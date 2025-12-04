use anyhow::Context;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Clone, Debug)]
pub struct NoetlClient {
    base_url: String,
    http: reqwest::Client,
}

impl NoetlClient {
    pub fn new(base_url: String) -> Self {
        Self { base_url, http: reqwest::Client::new() }
    }

    pub async fn execute_playbook(&self, name: &str, variables: serde_json::Value) -> anyhow::Result<ExecutionResponse> {
        // NOTE: Align path with your NoETL API per openapi.json. Placeholder used here.
        let url = format!("{}/api/playbooks/execute", self.base_url.trim_end_matches('/'));
        let payload = ExecuteRequest { name: name.to_string(), variables };
        let res = self.http.post(url)
            .json(&payload)
            .send().await
            .context("noetl execute_playbook: send")?;
        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        if !status.is_success() {
            return Err(anyhow::anyhow!("NoETL execute failed: {} - {}", status, body));
        }
        let parsed: ExecutionResponse = serde_json::from_str(&body)
            .context("parse execute response")?;
        Ok(parsed)
    }

    pub async fn get_playbook_status(&self, execution_id: &str) -> anyhow::Result<serde_json::Value> {
        // Placeholder path; adjust to real API
        let url = format!("{}/api/playbooks/executions/{}/status", self.base_url.trim_end_matches('/'), execution_id);
        let res = self.http.get(url).send().await.context("noetl get status: send")?;
        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        if !status.is_success() {
            return Err(anyhow::anyhow!("NoETL status failed: {} - {}", status, body));
        }
        let parsed: serde_json::Value = serde_json::from_str(&body).context("parse status json")?;
        Ok(parsed)
    }
}

#[derive(Debug, Serialize)]
struct ExecuteRequest {
    name: String,
    #[serde(default)]
    variables: serde_json::Value,
}

#[derive(Debug, Deserialize, Clone)]
pub struct ExecutionResponse {
    pub execution_id: String,
    pub name: Option<String>,
    pub status: Option<String>,
}
