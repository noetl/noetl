//! HTTP request tool.

use async_trait::async_trait;
use reqwest::Method;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;

use crate::auth::{AuthCredentials, AuthResolver};
use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::registry::{Tool, ToolConfig};
use crate::result::ToolResult;
use crate::template::TemplateEngine;

/// HTTP method.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "UPPERCASE")]
#[allow(clippy::upper_case_acronyms)] // HTTP methods are conventionally uppercase
pub enum HttpMethod {
    #[default]
    GET,
    POST,
    PUT,
    PATCH,
    DELETE,
    HEAD,
    OPTIONS,
}

impl From<HttpMethod> for Method {
    fn from(method: HttpMethod) -> Self {
        match method {
            HttpMethod::GET => Method::GET,
            HttpMethod::POST => Method::POST,
            HttpMethod::PUT => Method::PUT,
            HttpMethod::PATCH => Method::PATCH,
            HttpMethod::DELETE => Method::DELETE,
            HttpMethod::HEAD => Method::HEAD,
            HttpMethod::OPTIONS => Method::OPTIONS,
        }
    }
}

/// HTTP tool configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HttpConfig {
    /// URL to request.
    pub url: String,

    /// HTTP method (default: GET).
    #[serde(default)]
    pub method: HttpMethod,

    /// Request headers.
    #[serde(default)]
    pub headers: HashMap<String, String>,

    /// Request body (for POST/PUT/PATCH).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub body: Option<serde_json::Value>,

    /// JSON body (alternative to body, sets Content-Type).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub json: Option<serde_json::Value>,

    /// Form data (sets Content-Type to application/x-www-form-urlencoded).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub form: Option<HashMap<String, String>>,

    /// Query parameters.
    #[serde(default)]
    pub params: HashMap<String, String>,

    /// Request timeout in seconds.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timeout_seconds: Option<u64>,

    /// Whether to follow redirects (default: true).
    #[serde(default = "default_follow_redirects")]
    pub follow_redirects: bool,

    /// Expected response type.
    #[serde(default)]
    pub response_type: ResponseType,
}

fn default_follow_redirects() -> bool {
    true
}

/// Expected response type.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum ResponseType {
    /// Parse response as JSON.
    #[default]
    Json,
    /// Return response as text.
    Text,
    /// Return response as base64-encoded binary.
    Binary,
}

/// HTTP request tool.
pub struct HttpTool {
    client: reqwest::Client,
    auth_resolver: AuthResolver,
    template_engine: TemplateEngine,
}

impl HttpTool {
    /// Create a new HTTP tool.
    pub fn new() -> Self {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .unwrap_or_default();

        Self {
            client,
            auth_resolver: AuthResolver::new(),
            template_engine: TemplateEngine::new(),
        }
    }

    /// Create an HTTP tool with a custom client.
    pub fn with_client(client: reqwest::Client) -> Self {
        Self {
            client,
            auth_resolver: AuthResolver::new(),
            template_engine: TemplateEngine::new(),
        }
    }

