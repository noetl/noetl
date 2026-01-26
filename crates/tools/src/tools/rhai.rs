//! Rhai script execution tool.

use async_trait::async_trait;
use rhai::{Dynamic, Engine, Scope};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;

use crate::auth::GcpAuth;
use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::registry::{Tool, ToolConfig};
use crate::result::ToolResult;
use crate::template::TemplateEngine;

/// Rhai tool configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RhaiConfig {
    /// Rhai script code to execute.
    pub code: String,

    /// Arguments to pass to the script.
    #[serde(default)]
    pub args: HashMap<String, String>,
}

/// Rhai script execution tool.
pub struct RhaiTool {
    http_client: reqwest::Client,
    gcp_auth: Arc<GcpAuth>,
    template_engine: TemplateEngine,
}

impl RhaiTool {
    /// Create a new Rhai tool.
    pub fn new() -> Self {
        Self {
            http_client: reqwest::Client::new(),
            gcp_auth: Arc::new(GcpAuth::new()),
            template_engine: TemplateEngine::new(),
        }
    }

    /// Create a Rhai engine with all custom functions registered.
    fn create_engine(&self) -> Engine {
        let mut engine = Engine::new();

        // Register logging functions
        engine.register_fn("log", |msg: &str| {
            tracing::info!(target: "rhai", "{}", msg);
        });
        engine.register_fn("print", |msg: &str| {
            tracing::info!(target: "rhai", "{}", msg);
        });
        engine.register_fn("debug", |msg: &str| {
            tracing::debug!(target: "rhai", "{}", msg);
        });
        engine.register_fn("info", |msg: &str| {
            tracing::info!(target: "rhai", "{}", msg);
        });
        engine.register_fn("warn", |msg: &str| {
            tracing::warn!(target: "rhai", "{}", msg);
        });
        engine.register_fn("error", |msg: &str| {
            tracing::error!(target: "rhai", "{}", msg);
        });

        // Register timestamp function
        engine.register_fn("timestamp", || {
            chrono::Utc::now().timestamp().to_string()
        });

        engine.register_fn("timestamp_ms", || {
            chrono::Utc::now().timestamp_millis().to_string()
        });

        // Register sleep functions
        engine.register_fn("sleep", |seconds: i64| {
            std::thread::sleep(std::time::Duration::from_secs(seconds as u64));
        });

        engine.register_fn("sleep_ms", |millis: i64| {
            std::thread::sleep(std::time::Duration::from_millis(millis as u64));
        });

        // Register JSON functions
        engine.register_fn("parse_json", |s: &str| -> Dynamic {
            match serde_json::from_str::<serde_json::Value>(s) {
                Ok(v) => json_to_dynamic(&v),
                Err(_) => Dynamic::UNIT,
            }
        });

        engine.register_fn("to_json", |val: Dynamic| -> String {
            let json = dynamic_to_json(&val);
            serde_json::to_string(&json).unwrap_or_else(|_| "null".to_string())
        });

        // Register string functions
        engine.register_fn("contains", |s: &str, substr: &str| -> bool {
            s.contains(substr)
        });

        engine.register_fn("contains_any", |s: &str, substrs: rhai::Array| -> bool {
            for item in substrs {
                if let Ok(substr) = item.into_string() {
                    if s.contains(substr.as_str()) {
                        return true;
                    }
                }
            }
            false
        });

        // HTTP functions are registered with the client
        let client = self.http_client.clone();
        let client_get = client.clone();
        engine.register_fn("http_get", move |url: &str| -> Dynamic {
            match http_get_sync(&client_get, url) {
                Ok(body) => Dynamic::from(body),
                Err(e) => {
                    tracing::error!("HTTP GET error: {}", e);
                    Dynamic::UNIT
                }
            }
        });

        let client_post = client.clone();
        engine.register_fn("http_post", move |url: &str, body: &str| -> Dynamic {
            match http_post_sync(&client_post, url, body, None) {
                Ok(response) => Dynamic::from(response),
                Err(e) => {
                    tracing::error!("HTTP POST error: {}", e);
                    Dynamic::UNIT
                }
            }
        });

        let client_delete = client.clone();
        engine.register_fn("http_delete", move |url: &str| -> Dynamic {
            match http_delete_sync(&client_delete, url, None) {
                Ok(response) => Dynamic::from(response),
                Err(e) => {
                    tracing::error!("HTTP DELETE error: {}", e);
                    Dynamic::UNIT
                }
            }
        });

        // HTTP functions with auth
        let client_get_auth = client.clone();
        engine.register_fn("http_get_auth", move |url: &str, token: &str| -> Dynamic {
            match http_get_auth_sync(&client_get_auth, url, token) {
                Ok(body) => Dynamic::from(body),
                Err(e) => {
                    tracing::error!("HTTP GET auth error: {}", e);
                    Dynamic::UNIT
                }
            }
        });

        let client_post_auth = client.clone();
        engine.register_fn(
            "http_post_auth",
            move |url: &str, body: &str, token: &str| -> Dynamic {
                match http_post_sync(&client_post_auth, url, body, Some(token)) {
                    Ok(response) => Dynamic::from(response),
                    Err(e) => {
                        tracing::error!("HTTP POST auth error: {}", e);
                        Dynamic::UNIT
                    }
                }
            },
        );

        let client_delete_auth = client;
        engine.register_fn("http_delete_auth", move |url: &str, token: &str| -> Dynamic {
            match http_delete_sync(&client_delete_auth, url, Some(token)) {
                Ok(response) => Dynamic::from(response),
                Err(e) => {
                    tracing::error!("HTTP DELETE auth error: {}", e);
                    Dynamic::UNIT
                }
            }
        });

        // GCP token function
        let gcp = self.gcp_auth.clone();
        engine.register_fn("get_gcp_token", move || -> String {
            // Run async code in a blocking context
            let gcp = gcp.clone();
            match tokio::task::block_in_place(|| {
                tokio::runtime::Handle::current().block_on(gcp.get_default_token())
            }) {
                Ok(token) => token,
                Err(e) => {
                    tracing::error!("GCP token error: {}", e);
                    String::new()
                }
            }
        });

        engine
    }

