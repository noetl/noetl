//! Shell command execution tool.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;
use tokio::time::timeout;

use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::registry::{Tool, ToolConfig};
use crate::result::ToolResult;
use crate::template::TemplateEngine;

/// Shell tool configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShellConfig {
    /// Command to execute.
    pub command: String,

    /// Shell to use (default: "bash").
    #[serde(default = "default_shell")]
    pub shell: String,

    /// Working directory.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cwd: Option<String>,

    /// Environment variables.
    #[serde(default)]
    pub env: HashMap<String, String>,

    /// Timeout in seconds.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timeout_seconds: Option<u64>,

    /// Whether to capture output (default: true).
    #[serde(default = "default_capture")]
    pub capture: bool,
}

fn default_shell() -> String {
    "bash".to_string()
}

fn default_capture() -> bool {
    true
}

/// Shell command execution tool.
pub struct ShellTool {
    template_engine: TemplateEngine,
}

impl ShellTool {
    /// Create a new shell tool.
    pub fn new() -> Self {
        Self {
            template_engine: TemplateEngine::new(),
        }
    }

    /// Execute a shell command directly.
    pub async fn execute_command(
        &self,
        command: &str,
        shell: &str,
        cwd: Option<&str>,
        env: &HashMap<String, String>,
        timeout_duration: Option<Duration>,
        capture: bool,
    ) -> Result<ToolResult, ToolError> {
        let start = std::time::Instant::now();

        // Build the command
        let mut cmd = Command::new(shell);
        cmd.arg("-c").arg(command);

        // Set working directory
        if let Some(dir) = cwd {
            cmd.current_dir(dir);
        }

        // Set environment variables
        for (k, v) in env {
            cmd.env(k, v);
        }

        // Configure output capture
        if capture {
            cmd.stdout(std::process::Stdio::piped());
            cmd.stderr(std::process::Stdio::piped());
        }

        // Spawn the process
        let mut child = cmd.spawn().map_err(|e| {
            ToolError::Process(format!("Failed to spawn process: {}", e))
        })?;

        // Handle output capture
        let (stdout_result, stderr_result) = if capture {
            let stdout = child.stdout.take();
            let stderr = child.stderr.take();

            // Read stdout and stderr concurrently
            let stdout_handle = tokio::spawn(async move {
                let mut output = String::new();
                if let Some(stdout) = stdout {
                    let mut reader = BufReader::new(stdout).lines();
                    while let Ok(Some(line)) = reader.next_line().await {
                        output.push_str(&line);
                        output.push('\n');
                    }
                }
                output
            });

            let stderr_handle = tokio::spawn(async move {
                let mut output = String::new();
                if let Some(stderr) = stderr {
                    let mut reader = BufReader::new(stderr).lines();
                    while let Ok(Some(line)) = reader.next_line().await {
                        output.push_str(&line);
                        output.push('\n');
                    }
                }
                output
            });

            (stdout_handle, stderr_handle)
        } else {
            (
                tokio::spawn(async { String::new() }),
                tokio::spawn(async { String::new() }),
            )
        };

        // Wait for completion with optional timeout
        let wait_result = if let Some(duration) = timeout_duration {
            match timeout(duration, child.wait()).await {
                Ok(result) => result,
                Err(_) => {
                    // Kill the process on timeout
                    let _ = child.kill().await;
                    let duration_ms = start.elapsed().as_millis() as u64;
                    return Ok(ToolResult::timeout(duration.as_secs()).with_duration(duration_ms));
                }
            }
        } else {
            child.wait().await
        };

        let status = wait_result.map_err(|e| {
            ToolError::Process(format!("Failed to wait for process: {}", e))
        })?;

        let exit_code = status.code().unwrap_or(-1);
        let stdout = stdout_result.await.unwrap_or_default();
        let stderr = stderr_result.await.unwrap_or_default();

        let duration_ms = start.elapsed().as_millis() as u64;

        Ok(ToolResult::from_shell(exit_code, stdout, stderr).with_duration(duration_ms))
    }

