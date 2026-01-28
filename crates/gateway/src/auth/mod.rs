pub mod middleware;
pub mod types;

use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::time::{timeout, Duration};

use crate::callbacks::CallbackManager;
use crate::noetl_client::NoetlClient;

/// Combined state for auth handlers
#[derive(Clone)]
pub struct AuthState {
    pub noetl: Arc<NoetlClient>,
    pub callbacks: Arc<CallbackManager>,
}

/// Authentication error responses
#[derive(Debug)]
pub enum AuthError {
    InvalidCredentials,
    InvalidSession,
    Unauthorized,
    NoetlError(String),
    InternalError(String),
}

impl IntoResponse for AuthError {
    fn into_response(self) -> Response {
        let (status, message) = match self {
            AuthError::InvalidCredentials => (StatusCode::UNAUTHORIZED, "Invalid credentials".to_string()),
            AuthError::InvalidSession => (StatusCode::UNAUTHORIZED, "Invalid or expired session".to_string()),
            AuthError::Unauthorized => (StatusCode::FORBIDDEN, "Unauthorized access".to_string()),
            AuthError::NoetlError(msg) => (StatusCode::BAD_GATEWAY, msg),
            AuthError::InternalError(msg) => (StatusCode::INTERNAL_SERVER_ERROR, msg),
        };

        (status, Json(serde_json::json!({"error": message}))).into_response()
    }
}

/// Login request body
#[derive(Debug, Deserialize)]
pub struct LoginRequest {
    /// Auth0 access token
    pub auth0_token: String,
    /// Auth0 refresh token (optional)
    pub auth0_refresh_token: Option<String>,
    /// Auth0 domain (e.g., "your-tenant.auth0.com")
    pub auth0_domain: String,
    /// Session duration in hours (default: 8)
    #[serde(default = "default_session_duration")]
    pub session_duration_hours: i32,
    /// Client IP address (optional - will use request IP if not provided)
    pub client_ip: Option<String>,
    /// Client user agent (optional - will use request header if not provided)
    pub client_user_agent: Option<String>,
}

fn default_session_duration() -> i32 {
    8
}

/// Login response
#[derive(Debug, Serialize)]
pub struct LoginResponse {
    pub status: String,
    pub session_token: String,
    pub user: UserInfo,
    pub expires_at: String,
    pub message: String,
}

/// User information
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct UserInfo {
    pub user_id: i32,
    pub email: String,
    pub display_name: String,
}

/// Session validation request
#[derive(Debug, Deserialize)]
pub struct ValidateSessionRequest {
    pub session_token: String,
}

/// Session validation response
#[derive(Debug, Serialize)]
pub struct ValidateSessionResponse {
    pub valid: bool,
    pub user: Option<UserInfo>,
    pub expires_at: Option<String>,
    pub message: String,
}

/// Check playbook access request
#[derive(Debug, Deserialize)]
pub struct CheckAccessRequest {
    pub session_token: String,
    pub playbook_path: String,
    pub permission_type: String, // "execute", "view", "edit"
}

/// Check access response
#[derive(Debug, Serialize)]
pub struct CheckAccessResponse {
    pub allowed: bool,
    pub user: Option<UserInfo>,
    pub playbook_path: String,
    pub permission_type: String,
    pub message: String,
}

/// Login endpoint - authenticates user via Auth0 and creates session
pub async fn login(
    State(state): State<Arc<AuthState>>,
    Json(req): Json<LoginRequest>,
) -> Result<Json<LoginResponse>, AuthError> {
    tracing::info!("Auth login request for domain: {}", req.auth0_domain);

    // Register callback to receive result via NATS
    let (request_id, nats_subject, rx) = state.callbacks.register().await;
    tracing::debug!("Registered callback request_id={}, subject={}", request_id, nats_subject);

    // Call NoETL auth0_login playbook with callback info
    // The gateway tool abstracts NATS - playbooks just see callback_subject
    let variables = serde_json::json!({
        "auth0_token": req.auth0_token,
        "auth0_refresh_token": req.auth0_refresh_token.unwrap_or_default(),
        "auth0_domain": req.auth0_domain,
        "session_duration_hours": req.session_duration_hours,
        "client_ip": req.client_ip.unwrap_or_else(|| "0.0.0.0".to_string()),
        "client_user_agent": req.client_user_agent.unwrap_or_else(|| "unknown".to_string()),
        "callback_subject": nats_subject,
        "request_id": request_id.clone(),
    });

    let result = state.noetl
        .execute_playbook("api_integration/auth0/auth0_login", variables)
        .await
        .map_err(|e| {
            // Cancel callback on error
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            AuthError::NoetlError(format!("Login playbook failed: {}", e))
        })?;

    tracing::info!("Auth login execution_id: {}, request_id: {}", result.execution_id, request_id);

    // Wait for callback with 30 second timeout
    let callback_result = timeout(Duration::from_secs(30), rx)
        .await
        .map_err(|_| {
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            AuthError::InternalError("Login playbook timed out".to_string())
        })?
        .map_err(|_| AuthError::InternalError("Callback channel closed".to_string()))?;

    tracing::info!("Received callback for request_id={}, status={}", request_id, callback_result.status);

    // Extract output from callback data
    let output = callback_result.data;

    let status_str = output
        .get("status")
        .and_then(|v| v.as_str())
        .ok_or_else(|| AuthError::InvalidCredentials)?;

    if status_str != "authenticated" {
        return Err(AuthError::InvalidCredentials);
    }

    let session_token = output
        .get("session_token")
        .and_then(|v| v.as_str())
        .ok_or_else(|| AuthError::InternalError("No session token returned".to_string()))?
        .to_string();

    let user_obj = output
        .get("user")
        .ok_or_else(|| AuthError::InternalError("No user data returned".to_string()))?;

    let email = user_obj
        .get("email")
        .and_then(|v| v.as_str())
        .ok_or_else(|| AuthError::InternalError("Invalid email".to_string()))?
        .to_string();

    let user = UserInfo {
        user_id: user_obj
            .get("user_id")
            .and_then(|v| v.as_i64())
            .ok_or_else(|| AuthError::InternalError("Invalid user_id".to_string()))? as i32,
        email: email.clone(),
        // Use display_name if present, otherwise fall back to email
        display_name: user_obj
            .get("display_name")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| email.clone()),
    };

    let expires_at = output
        .get("expires_at")
        .and_then(|v| v.as_str())
        .ok_or_else(|| AuthError::InternalError("Invalid expires_at".to_string()))?
        .to_string();

    tracing::info!("Auth login successful for user: {}", user.email);

    Ok(Json(LoginResponse {
        status: "authenticated".to_string(),
        session_token,
        user,
        expires_at,
        message: "Authentication successful".to_string(),
    }))
}