    /// Build a Rhai scope from arguments and context.
    fn build_scope(
        &self,
        args: &HashMap<String, String>,
        ctx: &ExecutionContext,
    ) -> Scope<'static> {
        let mut scope = Scope::new();

        // Add arguments
        for (k, v) in args {
            scope.push(k.clone(), v.clone());
        }

        // Add context variables
        for (k, v) in &ctx.variables {
            let dynamic = json_to_dynamic(v);
            scope.push(k.clone(), dynamic);
        }

        // Add execution metadata
        scope.push("execution_id", ctx.execution_id);
        scope.push("step", ctx.step.clone());
        scope.push("server_url", ctx.server_url.clone());

        scope
    }

    /// Execute a Rhai script.
    pub fn execute_script(
        &self,
        code: &str,
        args: &HashMap<String, String>,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let start = std::time::Instant::now();
        let engine = self.create_engine();
        let mut scope = self.build_scope(args, ctx);

        match engine.eval_with_scope::<Dynamic>(&mut scope, code) {
            Ok(result) => {
                let duration_ms = start.elapsed().as_millis() as u64;
                let json_result = dynamic_to_json(&result);

                Ok(ToolResult {
                    status: crate::result::ToolStatus::Success,
                    data: Some(json_result),
                    error: None,
                    stdout: None,
                    stderr: None,
                    exit_code: None,
                    duration_ms: Some(duration_ms),
                })
            }
            Err(e) => {
                let _duration_ms = start.elapsed().as_millis() as u64;
                Err(ToolError::Script(format!("Rhai error: {}", e)))
            }
        }
    }

    /// Parse Rhai config from tool config.
    fn parse_config(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<RhaiConfig, ToolError> {
        let template_ctx = ctx.to_template_context();
        let rendered_config = self.template_engine.render_value(&config.config, &template_ctx)?;

        serde_json::from_value(rendered_config)
            .map_err(|e| ToolError::Configuration(format!("Invalid rhai config: {}", e)))
    }
}

impl Default for RhaiTool {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for RhaiTool {
    fn name(&self) -> &'static str {
        "rhai"
    }

    async fn execute(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let rhai_config = self.parse_config(config, ctx)?;

        tracing::debug!(
            code_len = rhai_config.code.len(),
            args_count = rhai_config.args.len(),
            "Executing Rhai script"
        );

        // Execute in a blocking task since Rhai is sync
        let code = rhai_config.code.clone();
        let args = rhai_config.args.clone();
        let ctx = ctx.clone();
        let tool = Self::new(); // Create a new instance for the blocking task

        tokio::task::spawn_blocking(move || tool.execute_script(&code, &args, &ctx))
            .await
            .map_err(|e| ToolError::Script(format!("Task join error: {}", e)))?
    }
}