    /// Parse shell config from tool config.
    fn parse_config(&self, config: &ToolConfig, ctx: &ExecutionContext) -> Result<ShellConfig, ToolError> {
        // First render templates in the config
        let template_ctx = ctx.to_template_context();
        let rendered_config = self.template_engine.render_value(&config.config, &template_ctx)?;

        // Parse the config
        let mut shell_config: ShellConfig = serde_json::from_value(rendered_config)
            .map_err(|e| ToolError::Configuration(format!("Invalid shell config: {}", e)))?;

        // Override timeout if set at tool config level
        if let Some(timeout_secs) = config.timeout {
            shell_config.timeout_seconds = Some(timeout_secs);
        }

        Ok(shell_config)
    }
}

impl Default for ShellTool {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for ShellTool {
    fn name(&self) -> &'static str {
        "shell"
    }

    async fn execute(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let shell_config = self.parse_config(config, ctx)?;

        let timeout_duration = shell_config.timeout_seconds.map(Duration::from_secs);

        tracing::debug!(
            command = %shell_config.command,
            shell = %shell_config.shell,
            cwd = ?shell_config.cwd,
            timeout = ?timeout_duration,
            "Executing shell command"
        );

        self.execute_command(
            &shell_config.command,
            &shell_config.shell,
            shell_config.cwd.as_deref(),
            &shell_config.env,
            timeout_duration,
            shell_config.capture,
        )
        .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::result::ToolStatus;

    #[tokio::test]
    async fn test_shell_echo() {
        let tool = ShellTool::new();
        let result = tool
            .execute_command(
                "echo 'hello world'",
                "bash",
                None,
                &HashMap::new(),
                None,
                true,
            )
            .await
            .unwrap();

        assert!(result.is_success());
        assert_eq!(result.exit_code, Some(0));
        assert!(result.stdout.as_ref().unwrap().contains("hello world"));
    }

    #[tokio::test]
    async fn test_shell_exit_code() {
        let tool = ShellTool::new();
        let result = tool
            .execute_command("exit 42", "bash", None, &HashMap::new(), None, true)
            .await
            .unwrap();

        assert!(!result.is_success());
        assert_eq!(result.exit_code, Some(42));
    }

    #[tokio::test]
    async fn test_shell_stderr() {
        let tool = ShellTool::new();
        let result = tool
            .execute_command(
                "echo 'error' >&2",
                "bash",
                None,
                &HashMap::new(),
                None,
                true,
            )
            .await
            .unwrap();

        assert!(result.is_success());
        assert!(result.stderr.as_ref().unwrap().contains("error"));
    }

    #[tokio::test]
    async fn test_shell_env() {
        let tool = ShellTool::new();
        let mut env = HashMap::new();
        env.insert("MY_VAR".to_string(), "my_value".to_string());

        let result = tool
            .execute_command("echo $MY_VAR", "bash", None, &env, None, true)
            .await
            .unwrap();

        assert!(result.is_success());
        assert!(result.stdout.as_ref().unwrap().contains("my_value"));
    }

    #[tokio::test]
    async fn test_shell_timeout() {
        let tool = ShellTool::new();
        let result = tool
            .execute_command(
                "sleep 10",
                "bash",
                None,
                &HashMap::new(),
                Some(Duration::from_millis(100)),
                true,
            )
            .await
            .unwrap();

        assert_eq!(result.status, ToolStatus::Timeout);
    }

    #[tokio::test]
    async fn test_shell_tool_interface() {
        let tool = ShellTool::new();
        assert_eq!(tool.name(), "shell");

        let config = ToolConfig {
            kind: "shell".to_string(),
            config: serde_json::json!({
                "command": "echo 'test'"
            }),
            timeout: None,
            retry: None,
            auth: None,
        };

        let ctx = ExecutionContext::default();
        let result = tool.execute(&config, &ctx).await.unwrap();
        assert!(result.is_success());
    }

    #[tokio::test]
    async fn test_shell_template_rendering() {
        let tool = ShellTool::new();
        let config = ToolConfig {
            kind: "shell".to_string(),
            config: serde_json::json!({
                "command": "echo '{{ message }}'"
            }),
            timeout: None,
            retry: None,
            auth: None,
        };

        let mut ctx = ExecutionContext::default();
        ctx.set_variable("message", serde_json::json!("rendered"));

        let result = tool.execute(&config, &ctx).await.unwrap();
        assert!(result.is_success());
        assert!(result.stdout.as_ref().unwrap().contains("rendered"));
    }
}
