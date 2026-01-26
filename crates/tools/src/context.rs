//! Execution context for tool operations.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Execution context passed to tools during execution.
///
/// Contains all the information a tool needs to execute:
/// - Execution metadata (id, step)
/// - Variables for template rendering
/// - Secrets for authentication
/// - Server URL for API calls
#[derive(Debug, Clone, Serialize, Deserialize)]
#[derive(Default)]
pub struct ExecutionContext {
    /// Unique execution ID.
    pub execution_id: i64,

    /// Current step name.
    pub step: String,

    /// Variables available for template rendering.
    #[serde(default)]
    pub variables: HashMap<String, serde_json::Value>,

    /// Secrets for authentication (decrypted).
    #[serde(default, skip_serializing)]
    pub secrets: HashMap<String, String>,

    /// Control plane server URL.
    pub server_url: String,

    /// Worker ID executing this context.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub worker_id: Option<String>,

    /// Command ID being executed.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub command_id: Option<String>,

    /// Current call index within the step.
    #[serde(default)]
    pub call_index: usize,
}

impl ExecutionContext {
    /// Create a new execution context.
    pub fn new(execution_id: i64, step: impl Into<String>, server_url: impl Into<String>) -> Self {
        Self {
            execution_id,
            step: step.into(),
            variables: HashMap::new(),
            secrets: HashMap::new(),
            server_url: server_url.into(),
            worker_id: None,
            command_id: None,
            call_index: 0,
        }
    }

    /// Set a variable value.
    pub fn set_variable(&mut self, name: impl Into<String>, value: serde_json::Value) {
        self.variables.insert(name.into(), value);
    }

    /// Get a variable value.
    pub fn get_variable(&self, name: &str) -> Option<&serde_json::Value> {
        self.variables.get(name)
    }

    /// Get a variable as a string.
    pub fn get_variable_str(&self, name: &str) -> Option<String> {
        self.variables.get(name).map(|v| match v {
            serde_json::Value::String(s) => s.clone(),
            serde_json::Value::Number(n) => n.to_string(),
            serde_json::Value::Bool(b) => b.to_string(),
            _ => v.to_string(),
        })
    }

    /// Set a secret value.
    pub fn set_secret(&mut self, name: impl Into<String>, value: impl Into<String>) {
        self.secrets.insert(name.into(), value.into());
    }

    /// Get a secret value.
    pub fn get_secret(&self, name: &str) -> Option<&str> {
        self.secrets.get(name).map(|s| s.as_str())
    }

    /// Set the worker ID.
    pub fn with_worker_id(mut self, worker_id: impl Into<String>) -> Self {
        self.worker_id = Some(worker_id.into());
        self
    }

    /// Set the command ID.
    pub fn with_command_id(mut self, command_id: impl Into<String>) -> Self {
        self.command_id = Some(command_id.into());
        self
    }

    /// Increment and return the call index.
    pub fn next_call_index(&mut self) -> usize {
        let idx = self.call_index;
        self.call_index += 1;
        idx
    }

    /// Convert context to a flat map for template rendering.
    pub fn to_template_context(&self) -> HashMap<String, serde_json::Value> {
        let mut ctx = self.variables.clone();

        // Add execution metadata
        ctx.insert("execution_id".to_string(), serde_json::json!(self.execution_id));
        ctx.insert("step".to_string(), serde_json::json!(self.step));
        ctx.insert("server_url".to_string(), serde_json::json!(self.server_url));

        if let Some(ref worker_id) = self.worker_id {
            ctx.insert("worker_id".to_string(), serde_json::json!(worker_id));
        }

        if let Some(ref command_id) = self.command_id {
            ctx.insert("command_id".to_string(), serde_json::json!(command_id));
        }

        ctx
    }

    /// Merge another context's variables into this one.
    pub fn merge_variables(&mut self, other: &HashMap<String, serde_json::Value>) {
        for (k, v) in other {
            self.variables.insert(k.clone(), v.clone());
        }
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_context_new() {
        let ctx = ExecutionContext::new(12345, "process_data", "http://localhost:8082");
        assert_eq!(ctx.execution_id, 12345);
        assert_eq!(ctx.step, "process_data");
        assert_eq!(ctx.server_url, "http://localhost:8082");
    }

    #[test]
    fn test_context_variables() {
        let mut ctx = ExecutionContext::default();
        ctx.set_variable("name", serde_json::json!("test"));
        ctx.set_variable("count", serde_json::json!(42));

        assert_eq!(ctx.get_variable("name"), Some(&serde_json::json!("test")));
        assert_eq!(ctx.get_variable_str("count"), Some("42".to_string()));
        assert_eq!(ctx.get_variable("missing"), None);
    }

    #[test]
    fn test_context_secrets() {
        let mut ctx = ExecutionContext::default();
        ctx.set_secret("api_key", "secret123");

        assert_eq!(ctx.get_secret("api_key"), Some("secret123"));
        assert_eq!(ctx.get_secret("missing"), None);
    }

    #[test]
    fn test_context_builder() {
        let ctx = ExecutionContext::new(1, "step1", "http://localhost")
            .with_worker_id("worker-1")
            .with_command_id("cmd-123");

        assert_eq!(ctx.worker_id, Some("worker-1".to_string()));
        assert_eq!(ctx.command_id, Some("cmd-123".to_string()));
    }

    #[test]
    fn test_context_call_index() {
        let mut ctx = ExecutionContext::default();
        assert_eq!(ctx.next_call_index(), 0);
        assert_eq!(ctx.next_call_index(), 1);
        assert_eq!(ctx.next_call_index(), 2);
    }

    #[test]
    fn test_context_to_template() {
        let mut ctx = ExecutionContext::new(12345, "step1", "http://localhost");
        ctx.set_variable("input", serde_json::json!("value"));

        let template_ctx = ctx.to_template_context();
        assert_eq!(template_ctx.get("execution_id"), Some(&serde_json::json!(12345)));
        assert_eq!(template_ctx.get("step"), Some(&serde_json::json!("step1")));
        assert_eq!(template_ctx.get("input"), Some(&serde_json::json!("value")));
    }

    #[test]
    fn test_context_serialization() {
        let ctx = ExecutionContext::new(12345, "step1", "http://localhost");
        let json = serde_json::to_string(&ctx).unwrap();
        assert!(json.contains("\"execution_id\":12345"));
        // Secrets should not be serialized
        assert!(!json.contains("secrets"));
    }
}
