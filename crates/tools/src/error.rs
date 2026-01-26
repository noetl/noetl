//! Tool execution error types.

use thiserror::Error;

/// Errors that can occur during tool execution.
#[derive(Debug, Error)]
pub enum ToolError {
    /// Tool not found in registry.
    #[error("Tool not found: {0}")]
    NotFound(String),

    /// Tool execution failed.
    #[error("Execution failed: {0}")]
    ExecutionFailed(String),

    /// Tool execution timed out.
    #[error("Execution timed out after {0} seconds")]
    Timeout(u64),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    Configuration(String),

    /// Template rendering error.
    #[error("Template error: {0}")]
    Template(String),

    /// HTTP request error.
    #[error("HTTP error: {0}")]
    Http(String),

    /// Database error.
    #[error("Database error: {0}")]
    Database(String),

    /// Authentication error.
    #[error("Authentication error: {0}")]
    Auth(String),

    /// Process spawn error.
    #[error("Process error: {0}")]
    Process(String),

    /// JSON serialization/deserialization error.
    #[error("JSON error: {0}")]
    Json(String),

    /// I/O error.
    #[error("I/O error: {0}")]
    Io(String),

    /// Script evaluation error.
    #[error("Script error: {0}")]
    Script(String),
}

impl From<std::io::Error> for ToolError {
    fn from(e: std::io::Error) -> Self {
        ToolError::Io(e.to_string())
    }
}

impl From<serde_json::Error> for ToolError {
    fn from(e: serde_json::Error) -> Self {
        ToolError::Json(e.to_string())
    }
}

impl From<reqwest::Error> for ToolError {
    fn from(e: reqwest::Error) -> Self {
        ToolError::Http(e.to_string())
    }
}

impl From<minijinja::Error> for ToolError {
    fn from(e: minijinja::Error) -> Self {
        ToolError::Template(e.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_display() {
        let err = ToolError::NotFound("shell".to_string());
        assert_eq!(err.to_string(), "Tool not found: shell");

        let err = ToolError::Timeout(30);
        assert_eq!(err.to_string(), "Execution timed out after 30 seconds");
    }

    #[test]
    fn test_error_from_io() {
        let io_err = std::io::Error::new(std::io::ErrorKind::NotFound, "file not found");
        let tool_err: ToolError = io_err.into();
        assert!(matches!(tool_err, ToolError::Io(_)));
    }
}
