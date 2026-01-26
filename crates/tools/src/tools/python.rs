//! Python script execution tool.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;
use tempfile::NamedTempFile;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tokio::time::timeout;

use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::registry::{Tool, ToolConfig};
use crate::result::{ToolResult, ToolStatus};
use crate::template::TemplateEngine;

/// Python tool configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PythonConfig {
    /// Python code to execute.
    pub code: String,

    /// Arguments passed to the script (available as 'args' dict).
    #[serde(default)]
    pub args: HashMap<String, serde_json::Value>,

    /// Python interpreter to use (default: "python3").
    #[serde(default = "default_python")]
    pub python: String,

    /// Additional environment variables.
    #[serde(default)]
    pub env: HashMap<String, String>,

    /// Timeout in seconds.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timeout_seconds: Option<u64>,

    /// Working directory.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cwd: Option<String>,
}

fn default_python() -> String {
    std::env::var("PYTHON_PATH").unwrap_or_else(|_| "python3".to_string())
}

/// Python script execution tool.
///
/// Executes Python code in a subprocess with JSON protocol:
/// - Script receives context on stdin as JSON
/// - Script should print result as JSON to stdout
/// - Exit code determines success/failure
pub struct PythonTool {
    template_engine: TemplateEngine,
}

impl PythonTool {
    /// Create a new Python tool.
    pub fn new() -> Self {
        Self {
            template_engine: TemplateEngine::new(),
        }
    }

    /// Execute Python code.
    #[allow(clippy::too_many_arguments)]
    pub async fn execute_code(
        &self,
        code: &str,
        args: &HashMap<String, serde_json::Value>,
        env: &HashMap<String, String>,
        python: &str,
        cwd: Option<&str>,
        timeout_duration: Option<Duration>,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let start = std::time::Instant::now();

        // Create wrapper script that handles JSON I/O
        let wrapper_code = format!(
            r#"
import sys
import json

# Read context from stdin
context = json.loads(sys.stdin.read())
args = context.get('args', {{}})
variables = context.get('variables', {{}})
execution_id = context.get('execution_id')
step = context.get('step')

# Make args available as globals for convenience
globals().update(args)

# User code
{}

# If the last expression is a result, capture it
# (This won't work for all cases, but covers simple scripts)
"#,
            code
        );

        // Write script to temp file
        let temp_file = NamedTempFile::new()
            .map_err(|e| ToolError::Process(format!("Failed to create temp file: {}", e)))?;

        tokio::fs::write(temp_file.path(), wrapper_code.as_bytes())
            .await
            .map_err(|e| ToolError::Process(format!("Failed to write script: {}", e)))?;

        // Build command
        let mut cmd = Command::new(python);
        cmd.arg(temp_file.path());

        if let Some(dir) = cwd {
            cmd.current_dir(dir);
        }

        // Set environment variables
        for (k, v) in env {
            cmd.env(k, v);
        }

        // Setup stdin/stdout/stderr
        cmd.stdin(std::process::Stdio::piped());
        cmd.stdout(std::process::Stdio::piped());
        cmd.stderr(std::process::Stdio::piped());

        // Spawn process
        let mut child = cmd.spawn().map_err(|e| {
            ToolError::Process(format!("Failed to spawn Python process: {}", e))
        })?;

        // Write context to stdin
        let context_json = serde_json::json!({
            "args": args,
            "variables": ctx.variables,
            "execution_id": ctx.execution_id,
            "step": ctx.step,
            "server_url": ctx.server_url,
        });

        let stdin = child.stdin.take();
        if let Some(mut stdin) = stdin {
            let _ = stdin
                .write_all(context_json.to_string().as_bytes())
                .await;
            let _ = stdin.shutdown().await;
        }

        // Wait for completion with timeout
        let output = if let Some(duration) = timeout_duration {
            // Take the child id before we potentially consume the process
            let child_id = child.id();

            match timeout(duration, child.wait_with_output()).await {
                Ok(result) => result.map_err(|e| {
                    ToolError::Process(format!("Failed to wait for process: {}", e))
                })?,
                Err(_) => {
                    // Timeout occurred - try to kill the process by ID
                    if let Some(pid) = child_id {
                        #[cfg(unix)]
                        {
                            
                            let _ = std::process::Command::new("kill")
                                .args(["-9", &pid.to_string()])
                                .spawn();
                        }
                        #[cfg(windows)]
                        {
                            let _ = std::process::Command::new("taskkill")
                                .args(["/F", "/PID", &pid.to_string()])
                                .spawn();
                        }
                    }
                    let duration_ms = start.elapsed().as_millis() as u64;
                    return Ok(
                        ToolResult::timeout(duration.as_secs()).with_duration(duration_ms)
                    );
                }
            }
        } else {
            child.wait_with_output().await.map_err(|e| {
                ToolError::Process(format!("Failed to wait for process: {}", e))
            })?
        };

        let exit_code = output.status.code().unwrap_or(-1);
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();

        let duration_ms = start.elapsed().as_millis() as u64;

        // Try to parse stdout as JSON for data
        let data = if !stdout.trim().is_empty() {
            serde_json::from_str(&stdout).ok()
        } else {
            None
        };

        let status = if exit_code == 0 {
            ToolStatus::Success
        } else {
            ToolStatus::Error
        };

        Ok(ToolResult {
            status,
            data: data.or_else(|| Some(serde_json::json!({
                "stdout": stdout,
                "stderr": stderr,
            }))),
            error: if exit_code != 0 {
                Some(format!("Python script exited with code {}", exit_code))
            } else {
                None
            },
            stdout: Some(stdout),
            stderr: Some(stderr),
            exit_code: Some(exit_code),
            duration_ms: Some(duration_ms),
        })
    }

