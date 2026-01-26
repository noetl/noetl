//! Tool registry and dispatch.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;

use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::result::ToolResult;

/// Configuration for tool execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolConfig {
    /// Tool kind/type (e.g., "shell", "http", "rhai").
    pub kind: String,

    /// Tool-specific configuration.
    #[serde(flatten)]
    pub config: serde_json::Value,

    /// Timeout in seconds (optional).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timeout: Option<u64>,

    /// Retry configuration (optional).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub retry: Option<RetryConfig>,

    /// Authentication configuration (optional).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auth: Option<AuthConfig>,
}

/// Retry configuration for tool execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetryConfig {
    /// Maximum number of retries.
    #[serde(default = "default_max_retries")]
    pub max_retries: u32,

    /// Initial delay between retries in milliseconds.
    #[serde(default = "default_initial_delay_ms")]
    pub initial_delay_ms: u64,

    /// Maximum delay between retries in milliseconds.
    #[serde(default = "default_max_delay_ms")]
    pub max_delay_ms: u64,

    /// Exponential backoff multiplier.
    #[serde(default = "default_backoff_multiplier")]
    pub backoff_multiplier: f64,
}

fn default_max_retries() -> u32 {
    3
}

fn default_initial_delay_ms() -> u64 {
    500
}

fn default_max_delay_ms() -> u64 {
    10000
}

fn default_backoff_multiplier() -> f64 {
    2.0
}

impl Default for RetryConfig {
    fn default() -> Self {
        Self {
            max_retries: default_max_retries(),
            initial_delay_ms: default_initial_delay_ms(),
            max_delay_ms: default_max_delay_ms(),
            backoff_multiplier: default_backoff_multiplier(),
        }
    }
}

/// Authentication configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthConfig {
    /// Authentication type.
    #[serde(rename = "type")]
    pub auth_type: AuthType,

    /// Credential name (for credential lookup).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub credential: Option<String>,

    /// Token (for direct token auth).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,

    /// Username (for basic auth).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub username: Option<String>,

    /// Password (for basic auth).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub password: Option<String>,

    /// API key header name.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub header: Option<String>,

    /// GCP scopes (for ADC auth).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scopes: Option<Vec<String>>,
}

/// Authentication type.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
#[derive(Default)]
pub enum AuthType {
    /// Bearer token authentication.
    Bearer,
    /// Basic authentication (username/password).
    Basic,
    /// API key authentication.
    ApiKey,
    /// GCP Application Default Credentials.
    GcpAdc,
    /// No authentication.
    #[default]
    None,
}


/// Tool trait for implementing executable tools.
#[async_trait]
pub trait Tool: Send + Sync {
    /// Returns the tool's unique name/kind.
    fn name(&self) -> &'static str;

    /// Execute the tool with the given configuration and context.
    async fn execute(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError>;
}

/// Registry of available tools.
pub struct ToolRegistry {
    tools: HashMap<String, Arc<dyn Tool>>,
}

impl ToolRegistry {
    /// Create a new empty tool registry.
    pub fn new() -> Self {
        Self {
            tools: HashMap::new(),
        }
    }

    /// Register a tool.
    pub fn register<T: Tool + 'static>(&mut self, tool: T) {
        let name = tool.name().to_string();
        self.tools.insert(name, Arc::new(tool));
    }

    /// Get a tool by name.
    pub fn get(&self, name: &str) -> Option<Arc<dyn Tool>> {
        self.tools.get(name).cloned()
    }

    /// Check if a tool is registered.
    pub fn has(&self, name: &str) -> bool {
        self.tools.contains_key(name)
    }

    /// List all registered tool names.
    pub fn list(&self) -> Vec<&str> {
        self.tools.keys().map(|s| s.as_str()).collect()
    }

    /// Execute a tool by name.
    pub async fn execute(
        &self,
        name: &str,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let tool = self.get(name).ok_or_else(|| ToolError::NotFound(name.to_string()))?;
        tool.execute(config, ctx).await
    }

    /// Execute a tool from config (uses config.kind as tool name).
    pub async fn execute_from_config(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        self.execute(&config.kind, config, ctx).await
    }
}

impl Default for ToolRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Debug for ToolRegistry {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ToolRegistry")
            .field("tools", &self.tools.keys().collect::<Vec<_>>())
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct MockTool;

    #[async_trait]
    impl Tool for MockTool {
        fn name(&self) -> &'static str {
            "mock"
        }

        async fn execute(
            &self,
            _config: &ToolConfig,
            _ctx: &ExecutionContext,
        ) -> Result<ToolResult, ToolError> {
            Ok(ToolResult::success(serde_json::json!({"mock": true})))
        }
    }

    #[test]
    fn test_registry_new() {
        let registry = ToolRegistry::new();
        assert!(registry.list().is_empty());
    }

    #[test]
    fn test_registry_register() {
        let mut registry = ToolRegistry::new();
        registry.register(MockTool);

        assert!(registry.has("mock"));
        assert!(!registry.has("unknown"));
        assert_eq!(registry.list(), vec!["mock"]);
    }

    #[tokio::test]
    async fn test_registry_execute() {
        let mut registry = ToolRegistry::new();
        registry.register(MockTool);

        let config = ToolConfig {
            kind: "mock".to_string(),
            config: serde_json::json!({}),
            timeout: None,
            retry: None,
            auth: None,
        };

        let ctx = ExecutionContext::default();
        let result = registry.execute("mock", &config, &ctx).await.unwrap();
        assert!(result.is_success());
    }

    #[tokio::test]
    async fn test_registry_execute_not_found() {
        let registry = ToolRegistry::new();
        let config = ToolConfig {
            kind: "unknown".to_string(),
            config: serde_json::json!({}),
            timeout: None,
            retry: None,
            auth: None,
        };

        let ctx = ExecutionContext::default();
        let result = registry.execute("unknown", &config, &ctx).await;
        assert!(matches!(result, Err(ToolError::NotFound(_))));
    }

    #[test]
    fn test_retry_config_default() {
        let config = RetryConfig::default();
        assert_eq!(config.max_retries, 3);
        assert_eq!(config.initial_delay_ms, 500);
        assert_eq!(config.max_delay_ms, 10000);
        assert_eq!(config.backoff_multiplier, 2.0);
    }

    #[test]
    fn test_auth_config_serialization() {
        let config = AuthConfig {
            auth_type: AuthType::Bearer,
            credential: Some("my-cred".to_string()),
            token: None,
            username: None,
            password: None,
            header: None,
            scopes: None,
        };

        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("\"type\":\"bearer\""));
        assert!(json.contains("\"credential\":\"my-cred\""));
    }
}
