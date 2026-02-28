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
use crate::config::AuthPlaybooksConfig;
use crate::noetl_client::NoetlClient;
use crate::session_cache::SessionCache;

/// Combined state for auth handlers
#[derive(Clone)]
pub struct AuthState {
    pub noetl: Arc<NoetlClient>,
    pub callbacks: Arc<CallbackManager>,
    /// Configurable playbook paths for authentication
    pub playbook_config: AuthPlaybooksConfig,
    /// Session cache backed by NATS K/V
    pub session_cache: Arc<SessionCache>,
}

/// Authentication error responses
#[derive(Debug)]
pub enum AuthError {
    InvalidCredentials,
    InvalidCredentialsWithReason(String),
    InvalidSession,
    Unauthorized,
    NoetlError(String),
    InternalError(String),
}

impl IntoResponse for AuthError {
    fn into_response(self) -> Response {
        let (status, message) = match self {
            AuthError::InvalidCredentials => (StatusCode::UNAUTHORIZED, "Invalid credentials".to_string()),
            AuthError::InvalidCredentialsWithReason(msg) => (StatusCode::UNAUTHORIZED, msg),
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
    /// Auth0 domain (e.g., "your-tenant.auth0.com") - optional, defaults to configured domain
    #[serde(default)]
    pub auth0_domain: Option<String>,
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

fn parse_roles(value: Option<&serde_json::Value>) -> Vec<String> {
    match value {
        Some(serde_json::Value::Array(items)) => {
            items.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect()
        }
        Some(serde_json::Value::String(s)) => parse_roles_from_string(s),
        _ => Vec::new(),
    }
}

fn parse_roles_from_string(value: &str) -> Vec<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Vec::new();
    }
    if let Ok(list) = serde_json::from_str::<Vec<String>>(trimmed) {
        return list;
    }
    if trimmed.starts_with('{') && trimmed.ends_with('}') {
        let inner = &trimmed[1..trimmed.len() - 1];
        if inner.trim().is_empty() {
            return Vec::new();
        }
        return inner
            .split(',')
            .map(|part| part.trim().trim_matches('"').to_string())
            .filter(|role| !role.is_empty())
            .collect();
    }
    vec![trimmed.to_string()]
}

fn callback_data_keys(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::Object(map) => {
            let mut keys: Vec<&str> = map.keys().map(std::string::String::as_str).collect();
            keys.sort_unstable();
            let preview: Vec<&str> = keys.into_iter().take(8).collect();
            if preview.is_empty() {
                "[]".to_string()
            } else {
                format!("[{}]", preview.join(","))
            }
        }
        _ => "[]".to_string(),
    }
}

fn extract_callback_error(value: &serde_json::Value) -> Option<String> {
    let message = value.get("message").and_then(|v| v.as_str()).unwrap_or("").trim();
    let error = value.get("error").and_then(|v| v.as_str()).unwrap_or("").trim();

    match (message.is_empty(), error.is_empty()) {
        (true, true) => None,
        (false, true) => Some(message.to_string()),
        (true, false) => Some(error.to_string()),
        (false, false) => Some(format!("{}: {}", message, error)),
    }
}

