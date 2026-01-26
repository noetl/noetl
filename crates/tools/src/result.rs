//! Tool execution result types.

use serde::{Deserialize, Serialize};

/// Status of a tool execution.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ToolStatus {
    /// Tool executed successfully.
    Success,
    /// Tool execution failed.
    Error,
    /// Tool execution timed out.
    Timeout,
}

impl ToolStatus {
    /// Returns true if the status indicates success.
    pub fn is_success(&self) -> bool {
        matches!(self, ToolStatus::Success)
    }

    /// Returns true if the status indicates an error.
    pub fn is_error(&self) -> bool {
        matches!(self, ToolStatus::Error)
    }

    /// Returns true if the status indicates a timeout.
    pub fn is_timeout(&self) -> bool {
        matches!(self, ToolStatus::Timeout)
    }
}

impl std::fmt::Display for ToolStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ToolStatus::Success => write!(f, "success"),
            ToolStatus::Error => write!(f, "error"),
            ToolStatus::Timeout => write!(f, "timeout"),
        }
    }
}

/// Result of a tool execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolResult {
    /// Execution status.
    pub status: ToolStatus,

    /// Result data (tool-specific).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<serde_json::Value>,

    /// Error message if status is Error.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,

    /// Standard output (for shell/script tools).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stdout: Option<String>,

    /// Standard error (for shell/script tools).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stderr: Option<String>,

    /// Exit code (for shell/script tools).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exit_code: Option<i32>,

    /// Execution duration in milliseconds.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<u64>,
}

impl ToolResult {
    /// Create a successful result with data.
    pub fn success(data: serde_json::Value) -> Self {
        Self {
            status: ToolStatus::Success,
            data: Some(data),
            error: None,
            stdout: None,
            stderr: None,
            exit_code: None,
            duration_ms: None,
        }
    }

    /// Create an error result with message.
    pub fn error(message: impl Into<String>) -> Self {
        Self {
            status: ToolStatus::Error,
            data: None,
            error: Some(message.into()),
            stdout: None,
            stderr: None,
            exit_code: None,
            duration_ms: None,
        }
    }

    /// Create a timeout result.
    pub fn timeout(duration_seconds: u64) -> Self {
        Self {
            status: ToolStatus::Timeout,
            data: None,
            error: Some(format!("Execution timed out after {} seconds", duration_seconds)),
            stdout: None,
            stderr: None,
            exit_code: None,
            duration_ms: Some(duration_seconds * 1000),
        }
    }

    /// Create a result from shell command execution.
    pub fn from_shell(exit_code: i32, stdout: String, stderr: String) -> Self {
        let status = if exit_code == 0 {
            ToolStatus::Success
        } else {
            ToolStatus::Error
        };

        Self {
            status,
            data: Some(serde_json::json!({
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
            })),
            error: if exit_code != 0 {
                Some(format!("Command exited with code {}", exit_code))
            } else {
                None
            },
            stdout: Some(stdout),
            stderr: Some(stderr),
            exit_code: Some(exit_code),
            duration_ms: None,
        }
    }

    /// Set the execution duration.
    pub fn with_duration(mut self, duration_ms: u64) -> Self {
        self.duration_ms = Some(duration_ms);
        self
    }

    /// Set additional data on the result.
    pub fn with_data(mut self, data: serde_json::Value) -> Self {
        self.data = Some(data);
        self
    }

    /// Returns true if the result indicates success.
    pub fn is_success(&self) -> bool {
        self.status.is_success()
    }
}

impl Default for ToolResult {
    fn default() -> Self {
        Self {
            status: ToolStatus::Success,
            data: None,
            error: None,
            stdout: None,
            stderr: None,
            exit_code: None,
            duration_ms: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tool_status_display() {
        assert_eq!(ToolStatus::Success.to_string(), "success");
        assert_eq!(ToolStatus::Error.to_string(), "error");
        assert_eq!(ToolStatus::Timeout.to_string(), "timeout");
    }

    #[test]
    fn test_tool_status_methods() {
        assert!(ToolStatus::Success.is_success());
        assert!(!ToolStatus::Success.is_error());
        assert!(ToolStatus::Error.is_error());
        assert!(ToolStatus::Timeout.is_timeout());
    }

    #[test]
    fn test_tool_result_success() {
        let result = ToolResult::success(serde_json::json!({"key": "value"}));
        assert!(result.is_success());
        assert!(result.data.is_some());
        assert!(result.error.is_none());
    }

    #[test]
    fn test_tool_result_error() {
        let result = ToolResult::error("something went wrong");
        assert!(!result.is_success());
        assert!(result.data.is_none());
        assert_eq!(result.error, Some("something went wrong".to_string()));
    }

    #[test]
    fn test_tool_result_from_shell() {
        let result = ToolResult::from_shell(0, "output".to_string(), "".to_string());
        assert!(result.is_success());
        assert_eq!(result.stdout, Some("output".to_string()));
        assert_eq!(result.exit_code, Some(0));

        let result = ToolResult::from_shell(1, "".to_string(), "error".to_string());
        assert!(!result.is_success());
        assert_eq!(result.exit_code, Some(1));
    }

    #[test]
    fn test_tool_result_serialization() {
        let result = ToolResult::success(serde_json::json!({"count": 42}));
        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("\"status\":\"success\""));
        assert!(json.contains("\"count\":42"));
    }
}