    /// Execute an HTTP request.
    pub async fn request(
        &self,
        config: &HttpConfig,
        auth: Option<AuthCredentials>,
    ) -> Result<ToolResult, ToolError> {
        let start = std::time::Instant::now();

        // Build the request
        let method: Method = config.method.clone().into();
        let mut request = self.client.request(method, &config.url);

        // Set query parameters
        if !config.params.is_empty() {
            request = request.query(&config.params);
        }

        // Set headers
        for (key, value) in &config.headers {
            request = request.header(key.as_str(), value.as_str());
        }

        // Set body
        if let Some(ref json) = config.json {
            request = request.json(json);
        } else if let Some(ref form) = config.form {
            request = request.form(form);
        } else if let Some(ref body) = config.body {
            match body {
                serde_json::Value::String(s) => {
                    request = request.body(s.clone());
                }
                _ => {
                    request = request.json(body);
                }
            }
        }

        // Apply authentication
        if let Some(creds) = auth {
            request = creds.apply_to_request(request);
        }

        // Set timeout
        if let Some(timeout) = config.timeout_seconds {
            request = request.timeout(Duration::from_secs(timeout));
        }

        // Execute request
        let response = request.send().await?;

        let status_code = response.status().as_u16();
        let headers: HashMap<String, String> = response
            .headers()
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_str().unwrap_or("").to_string()))
            .collect();

        // Parse response based on type
        let (data, text_body) = match config.response_type {
            ResponseType::Json => {
                let text = response.text().await.unwrap_or_default();
                let json: serde_json::Value =
                    serde_json::from_str(&text).unwrap_or(serde_json::json!(text));
                (json, Some(text))
            }
            ResponseType::Text => {
                let text = response.text().await.unwrap_or_default();
                (serde_json::json!(text), Some(text))
            }
            ResponseType::Binary => {
                let bytes = response.bytes().await.unwrap_or_default();
                let encoded = base64::Engine::encode(
                    &base64::engine::general_purpose::STANDARD,
                    &bytes,
                );
                (
                    serde_json::json!({
                        "base64": encoded,
                        "size": bytes.len()
                    }),
                    None,
                )
            }
        };

        let duration_ms = start.elapsed().as_millis() as u64;

        // Determine success based on status code
        let is_success = (200..300).contains(&status_code);

        let result = ToolResult {
            status: if is_success {
                crate::result::ToolStatus::Success
            } else {
                crate::result::ToolStatus::Error
            },
            data: Some(serde_json::json!({
                "status_code": status_code,
                "headers": headers,
                "body": data,
            })),
            error: if !is_success {
                Some(format!("HTTP {} response", status_code))
            } else {
                None
            },
            stdout: text_body,
            stderr: None,
            exit_code: Some(if is_success { 0 } else { 1 }),
            duration_ms: Some(duration_ms),
        };

        Ok(result)
    }

    /// Parse HTTP config from tool config.
    fn parse_config(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<HttpConfig, ToolError> {
        let template_ctx = ctx.to_template_context();
        let rendered_config = self.template_engine.render_value(&config.config, &template_ctx)?;

        serde_json::from_value(rendered_config)
            .map_err(|e| ToolError::Configuration(format!("Invalid http config: {}", e)))
    }
}

impl Default for HttpTool {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for HttpTool {
    fn name(&self) -> &'static str {
        "http"
    }

    async fn execute(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let http_config = self.parse_config(config, ctx)?;

        // Resolve authentication if configured
        let auth = if let Some(ref auth_config) = config.auth {
            Some(self.auth_resolver.resolve(auth_config, ctx).await?)
        } else {
            None
        };

        tracing::debug!(
            url = %http_config.url,
            method = ?http_config.method,
            has_auth = auth.is_some(),
            "Executing HTTP request"
        );

        self.request(&http_config, auth).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_http_method_conversion() {
        assert_eq!(Method::from(HttpMethod::GET), Method::GET);
        assert_eq!(Method::from(HttpMethod::POST), Method::POST);
        assert_eq!(Method::from(HttpMethod::PUT), Method::PUT);
        assert_eq!(Method::from(HttpMethod::DELETE), Method::DELETE);
    }

    #[test]
    fn test_http_config_deserialization() {
        let json = serde_json::json!({
            "url": "https://api.example.com/data",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "json": {"key": "value"}
        });

        let config: HttpConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.url, "https://api.example.com/data");
        assert!(matches!(config.method, HttpMethod::POST));
        assert!(config.json.is_some());
    }

    #[test]
    fn test_http_config_defaults() {
        let json = serde_json::json!({
            "url": "https://example.com"
        });

        let config: HttpConfig = serde_json::from_value(json).unwrap();
        assert!(matches!(config.method, HttpMethod::GET));
        assert!(config.follow_redirects);
        assert!(matches!(config.response_type, ResponseType::Json));
    }

    #[tokio::test]
    async fn test_http_tool_interface() {
        let tool = HttpTool::new();
        assert_eq!(tool.name(), "http");
    }

    #[test]
    fn test_response_type_serialization() {
        let rt = ResponseType::Json;
        let json = serde_json::to_string(&rt).unwrap();
        assert_eq!(json, "\"json\"");

        let rt = ResponseType::Text;
        let json = serde_json::to_string(&rt).unwrap();
        assert_eq!(json, "\"text\"");
    }
}