    /// Parse Python config from tool config.
    fn parse_config(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<PythonConfig, ToolError> {
        let template_ctx = ctx.to_template_context();
        let rendered_config = self.template_engine.render_value(&config.config, &template_ctx)?;

        serde_json::from_value(rendered_config)
            .map_err(|e| ToolError::Configuration(format!("Invalid python config: {}", e)))
    }
}

impl Default for PythonTool {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for PythonTool {
    fn name(&self) -> &'static str {
        "python"
    }

    async fn execute(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let python_config = self.parse_config(config, ctx)?;

        let timeout_duration = python_config
            .timeout_seconds
            .or(config.timeout)
            .map(Duration::from_secs);

        tracing::debug!(
            code_len = python_config.code.len(),
            python = %python_config.python,
            timeout = ?timeout_duration,
            "Executing Python script"
        );

        self.execute_code(
            &python_config.code,
            &python_config.args,
            &python_config.env,
            &python_config.python,
            python_config.cwd.as_deref(),
            timeout_duration,
            ctx,
        )
        .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_python_config_deserialization() {
        let json = serde_json::json!({
            "code": "print('hello')",
            "args": {"name": "world"},
            "python": "python3"
        });

        let config: PythonConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.code, "print('hello')");
        assert!(config.args.contains_key("name"));
    }

    #[test]
    fn test_python_config_defaults() {
        let json = serde_json::json!({
            "code": "print(1)"
        });

        let config: PythonConfig = serde_json::from_value(json).unwrap();
        assert!(config.args.is_empty());
        assert!(config.env.is_empty());
        assert_eq!(config.python, default_python());
    }

    #[tokio::test]
    async fn test_python_simple_script() {
        let tool = PythonTool::new();
        let args = HashMap::new();
        let env = HashMap::new();
        let ctx = ExecutionContext::default();

        let result = tool
            .execute_code(
                "print('hello from python')",
                &args,
                &env,
                "python3",
                None,
                None,
                &ctx,
            )
            .await
            .unwrap();

        assert!(result.is_success());
        assert!(result.stdout.as_ref().unwrap().contains("hello from python"));
    }

    #[tokio::test]
    async fn test_python_json_output() {
        let tool = PythonTool::new();
        let args = HashMap::new();
        let env = HashMap::new();
        let ctx = ExecutionContext::default();

        let result = tool
            .execute_code(
                r#"import json; print(json.dumps({"result": 42}))"#,
                &args,
                &env,
                "python3",
                None,
                None,
                &ctx,
            )
            .await
            .unwrap();

        assert!(result.is_success());
        if let Some(data) = result.data {
            // Either parsed JSON or raw output
            assert!(data.to_string().contains("42"));
        }
    }

    #[tokio::test]
    async fn test_python_with_args() {
        let tool = PythonTool::new();
        let mut args = HashMap::new();
        args.insert("x".to_string(), serde_json::json!(10));
        let env = HashMap::new();
        let ctx = ExecutionContext::default();

        let result = tool
            .execute_code(
                "print(args.get('x', 0) * 2)",
                &args,
                &env,
                "python3",
                None,
                None,
                &ctx,
            )
            .await
            .unwrap();

        assert!(result.is_success());
        assert!(result.stdout.as_ref().unwrap().contains("20"));
    }

    #[tokio::test]
    async fn test_python_error() {
        let tool = PythonTool::new();
        let args = HashMap::new();
        let env = HashMap::new();
        let ctx = ExecutionContext::default();

        let result = tool
            .execute_code(
                "raise ValueError('test error')",
                &args,
                &env,
                "python3",
                None,
                None,
                &ctx,
            )
            .await
            .unwrap();

        assert!(!result.is_success());
        assert!(result.exit_code.unwrap() != 0);
    }

    #[tokio::test]
    async fn test_python_timeout() {
        let tool = PythonTool::new();
        let args = HashMap::new();
        let env = HashMap::new();
        let ctx = ExecutionContext::default();

        let result = tool
            .execute_code(
                "import time; time.sleep(10)",
                &args,
                &env,
                "python3",
                None,
                Some(Duration::from_millis(100)),
                &ctx,
            )
            .await
            .unwrap();

        assert_eq!(result.status, ToolStatus::Timeout);
    }

    #[tokio::test]
    async fn test_python_tool_interface() {
        let tool = PythonTool::new();
        assert_eq!(tool.name(), "python");

        let config = ToolConfig {
            kind: "python".to_string(),
            config: serde_json::json!({
                "code": "print('test')"
            }),
            timeout: None,
            retry: None,
            auth: None,
        };

        let ctx = ExecutionContext::default();
        let result = tool.execute(&config, &ctx).await.unwrap();
        assert!(result.is_success());
    }
}