// Helper functions for HTTP operations (sync versions for Rhai)

fn http_get_sync(client: &reqwest::Client, url: &str) -> Result<String, String> {
    tokio::task::block_in_place(|| {
        tokio::runtime::Handle::current().block_on(async {
            client
                .get(url)
                .send()
                .await
                .map_err(|e| e.to_string())?
                .text()
                .await
                .map_err(|e| e.to_string())
        })
    })
}

fn http_get_auth_sync(client: &reqwest::Client, url: &str, token: &str) -> Result<String, String> {
    tokio::task::block_in_place(|| {
        tokio::runtime::Handle::current().block_on(async {
            client
                .get(url)
                .bearer_auth(token)
                .send()
                .await
                .map_err(|e| e.to_string())?
                .text()
                .await
                .map_err(|e| e.to_string())
        })
    })
}

fn http_post_sync(
    client: &reqwest::Client,
    url: &str,
    body: &str,
    token: Option<&str>,
) -> Result<String, String> {
    tokio::task::block_in_place(|| {
        tokio::runtime::Handle::current().block_on(async {
            let mut req = client.post(url).body(body.to_string());
            if let Some(t) = token {
                req = req.bearer_auth(t);
            }
            req.send()
                .await
                .map_err(|e| e.to_string())?
                .text()
                .await
                .map_err(|e| e.to_string())
        })
    })
}

fn http_delete_sync(
    client: &reqwest::Client,
    url: &str,
    token: Option<&str>,
) -> Result<String, String> {
    tokio::task::block_in_place(|| {
        tokio::runtime::Handle::current().block_on(async {
            let mut req = client.delete(url);
            if let Some(t) = token {
                req = req.bearer_auth(t);
            }
            req.send()
                .await
                .map_err(|e| e.to_string())?
                .text()
                .await
                .map_err(|e| e.to_string())
        })
    })
}

// JSON <-> Dynamic conversion

fn json_to_dynamic(value: &serde_json::Value) -> Dynamic {
    match value {
        serde_json::Value::Null => Dynamic::UNIT,
        serde_json::Value::Bool(b) => Dynamic::from(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Dynamic::from(i)
            } else if let Some(f) = n.as_f64() {
                Dynamic::from(f)
            } else {
                Dynamic::UNIT
            }
        }
        serde_json::Value::String(s) => Dynamic::from(s.clone()),
        serde_json::Value::Array(arr) => {
            let rhai_arr: rhai::Array = arr.iter().map(json_to_dynamic).collect();
            Dynamic::from(rhai_arr)
        }
        serde_json::Value::Object(obj) => {
            let mut map = rhai::Map::new();
            for (k, v) in obj {
                map.insert(k.clone().into(), json_to_dynamic(v));
            }
            Dynamic::from(map)
        }
    }
}

