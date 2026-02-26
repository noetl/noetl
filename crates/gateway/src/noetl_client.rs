//! NoETL client for authentication and playbook execution.
//!
//! This module provides the HTTP client for communicating with the NoETL server.
//! Most API calls should go through the proxy route (/noetl/*) which forwards
//! authenticated requests directly to NoETL. This client is primarily used for
//! authentication playbooks and legacy executePlaybook mutation.

use anyhow::Context;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug)]
pub struct NoetlClient {
    base_url: String,
    http: reqwest::Client,
}

#[derive(Debug, Clone)]
pub struct ValidatedSession {
    pub user_id: i32,
    pub email: String,
    pub display_name: String,
    pub expires_at: String,
    pub roles: Vec<String>,
}

impl NoetlClient {
    pub fn new(base_url: String) -> Self {
        Self {
            base_url,
            http: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(120))
                .build()
                .unwrap_or_default(),
        }
    }

    pub fn base_url(&self) -> &str {
        &self.base_url
    }

    /// Execute a playbook by path.
    /// POST /api/execute with { path, payload }
    pub async fn execute_playbook(&self, path: &str, args: serde_json::Value) -> anyhow::Result<ExecutionResponse> {
        let url = format!("{}/api/execute", self.base_url.trim_end_matches('/'));
        let payload = serde_json::json!({ "path": path, "payload": args });

        let res = self
            .http
            .post(&url)
            .json(&payload)
            .send()
            .await
            .context("execute_playbook: send")?;

        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        if !status.is_success() {
            return Err(anyhow::anyhow!("Execute playbook failed: {} - {}", status, body));
        }

        let parsed: ExecutionResponse = serde_json::from_str(&body).context("parse execution response")?;
        Ok(parsed)
    }

    /// Get execution status (used by auth module for login/validate playbooks).
    /// GET /api/executions/{id}/status
    pub async fn get_playbook_status(&self, execution_id: &str) -> anyhow::Result<serde_json::Value> {
        let url = format!(
            "{}/api/executions/{}/status",
            self.base_url.trim_end_matches('/'),
            execution_id
        );

        let res = self.http.get(&url).send().await.context("get_playbook_status: send")?;

        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        if !status.is_success() {
            return Err(anyhow::anyhow!("Get playbook status failed: {} - {}", status, body));
        }

        let parsed: serde_json::Value = serde_json::from_str(&body).context("parse status json")?;
        Ok(parsed)
    }

    /// Generic API call for proxy support.
    /// This allows the GraphQL schema to provide a proxyRequest mutation.
    pub async fn api_call(
        &self,
        method: &str,
        endpoint: &str,
        body: Option<serde_json::Value>,
    ) -> anyhow::Result<serde_json::Value> {
        let url = format!("{}{}", self.base_url.trim_end_matches('/'), endpoint);

        let mut req = match method.to_uppercase().as_str() {
            "GET" => self.http.get(&url),
            "POST" => self.http.post(&url),
            "PUT" => self.http.put(&url),
            "DELETE" => self.http.delete(&url),
            "PATCH" => self.http.patch(&url),
            _ => return Err(anyhow::anyhow!("Unsupported HTTP method: {}", method)),
        };

        if let Some(body) = body {
            req = req.json(&body);
        }

        let res = req.send().await.context("api_call: send")?;

        let status = res.status();
        let body = res.text().await.unwrap_or_default();

        if !status.is_success() {
            return Err(anyhow::anyhow!("API call failed: {} - {}", status, body));
        }

        // Try to parse as JSON, fall back to wrapping string in JSON
        serde_json::from_str(&body).or_else(|_| Ok(serde_json::json!({ "data": body })))
    }

    /// Validate session token via dedicated NoETL auth API.
    /// This is used as cache-miss fallback for gateway auth validation.
    pub async fn validate_session_via_api(
        &self,
        session_token: &str,
        credential: &str,
    ) -> anyhow::Result<Option<ValidatedSession>> {
        let url = format!("{}/api/auth/session/validate", self.base_url.trim_end_matches('/'));
        let payload = serde_json::json!({
            "session_token": session_token,
            "credential": credential,
        });

        let res = self
            .http
            .post(&url)
            .json(&payload)
            .send()
            .await
            .context("validate_session_via_api: send")?;

        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        if !status.is_success() {
            return Err(anyhow::anyhow!(
                "Validate session API request failed: {} - {}",
                status,
                body
            ));
        }

        let parsed: AuthSessionValidateResponse =
            serde_json::from_str(&body).context("validate_session_via_api: parse response")?;

        if parsed.status != "ok" {
            let message = parsed
                .error
                .unwrap_or_else(|| "unknown auth session validation error".to_string());
            return Err(anyhow::anyhow!("Validate session API error: {}", message));
        }

        if !parsed.valid {
            return Ok(None);
        }

        let user = parsed
            .user
            .ok_or_else(|| anyhow::anyhow!("validate_session_via_api: missing user payload"))?;

        Ok(Some(ValidatedSession {
            user_id: user.user_id,
            email: user.email,
            display_name: user.display_name,
            expires_at: parsed.expires_at.unwrap_or_default(),
            roles: user.roles,
        }))
    }
}

// Response types

#[derive(Debug, Deserialize, Clone)]
struct AuthSessionValidateResponse {
    status: String,
    valid: bool,
    user: Option<AuthSessionValidateUser>,
    expires_at: Option<String>,
    error: Option<String>,
}

#[derive(Debug, Deserialize, Clone)]
struct AuthSessionValidateUser {
    user_id: i32,
    email: String,
    display_name: String,
    #[serde(default)]
    roles: Vec<String>,
}

#[derive(Debug, Deserialize, Clone)]
pub struct ExecutionResponse {
    pub execution_id: String,
    pub name: Option<String>,
    pub status: Option<String>,
    pub path: Option<String>,
}
