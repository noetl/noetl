//! Result extension trait for logging errors with context.
//!
//! This module provides a `ResultExt` trait that adds a `log` method
//! to `Result` types for automatic error logging with context.

use std::fmt::Display;
use tracing::error;

/// Extension trait for logging errors with context.
///
/// This trait adds a `log` method to `Result` types that logs
/// errors with the provided context message and source location.
pub trait ResultExt<T, E> {
    /// Log the error with context if this is an `Err` variant.
    ///
    /// # Arguments
    ///
    /// * `context` - A context message to include in the log
    ///
    /// # Returns
    ///
    /// The original `Result` unchanged.
    ///
    /// # Example
    ///
    /// ```ignore
    /// use noetl_control_plane::result_ext::ResultExt;
    ///
    /// let result: Result<i32, &str> = Err("something went wrong");
    /// let _ = result.log("processing request");
    /// // Logs: "processing request" with error details
    /// ```
    fn log<S: ToString>(self, context: S) -> Result<T, E>;
}

impl<T, E: Display> ResultExt<T, E> for Result<T, E> {
    #[track_caller]
    fn log<S: ToString>(self, context: S) -> Result<T, E> {
        if let Err(ref e) = self {
            let caller_location = std::panic::Location::caller();
            error!(
                target: "noetl_control_plane",
                error = %e,
                file = %format!("{}:{}", caller_location.file(), caller_location.line()),
                context = %context.to_string(),
                "Operation failed"
            );
        }
        self
    }
}

/// Extension trait for logging errors with context, returning Option.
pub trait OptionResultExt<T> {
    /// Log if this is a `None` variant.
    ///
    /// # Arguments
    ///
    /// * `context` - A context message to include in the log
    ///
    /// # Returns
    ///
    /// The original `Option` unchanged.
    fn log_none<S: ToString>(self, context: S) -> Option<T>;
}

impl<T> OptionResultExt<T> for Option<T> {
    #[track_caller]
    fn log_none<S: ToString>(self, context: S) -> Option<T> {
        if self.is_none() {
            let caller_location = std::panic::Location::caller();
            tracing::warn!(
                target: "noetl_control_plane",
                file = %format!("{}:{}", caller_location.file(), caller_location.line()),
                context = %context.to_string(),
                "Expected value was None"
            );
        }
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_result_ext_ok() {
        let result: Result<i32, &str> = Ok(42);
        let logged = result.log("test context");
        assert_eq!(logged.unwrap(), 42);
    }

    #[test]
    fn test_result_ext_err() {
        let result: Result<i32, &str> = Err("test error");
        let logged = result.log("test context");
        assert!(logged.is_err());
    }

    #[test]
    fn test_option_ext_some() {
        let opt: Option<i32> = Some(42);
        let logged = opt.log_none("test context");
        assert_eq!(logged.unwrap(), 42);
    }

    #[test]
    fn test_option_ext_none() {
        let opt: Option<i32> = None;
        let logged = opt.log_none("test context");
        assert!(logged.is_none());
    }
}