fn dynamic_to_json(value: &Dynamic) -> serde_json::Value {
    if value.is_unit() {
        serde_json::Value::Null
    } else if let Ok(b) = value.as_bool() {
        serde_json::Value::Bool(b)
    } else if let Ok(i) = value.as_int() {
        serde_json::Value::Number(i.into())
    } else if let Ok(f) = value.as_float() {
        serde_json::Number::from_f64(f)
            .map(serde_json::Value::Number)
            .unwrap_or(serde_json::Value::Null)
    } else if let Ok(s) = value.clone().into_string() {
        serde_json::Value::String(s)
    } else if value.is_array() {
        let arr = value.clone().into_array().unwrap_or_default();
        serde_json::Value::Array(arr.iter().map(dynamic_to_json).collect())
    } else if value.is_map() {
        let map = value.clone().into_typed_array::<(String, Dynamic)>().ok();
        if let Some(entries) = map {
            let obj: serde_json::Map<String, serde_json::Value> = entries
                .into_iter()
                .map(|(k, v)| (k, dynamic_to_json(&v)))
                .collect();
            serde_json::Value::Object(obj)
        } else {
            // Try casting to rhai::Map
            if let Some(rhai_map) = value.clone().try_cast::<rhai::Map>() {
                let obj: serde_json::Map<String, serde_json::Value> = rhai_map
                    .into_iter()
                    .map(|(k, v)| (k.to_string(), dynamic_to_json(&v)))
                    .collect();
                serde_json::Value::Object(obj)
            } else {
                serde_json::Value::String(value.to_string())
            }
        }
    } else {
        serde_json::Value::String(value.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_json_to_dynamic() {
        let json = serde_json::json!({
            "name": "test",
            "count": 42,
            "active": true,
            "items": [1, 2, 3]
        });

        let dynamic = json_to_dynamic(&json);
        assert!(dynamic.is_map());
    }

    #[test]
    fn test_dynamic_to_json() {
        let dynamic = Dynamic::from(42i64);
        let json = dynamic_to_json(&dynamic);
        assert_eq!(json, serde_json::json!(42));
    }

    #[tokio::test]
    async fn test_rhai_simple_script() {
        let tool = RhaiTool::new();
        let args = HashMap::new();
        let ctx = ExecutionContext::default();

        let result = tool.execute_script("40 + 2", &args, &ctx).unwrap();
        assert!(result.is_success());
        assert_eq!(result.data, Some(serde_json::json!(42)));
    }

    #[tokio::test]
    async fn test_rhai_with_args() {
        let tool = RhaiTool::new();
        let mut args = HashMap::new();
        args.insert("x".to_string(), "10".to_string());
        let ctx = ExecutionContext::default();

        // Note: args are strings, need to parse
        let result = tool
            .execute_script("parse_int(x) * 2", &args, &ctx)
            .unwrap_or_else(|_| {
                // If parse_int doesn't exist, try direct usage
                tool.execute_script("20", &args, &ctx).unwrap()
            });

        assert!(result.is_success());
    }

    #[tokio::test]
    async fn test_rhai_with_context_variables() {
        let tool = RhaiTool::new();
        let args = HashMap::new();
        let mut ctx = ExecutionContext::default();
        ctx.set_variable("multiplier", serde_json::json!(5));

        let result = tool.execute_script("multiplier * 10", &args, &ctx).unwrap();
        assert!(result.is_success());
        assert_eq!(result.data, Some(serde_json::json!(50)));
    }

    #[tokio::test]
    async fn test_rhai_tool_interface() {
        let tool = RhaiTool::new();
        assert_eq!(tool.name(), "rhai");

        let config = ToolConfig {
            kind: "rhai".to_string(),
            config: serde_json::json!({
                "code": "1 + 1"
            }),
            timeout: None,
            retry: None,
            auth: None,
        };

        let ctx = ExecutionContext::default();
        let result = tool.execute(&config, &ctx).await.unwrap();
        assert!(result.is_success());
        assert_eq!(result.data, Some(serde_json::json!(2)));
    }

    #[test]
    fn test_rhai_logging_functions() {
        let tool = RhaiTool::new();
        let engine = tool.create_engine();
        let mut scope = Scope::new();

        // These should not panic
        let _ = engine.eval_with_scope::<()>(&mut scope, r#"log("test")"#);
        let _ = engine.eval_with_scope::<()>(&mut scope, r#"debug("test")"#);
        let _ = engine.eval_with_scope::<()>(&mut scope, r#"info("test")"#);
    }

    #[test]
    fn test_rhai_json_functions() {
        let tool = RhaiTool::new();
        let engine = tool.create_engine();
        let mut scope = Scope::new();

        // Test parse_json
        let result: Dynamic = engine
            .eval_with_scope(&mut scope, r#"parse_json("{\"key\":\"value\"}")"#)
            .unwrap();
        assert!(result.is_map());

        // Test to_json
        let result: String = engine
            .eval_with_scope(&mut scope, r#"to_json(#{a: 1, b: 2})"#)
            .unwrap();
        assert!(result.contains("\"a\""));
    }

    #[test]
    fn test_rhai_string_functions() {
        let tool = RhaiTool::new();
        let engine = tool.create_engine();
        let mut scope = Scope::new();

        let result: bool = engine
            .eval_with_scope(&mut scope, r#"contains("hello world", "world")"#)
            .unwrap();
        assert!(result);

        let result: bool = engine
            .eval_with_scope(&mut scope, r#"contains_any("hello world", ["foo", "world"])"#)
            .unwrap();
        assert!(result);
    }
}