pub async fn resolve_session_cache_or_db(
    state: &AuthState,
    session_token: &str,
) -> Result<Option<crate::session_cache::CachedSession>, AuthError> {
    if let Some(cached) = state.session_cache.get(session_token).await {
        return Ok(Some(cached));
    }

    let db_credential = &state.playbook_config.session_db_credential;
    tracing::debug!(
        "Session cache miss, validating via auth API (credential={})",
        db_credential
    );

    let validated = state
        .noetl
        .validate_session_via_api(session_token, db_credential)
        .await
        .map_err(|e| AuthError::NoetlError(format!("Session validation API failed: {}", e)))?;

    match validated {
        Some(found) => {
            let cached = crate::session_cache::CachedSession {
                session_token: session_token.to_string(),
                user_id: found.user_id,
                email: found.email,
                display_name: found.display_name,
                expires_at: found.expires_at,
                is_active: true,
                roles: found.roles,
            };

            if let Err(e) = state.session_cache.put(&cached).await {
                tracing::warn!("Failed to cache API-validated session: {}", e);
            }

            Ok(Some(cached))
        }
        None => {
            let _ = state.session_cache.invalidate(session_token).await;
            Ok(None)
        }
    }
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
    #[serde(default)]
    pub roles: Vec<String>,
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
    // Use provided domain or fall back to default
    let auth0_domain = req
        .auth0_domain
        .unwrap_or_else(|| "mestumre-development.us.auth0.com".to_string());
    tracing::info!("Auth login request for domain: {}", auth0_domain);

    // Register callback to receive result via NATS
    let (request_id, nats_subject, rx) = state.callbacks.register().await;
    tracing::debug!(
        "Registered callback request_id={}, subject={}",
        request_id,
        nats_subject
    );

    // Call NoETL auth0_login playbook with callback info
    // The gateway tool abstracts NATS - playbooks just see callback_subject
    let variables = serde_json::json!({
        "auth0_token": req.auth0_token,
        "auth0_refresh_token": req.auth0_refresh_token.unwrap_or_default(),
        "auth0_domain": auth0_domain,
        "session_duration_hours": req.session_duration_hours,
        "client_ip": req.client_ip.unwrap_or_else(|| "0.0.0.0".to_string()),
        "client_user_agent": req.client_user_agent.unwrap_or_else(|| "unknown".to_string()),
        "callback_subject": nats_subject,
        "request_id": request_id.clone(),
    });

    let playbook_path = &state.playbook_config.login;
    tracing::debug!("Using login playbook: {}", playbook_path);

    let result = state
        .noetl
        .execute_playbook(playbook_path, variables)
        .await
        .map_err(|e| {
            // Cancel callback on error
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            AuthError::NoetlError(format!("Login playbook failed: {}", e))
        })?;

    tracing::info!(
        "Auth login execution_id: {}, request_id: {}",
        result.execution_id,
        request_id
    );

    // Wait for callback with configurable timeout
    let timeout_secs = state.playbook_config.timeout_secs;
    let callback_result = timeout(Duration::from_secs(timeout_secs), rx)
        .await
        .map_err(|_| {
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            AuthError::InternalError("Login playbook timed out".to_string())
        })?
        .map_err(|_| AuthError::InternalError("Callback channel closed".to_string()))?;

    tracing::info!(
        "Received callback for request_id={}, status={}, data_keys={}",
        request_id,
        callback_result.status,
        callback_data_keys(&callback_result.data)
    );

    // Extract output from callback data
    let output = callback_result.data;

    if callback_result.status != "success" {
        let reason = extract_callback_error(&output).unwrap_or_else(|| "Invalid credentials".to_string());
        tracing::warn!(
            "Auth login failed for request_id={} status={} reason={}",
            request_id,
            callback_result.status,
            reason
        );
        return Err(AuthError::InvalidCredentialsWithReason(reason));
    }

    let status_str = output
        .get("status")
        .and_then(|v| v.as_str())
        .ok_or_else(|| AuthError::InternalError("Login callback missing status field".to_string()))?;

    if status_str != "authenticated" {
        let reason =
            extract_callback_error(&output).unwrap_or_else(|| format!("Authentication status: {}", status_str));
        tracing::warn!(
            "Auth login rejected for request_id={} status={} reason={}",
            request_id,
            status_str,
            reason
        );
        return Err(AuthError::InvalidCredentialsWithReason(reason));
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
    let roles = parse_roles(user_obj.get("roles"));

    // user_id can be either a number or string (from Jinja2 templates)
    let user_id = user_obj
        .get("user_id")
        .and_then(|v| v.as_i64().or_else(|| v.as_str().and_then(|s| s.parse::<i64>().ok())))
        .ok_or_else(|| AuthError::InternalError("Invalid user_id".to_string()))? as i32;

    let user = UserInfo {
        user_id,
        email: email.clone(),
        // Use display_name if present, otherwise fall back to email
        display_name: user_obj
            .get("display_name")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| email.clone()),
        roles,
    };

    let expires_at = output
        .get("expires_at")
        .and_then(|v| v.as_str())
        .ok_or_else(|| AuthError::InternalError("Invalid expires_at".to_string()))?
        .to_string();

    tracing::info!("Auth login successful for user: {}", user.email);

    // Cache the session for fast validation on subsequent requests
    let cached_session = crate::session_cache::CachedSession {
        session_token: session_token.clone(),
        user_id: user.user_id,
        email: user.email.clone(),
        display_name: user.display_name.clone(),
        expires_at: expires_at.clone(),
        is_active: true,
        roles: user.roles.clone(),
    };
    if let Err(e) = state.session_cache.put(&cached_session).await {
        tracing::warn!("Failed to cache session after login: {}", e);
    }

    Ok(Json(LoginResponse {
        status: "authenticated".to_string(),
        session_token,
        user,
        expires_at,
        message: "Authentication successful".to_string(),
    }))
}

