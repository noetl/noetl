//! Control plane HTTP client.

use anyhow::Result;
use reqwest::StatusCode;
use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Result of claiming a command.
#[derive(Debug, Clone)]
pub enum ClaimResult {
    /// Successfully claimed the command.
    Claimed,
    /// Command already claimed by another worker.
    AlreadyClaimed,
    /// Failed to claim (error).
    Failed(String),
}

/// Command fetched from the control plane.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Command {
    /// Execution ID.
    pub execution_id: i64,

    /// Event ID.
    pub event_id: i64,

    /// Command ID.
    pub command_id: String,

    /// Step name.
    pub step: String,

    /// Tool specification.
    pub tool: serde_json::Value,

    /// Case/when/then evaluation rules.
    #[serde(default)]
    pub cases: Vec<serde_json::Value>,

    /// Variables for template rendering.
    #[serde(default)]
    pub variables: std::collections::HashMap<String, serde_json::Value>,

    /// Secrets (decrypted).
    #[serde(default)]
    pub secrets: std::collections::HashMap<String, String>,
}

/// Event to emit to the control plane.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkerEvent {
    /// Event type (e.g., "command.claimed", "command.started", "command.completed").
    pub event_type: String,

    /// Execution ID.
    pub execution_id: i64,

    /// Event payload.
    pub payload: serde_json::Value,
}

/// HTTP client for control plane API.
#[derive(Clone)]
pub struct ControlPlaneClient {
    client: reqwest::Client,
    server_url: String,
}

impl ControlPlaneClient {
    /// Create a new control plane client.
    pub fn new(server_url: &str) -> Self {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .unwrap_or_default();

        Self {
            client,
            server_url: server_url.trim_end_matches('/').to_string(),
        }
    }

    /// Claim a command by emitting a command.claimed event.
    ///
    /// Returns Claimed if successful, AlreadyClaimed if 409, Failed otherwise.
    pub async fn claim_command(
        &self,
        execution_id: i64,
        command_id: &str,
        worker_id: &str,
    ) -> Result<ClaimResult> {
        let event = WorkerEvent {
            event_type: "command.claimed".to_string(),
            execution_id,
            payload: serde_json::json!({
                "command_id": command_id,
                "worker_id": worker_id,
            }),
        };

        let response = self
            .client
            .post(format!("{}/api/events", self.server_url))
            .json(&event)
            .send()
            .await?;

        match response.status() {
            StatusCode::OK | StatusCode::CREATED => Ok(ClaimResult::Claimed),
            StatusCode::CONFLICT => Ok(ClaimResult::AlreadyClaimed),
            status => {
                let body = response.text().await.unwrap_or_default();
                Ok(ClaimResult::Failed(format!("Status {}: {}", status, body)))
            }
        }
    }

    /// Fetch full command details from the control plane.
    pub async fn fetch_command(&self, event_id: i64) -> Result<Command> {
        let response = self
            .client
            .get(format!("{}/api/commands/{}", self.server_url, event_id))
            .send()
            .await?;

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to fetch command: {}", body);
        }

        let command: Command = response.json().await?;
        Ok(command)
    }

    /// Emit an event to the control plane.
    pub async fn emit_event(&self, event: WorkerEvent) -> Result<()> {
        let response = self
            .client
            .post(format!("{}/api/events", self.server_url))
            .json(&event)
            .send()
            .await?;

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to emit event: {}", body);
        }

        Ok(())
    }

    /// Emit an event with retry.
    pub async fn emit_event_with_retry(
        &self,
        event: WorkerEvent,
        max_retries: u32,
    ) -> Result<()> {
        let mut delay = Duration::from_millis(500);

        for attempt in 0..=max_retries {
            match self.emit_event(event.clone()).await {
                Ok(()) => return Ok(()),
                Err(e) if attempt < max_retries => {
                    tracing::warn!(
                        attempt = attempt + 1,
                        max_retries,
                        error = %e,
                        "Event emission failed, retrying"
                    );
                    tokio::time::sleep(delay).await;
                    delay = std::cmp::min(delay * 2, Duration::from_secs(10));
                }
                Err(e) => return Err(e),
            }
        }

        Ok(())
    }

    /// Get a variable value for an execution.
    pub async fn get_variable(
        &self,
        execution_id: i64,
        name: &str,
    ) -> Result<Option<serde_json::Value>> {
        let response = self
            .client
            .get(format!("{}/api/vars/{}/{}", self.server_url, execution_id, name))
            .send()
            .await?;

        if response.status() == StatusCode::NOT_FOUND {
            return Ok(None);
        }

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to get variable: {}", body);
        }

        let value: serde_json::Value = response.json().await?;
        Ok(Some(value))
    }

    /// Set a variable value for an execution.
    pub async fn set_variable(
        &self,
        execution_id: i64,
        name: &str,
        value: serde_json::Value,
    ) -> Result<()> {
        let response = self
            .client
            .post(format!("{}/api/vars/{}", self.server_url, execution_id))
            .json(&serde_json::json!({
                name: value
            }))
            .send()
            .await?;

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to set variable: {}", body);
        }

        Ok(())
    }

    /// Register the worker pool with the control plane.
    pub async fn register_worker(
        &self,
        worker_id: &str,
        pool_name: &str,
        hostname: &str,
    ) -> Result<()> {
        let response = self
            .client
            .post(format!("{}/api/worker/pool/register", self.server_url))
            .json(&serde_json::json!({
                "worker_id": worker_id,
                "pool_name": pool_name,
                "hostname": hostname,
            }))
            .send()
            .await?;

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to register worker: {}", body);
        }

        Ok(())
    }

    /// Send a heartbeat to the control plane.
    pub async fn heartbeat(&self, worker_id: &str, pool_name: &str) -> Result<()> {
        let response = self
            .client
            .post(format!("{}/api/worker/pool/heartbeat", self.server_url))
            .json(&serde_json::json!({
                "worker_id": worker_id,
                "pool_name": pool_name,
            }))
            .send()
            .await?;

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            tracing::warn!("Heartbeat failed: {}", body);
        }

        Ok(())
    }

    /// Deregister the worker pool.
    pub async fn deregister_worker(&self, worker_id: &str, pool_name: &str) -> Result<()> {
        let response = self
            .client
            .delete(format!("{}/api/worker/pool/deregister", self.server_url))
            .json(&serde_json::json!({
                "worker_id": worker_id,
                "pool_name": pool_name,
            }))
            .send()
            .await?;

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            tracing::warn!("Deregister failed: {}", body);
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_worker_event_serialization() {
        let event = WorkerEvent {
            event_type: "command.started".to_string(),
            execution_id: 12345,
            payload: serde_json::json!({"command_id": "cmd-123"}),
        };

        let json = serde_json::to_string(&event).unwrap();
        assert!(json.contains("command.started"));
        assert!(json.contains("12345"));
    }

    #[test]
    fn test_command_deserialization() {
        let json = serde_json::json!({
            "execution_id": 12345,
            "event_id": 67890,
            "command_id": "cmd-abc",
            "step": "process",
            "tool": {"kind": "shell", "command": "echo hello"},
            "cases": [],
            "variables": {},
            "secrets": {}
        });

        let command: Command = serde_json::from_value(json).unwrap();
        assert_eq!(command.execution_id, 12345);
        assert_eq!(command.step, "process");
    }

    #[test]
    fn test_client_creation() {
        let client = ControlPlaneClient::new("http://localhost:8082");
        assert_eq!(client.server_url, "http://localhost:8082");

        let client = ControlPlaneClient::new("http://localhost:8082/");
        assert_eq!(client.server_url, "http://localhost:8082");
    }
}
