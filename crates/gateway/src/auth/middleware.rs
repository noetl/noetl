use axum::{
    extract::{Request, State},
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
};
use std::sync::Arc;

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
        return Err((StatusCode::UNAUTHORIZED, "Missing authentication token").into_response());
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

    let session = super::resolve_session_cache_or_db(state.as_ref(), token)
        .await
        .map_err(|e| {
            tracing::error!("Session validation failed: {:?}", e);
            e.into_response()
        })?;

    let cached = if let Some(cached) = session {
        cached
    } else {
        tracing::warn!("Invalid or expired session token");
        return Err((StatusCode::UNAUTHORIZED, "Invalid or expired session").into_response());
    };

    let user_context = UserContext {
        user_id: cached.user_id,
        email: cached.email,
        display_name: cached.display_name,
        session_token: token.to_string(),
    };

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
