use axum::{
    extract::{Request, State},
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
};
use std::sync::Arc;

use crate::noetl_client::NoetlClient;

use super::types::UserContext;

/// Middleware to validate session token and inject user context
pub async fn auth_middleware(
    State(noetl): State<Arc<NoetlClient>>,
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

    // Validate session via NoETL playbook
    let variables = serde_json::json!({
        "session_token": token,
    });

    let result = noetl
        .execute_playbook("api_integration/auth0/auth0_validate_session", variables)
        .await
        .map_err(|e| {
            tracing::error!("Session validation failed: {}", e);
            (StatusCode::INTERNAL_SERVER_ERROR, "Session validation failed").into_response()
        })?;

    // Poll for result (simplified - in production use event system)
    tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;

    let status_result = noetl
        .get_playbook_status(&result.execution_id)
        .await
        .map_err(|e| {
            tracing::error!("Failed to get validation status: {}", e);
            (StatusCode::INTERNAL_SERVER_ERROR, "Failed to verify session").into_response()
        })?;

    let output = status_result.get("output").ok_or_else(|| {
        tracing::error!("No output from validation playbook");
        (StatusCode::INTERNAL_SERVER_ERROR, "Invalid validation response").into_response()
    })?;

    let valid = output.get("valid").and_then(|v| v.as_bool()).unwrap_or(false);

    if !valid {
        tracing::warn!("Invalid or expired session token");
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
            .ok_or_else(|| {
                (StatusCode::INTERNAL_SERVER_ERROR, "Invalid display_name").into_response()
            })?
            .to_string(),
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