/// Validate session endpoint - checks if session token is valid
pub async fn validate_session(
    State(state): State<Arc<AuthState>>,
    Json(req): Json<ValidateSessionRequest>,
) -> Result<Json<ValidateSessionResponse>, AuthError> {
    tracing::info!("Auth validate_session request");

    // Register callback to receive result via NATS
    let (request_id, nats_subject, rx) = state.callbacks.register().await;

    // Call NoETL auth0_validate_session playbook with callback info
    // The gateway tool abstracts NATS - playbooks just see callback_subject
    let variables = serde_json::json!({
        "session_token": req.session_token,
        "callback_subject": nats_subject,
        "request_id": request_id.clone(),
    });

    let result = state.noetl
        .execute_playbook("api_integration/auth0/auth0_validate_session", variables)
        .await
        .map_err(|e| {
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            AuthError::NoetlError(format!("Validate session playbook failed: {}", e))
        })?;

    tracing::info!("Auth validate_session execution_id: {}, request_id: {}", result.execution_id, request_id);

    // Wait for callback with 30 second timeout
    let callback_result = timeout(Duration::from_secs(30), rx)
        .await
        .map_err(|_| {
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            AuthError::InternalError("Validate session playbook timed out".to_string())
        })?
        .map_err(|_| AuthError::InternalError("Callback channel closed".to_string()))?;

    let output = callback_result.data;

    let valid = output.get("valid").and_then(|v| v.as_bool()).unwrap_or(false);

    if !valid {
        return Ok(Json(ValidateSessionResponse {
            valid: false,
            user: None,
            expires_at: None,
            message: "Session is invalid or expired".to_string(),
        }));
    }

    let user_obj = output.get("user");
    let user = if let Some(u) = user_obj {
        Some(UserInfo {
            user_id: u.get("user_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
            email: u
                .get("email")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string(),
            display_name: u
                .get("display_name")
                .and_then(|v| v.as_str())
                .unwrap_or("Unknown User")
                .to_string(),
        })
    } else {
        None
    };

    let expires_at = output
        .get("expires_at")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    tracing::info!("Auth validate_session valid: {}", valid);

    Ok(Json(ValidateSessionResponse {
        valid,
        user,
        expires_at,
        message: if valid {
            "Session is valid".to_string()
        } else {
            "Session is invalid".to_string()
        },
    }))
}

/// Check playbook access endpoint - verifies user has permission for playbook
pub async fn check_access(
    State(state): State<Arc<AuthState>>,
    Json(req): Json<CheckAccessRequest>,
) -> Result<Json<CheckAccessResponse>, AuthError> {
    tracing::info!(
        "Auth check_access request for playbook: {} permission: {}",
        req.playbook_path,
        req.permission_type
    );

    // Register callback to receive result via NATS
    let (request_id, nats_subject, rx) = state.callbacks.register().await;

    // Call NoETL check_playbook_access playbook with callback info
    // The gateway tool abstracts NATS - playbooks just see callback_subject
    let variables = serde_json::json!({
        "session_token": req.session_token,
        "playbook_path": req.playbook_path,
        "permission_type": req.permission_type,
        "callback_subject": nats_subject,
        "request_id": request_id.clone(),
    });

    let result = state.noetl
        .execute_playbook("api_integration/auth0/check_playbook_access", variables)
        .await
        .map_err(|e| {
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            AuthError::NoetlError(format!("Check access playbook failed: {}", e))
        })?;

    tracing::info!("Auth check_access execution_id: {}, request_id: {}", result.execution_id, request_id);

    // Wait for callback with 30 second timeout
    let callback_result = timeout(Duration::from_secs(30), rx)
        .await
        .map_err(|_| {
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            AuthError::InternalError("Check access playbook timed out".to_string())
        })?
        .map_err(|_| AuthError::InternalError("Callback channel closed".to_string()))?;

    let output = callback_result.data;

    let allowed = output.get("allowed").and_then(|v| v.as_bool()).unwrap_or(false);

    let user_obj = output.get("user");
    let user = if let Some(u) = user_obj {
        Some(UserInfo {
            user_id: u.get("user_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
            email: u
                .get("email")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string(),
            display_name: u
                .get("display_name")
                .and_then(|v| v.as_str())
                .unwrap_or("Unknown User")
                .to_string(),
        })
    } else {
        None
    };

    let message = output
        .get("message")
        .and_then(|v| v.as_str())
        .unwrap_or("Access check completed")
        .to_string();

    tracing::info!("Auth check_access allowed: {}", allowed);

    Ok(Json(CheckAccessResponse {
        allowed,
        user,
        playbook_path: req.playbook_path,
        permission_type: req.permission_type,
        message,
    }))
}
