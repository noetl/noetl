use axum::{
    extract::{Request, State},
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
};
use std::sync::Arc;
use tokio::time::{timeout, Duration};

use super::types::UserContext;
use super::AuthState;

/// Check if auth bypass is enabled (for development/testing)
fn is_auth_bypass_enabled() -> bool {
    std::env::var("GATEWAY_AUTH_BYPASS")
        .map(|v| v == "true" || v == "1")
        .unwrap_or(false)
}

/// Middleware to validate session token and inject user context
pub async fn auth_middleware(
    State(state): State<Arc<AuthState>>,
    mut request: Request,
    next: Next,
) -> Result<Response, Response> {
    // Extract session token from Authorization header or cookie
    let session_token = extract_session_token(&request);

    if session_token.is_none() {
        tracing::warn!("No session token provided");
        return Err((
            StatusCode::UNAUTHORIZED,
            "Missing authentication token",
        )
            .into_response());
    }

    let token = session_token.unwrap();

    // Development mode: bypass validation but still require a token
    if is_auth_bypass_enabled() {
        tracing::warn!("AUTH BYPASS ENABLED - skipping session validation (dev mode)");
        let user_context = UserContext {
            user_id: 0,
            email: "dev@localhost".to_string(),
            display_name: "Dev User".to_string(),
            session_token: token.to_string(),
        };
        request.extensions_mut().insert(user_context);
        return Ok(next.run(request).await);
    }

    // Check session cache first for fast validation
    if let Some(cached) = state.session_cache.get(token).await {
        tracing::debug!("Middleware: session cache HIT for user={}", cached.email);
        let user_context = UserContext {
            user_id: cached.user_id,
            email: cached.email,
            display_name: cached.display_name,
            session_token: token.to_string(),
        };
        request.extensions_mut().insert(user_context);
        return Ok(next.run(request).await);
    }

    // Cache miss - validate via playbook
    tracing::debug!("Middleware: session cache MISS, calling playbook");

    // Register callback to receive result
    let (request_id, callback_subject, rx) = state.callbacks.register().await;

    // Validate session via NoETL playbook with callback info
    // The gateway tool abstracts NATS - playbooks just see callback_subject
    let variables = serde_json::json!({
        "session_token": token,
        "callback_subject": callback_subject,
        "request_id": request_id.clone(),
    });

    let result = state.noetl
        .execute_playbook("api_integration/auth0/auth0_validate_session", variables)
        .await
        .map_err(|e| {
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            tracing::error!("Session validation failed: {}", e);
            (StatusCode::INTERNAL_SERVER_ERROR, "Session validation failed").into_response()
        })?;

    tracing::debug!("Middleware validation execution_id: {}, request_id: {}", result.execution_id, request_id);

    // Wait for callback with 30 second timeout
    let callback_result = timeout(Duration::from_secs(30), rx)
        .await
        .map_err(|_| {
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            tracing::error!("Validation playbook timed out");
            (StatusCode::INTERNAL_SERVER_ERROR, "Session validation timed out").into_response()
        })?
        .map_err(|_| {
            tracing::error!("Callback channel closed");
            (StatusCode::INTERNAL_SERVER_ERROR, "Callback channel closed").into_response()
        })?;

    let output = callback_result.data;

    let valid = output.get("valid").and_then(|v| v.as_bool()).unwrap_or(false);

    if !valid {
        tracing::warn!("Invalid or expired session token");
        // Invalidate any stale cache entry
        let _ = state.session_cache.invalidate(token).await;
        return Err((StatusCode::UNAUTHORIZED, "Invalid or expired session").into_response());
    }

    // Extract user context
    let user_obj = output.get("user").ok_or_else(|| {
        tracing::error!("No user data in validation response");
        (StatusCode::INTERNAL_SERVER_ERROR, "Invalid user data").into_response()
    })?;

    let user_context = UserContext {
        user_id: user_obj
            .get("user_id")
            .and_then(|v| v.as_i64())
            .ok_or_else(|| {
                (StatusCode::INTERNAL_SERVER_ERROR, "Invalid user_id").into_response()
            })? as i32,
        email: user_obj
            .get("email")
            .and_then(|v| v.as_str())
            .ok_or_else(|| (StatusCode::INTERNAL_SERVER_ERROR, "Invalid email").into_response())?
            .to_string(),
        display_name: user_obj
            .get("display_name")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown User")
            .to_string(),
        session_token: token.to_string(),
    };
    let roles = super::parse_roles(user_obj.get("roles"));

    // Cache the validated session for future requests
    let expires_at = output
        .get("expires_at")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    let cached_session = crate::session_cache::CachedSession {
        session_token: token.to_string(),
        user_id: user_context.user_id,
        email: user_context.email.clone(),
        display_name: user_context.display_name.clone(),
        expires_at,
        is_active: true,
        roles,
    };
    if let Err(e) = state.session_cache.put(&cached_session).await {
        tracing::warn!("Failed to cache session: {}", e);
    }

    tracing::info!("Authenticated user: {} ({})", user_context.email, user_context.user_id);

    // Inject user context into request extensions
    request.extensions_mut().insert(user_context);

    // Continue to next middleware/handler
    Ok(next.run(request).await)
}

/// Extract session token from request headers or cookies
fn extract_session_token(request: &Request) -> Option<&str> {
    // Try Authorization header first: "Bearer <token>"
    if let Some(auth_header) = request.headers().get("authorization") {
        if let Ok(auth_str) = auth_header.to_str() {
            if let Some(token) = auth_str.strip_prefix("Bearer ") {
                return Some(token);
            }
        }
    }

    // Try X-Session-Token header
    if let Some(session_header) = request.headers().get("x-session-token") {
        if let Ok(token) = session_header.to_str() {
            return Some(token);
        }
    }

    // Try Cookie header: "session_token=<token>"
    if let Some(cookie_header) = request.headers().get("cookie") {
        if let Ok(cookie_str) = cookie_header.to_str() {
            for cookie in cookie_str.split(';') {
                let parts: Vec<&str> = cookie.trim().splitn(2, '=').collect();
                if parts.len() == 2 && parts[0] == "session_token" {
                    return Some(parts[1]);
                }
            }
        }
    }

    None
}
