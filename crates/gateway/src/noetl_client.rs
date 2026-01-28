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
    /// POST /api/run/playbook with { path, args }
    pub async fn execute_playbook(&self, path: &str, args: serde_json::Value) -> anyhow::Result<ExecutionResponse> {
        let url = format!("{}/api/run/playbook", self.base_url.trim_end_matches('/'));
        let payload = serde_json::json!({ "path": path, "args": args });

        let res = self.http.post(&url).json(&payload).send().await
            .context("execute_playbook: send")?;

        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        if !status.is_success() {
            return Err(anyhow::anyhow!("Execute playbook failed: {} - {}", status, body));
        }

        let parsed: ExecutionResponse = serde_json::from_str(&body)
            .context("parse execution response")?;
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

        let res = self.http.get(&url).send().await
            .context("get_playbook_status: send")?;

        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        if !status.is_success() {
            return Err(anyhow::anyhow!("Get playbook status failed: {} - {}", status, body));
        }

        let parsed: serde_json::Value = serde_json::from_str(&body)
            .context("parse status json")?;
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
        serde_json::from_str(&body)
            .or_else(|_| Ok(serde_json::json!({ "data": body })))
    }
}

// Response types

#[derive(Debug, Deserialize, Clone)]
pub struct ExecutionResponse {
    pub execution_id: String,
    pub name: Option<String>,
    pub status: Option<String>,
    pub path: Option<String>,
}