/// Validate session endpoint - checks if session token is valid.
/// Uses cache-first strategy: checks NATS K/V first, then NoETL Postgres API.
pub async fn validate_session(
    State(state): State<Arc<AuthState>>,
    Json(req): Json<ValidateSessionRequest>,
) -> Result<Json<ValidateSessionResponse>, AuthError> {
    tracing::info!("Auth validate_session request");
    let session = resolve_session_cache_or_db(state.as_ref(), &req.session_token).await?;

    if let Some(cached) = session {
        return Ok(Json(ValidateSessionResponse {
            valid: true,
            user: Some(UserInfo {
                user_id: cached.user_id,
                email: cached.email,
                display_name: cached.display_name,
                roles: cached.roles,
            }),
            expires_at: Some(cached.expires_at),
            message: "Session is valid".to_string(),
        }));
    }

    Ok(Json(ValidateSessionResponse {
        valid: false,
        user: None,
        expires_at: None,
        message: "Session is invalid or expired".to_string(),
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
    // Note: playbook expects "action" not "permission_type"
    let variables = serde_json::json!({
        "session_token": req.session_token,
        "playbook_path": req.playbook_path,
        "action": req.permission_type,
        "callback_subject": nats_subject,
        "request_id": request_id.clone(),
    });

    let playbook_path = &state.playbook_config.check_access;
    tracing::debug!("Using check_access playbook: {}", playbook_path);

    let result = state
        .noetl
        .execute_playbook(playbook_path, variables)
        .await
        .map_err(|e| {
            let callbacks = state.callbacks.clone();
            let req_id = request_id.clone();
            tokio::spawn(async move { callbacks.cancel(&req_id).await });
            AuthError::NoetlError(format!("Check access playbook failed: {}", e))
        })?;

    tracing::info!(
        "Auth check_access execution_id: {}, request_id: {}",
        result.execution_id,
        request_id
    );

    // Wait for callback with configurable timeout
    let timeout_secs = state.playbook_config.timeout_secs;
    let callback_result = timeout(Duration::from_secs(timeout_secs), rx)
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
            email: u.get("email").and_then(|v| v.as_str()).unwrap_or("unknown").to_string(),
            display_name: u
                .get("display_name")
                .and_then(|v| v.as_str())
                .unwrap_or("Unknown User")
                .to_string(),
            roles: parse_roles(u.get("roles")),
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

/// Internal callback request body - matches CallbackResult structure
#[derive(Debug, Deserialize)]
pub struct InternalCallbackRequest {
    pub request_id: String,
    #[serde(default)]
    pub execution_id: Option<String>,
    #[serde(default)]
    pub step: Option<String>,
    #[serde(default = "default_callback_status")]
    pub status: String,
    #[serde(default)]
    pub data: serde_json::Value,
}

fn default_callback_status() -> String {
    "success".to_string()
}

/// Internal callback response
#[derive(Debug, Serialize)]
pub struct InternalCallbackResponse {
    pub delivered: bool,
    pub message: String,
}

/// Internal callback endpoint - allows workers to deliver results via HTTP
/// This is an alternative to NATS-based callbacks for simpler deployments.
///
/// Endpoint: POST /api/internal/callback
///
/// Workers can call this using the standard http tool:
/// ```yaml
/// - sink:
///     tool:
///       kind: http
///       method: POST
///       url: "http://gateway:8090/api/internal/callback"
///       headers:
///         Content-Type: application/json
///       body:
///         request_id: "{{ request_id }}"
///         status: "{{ result.status }}"
///         data:
///           session_token: "{{ result.session_token }}"
///           user: ...
/// ```
pub async fn internal_callback(
    State(state): State<Arc<AuthState>>,
    Json(req): Json<InternalCallbackRequest>,
) -> Json<InternalCallbackResponse> {
    tracing::info!(
        "Internal callback received: request_id={}, status={}, step={:?}, data_keys={}",
        req.request_id,
        req.status,
        req.step,
        callback_data_keys(&req.data)
    );

    // Convert to CallbackResult and deliver
    let callback_result = crate::callbacks::CallbackResult {
        request_id: req.request_id.clone(),
        execution_id: req.execution_id,
        step: req.step,
        status: req.status,
        data: req.data,
    };

    let delivered = state.callbacks.deliver(callback_result).await;

    if delivered {
        tracing::info!("Callback delivered for request_id={}", req.request_id);
        Json(InternalCallbackResponse {
            delivered: true,
            message: "Callback delivered successfully".to_string(),
        })
    } else {
        tracing::warn!("No pending request for callback request_id={}", req.request_id);
        Json(InternalCallbackResponse {
            delivered: false,
            message: "No pending request found for this request_id".to_string(),
        })
    }
}
