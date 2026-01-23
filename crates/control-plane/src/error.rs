//! Error types for the NoETL Control Plane server.
//!
//! This module provides custom error types that implement `IntoResponse`
//! for seamless integration with Axum handlers.

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;
use thiserror::Error;

/// Application-level errors for the control plane.
#[derive(Error, Debug)]
pub enum AppError {
    /// Database error
    #[error("Database error: {0}")]
    Database(#[from] sqlx::Error),

    /// Not found error
    #[error("Resource not found: {0}")]
    NotFound(String),

    /// Validation error
    #[error("Validation error: {0}")]
    Validation(String),

    /// Authentication error
    #[error("Authentication error: {0}")]
    Auth(String),

    /// Authorization error
    #[error("Authorization error: {0}")]
    Forbidden(String),

    /// Conflict error (e.g., duplicate resource)
    #[error("Conflict: {0}")]
    Conflict(String),

    /// Bad request error
    #[error("Bad request: {0}")]
    BadRequest(String),

    /// Internal server error
    #[error("Internal error: {0}")]
    Internal(String),

    /// Configuration error
    #[error("Configuration error: {0}")]
    Config(String),

    /// NATS messaging error
    #[error("NATS error: {0}")]
    Nats(String),

    /// Serialization error
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    /// Template rendering error
    #[error("Template error: {0}")]
    Template(String),

    /// Encryption error
    #[error("Encryption error: {0}")]
    Encryption(String),

    /// External service error
    #[error("External service error: {0}")]
    ExternalService(String),

    /// Parse error (YAML, JSON, etc.)
    #[error("Parse error: {0}")]
    Parse(String),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, error_message) = match &self {
            AppError::Database(e) => {
                tracing::error!(error = %e, "Database error");
                (StatusCode::INTERNAL_SERVER_ERROR, self.to_string())
            }
            AppError::NotFound(msg) => (StatusCode::NOT_FOUND, msg.clone()),
            AppError::Validation(msg) => (StatusCode::UNPROCESSABLE_ENTITY, msg.clone()),
            AppError::Auth(msg) => (StatusCode::UNAUTHORIZED, msg.clone()),
            AppError::Forbidden(msg) => (StatusCode::FORBIDDEN, msg.clone()),
            AppError::Conflict(msg) => (StatusCode::CONFLICT, msg.clone()),
            AppError::BadRequest(msg) => (StatusCode::BAD_REQUEST, msg.clone()),
            AppError::Internal(msg) => {
                tracing::error!(error = %msg, "Internal error");
                (StatusCode::INTERNAL_SERVER_ERROR, msg.clone())
            }
            AppError::Config(msg) => {
                tracing::error!(error = %msg, "Configuration error");
                (StatusCode::INTERNAL_SERVER_ERROR, msg.clone())
            }
            AppError::Nats(msg) => {
                tracing::error!(error = %msg, "NATS error");
                (StatusCode::SERVICE_UNAVAILABLE, msg.clone())
            }
            AppError::Serialization(e) => {
                tracing::error!(error = %e, "Serialization error");
                (StatusCode::INTERNAL_SERVER_ERROR, self.to_string())
            }
            AppError::Template(msg) => {
                tracing::error!(error = %msg, "Template error");
                (StatusCode::INTERNAL_SERVER_ERROR, msg.clone())
            }
            AppError::Encryption(msg) => {
                tracing::error!(error = %msg, "Encryption error");
                (StatusCode::INTERNAL_SERVER_ERROR, msg.clone())
            }
            AppError::ExternalService(msg) => {
                tracing::warn!(error = %msg, "External service error");
                (StatusCode::BAD_GATEWAY, msg.clone())
            }
            AppError::Parse(msg) => {
                tracing::error!(error = %msg, "Parse error");
                (StatusCode::BAD_REQUEST, msg.clone())
            }
        };

        let body = Json(json!({
            "error": error_message,
            "status": status.as_u16()
        }));

        (status, body).into_response()
    }
}

/// Result type alias using AppError.
pub type AppResult<T> = Result<T, AppError>;

impl From<anyhow::Error> for AppError {
    fn from(err: anyhow::Error) -> Self {
        AppError::Internal(err.to_string())
    }
}

impl From<envy::Error> for AppError {
    fn from(err: envy::Error) -> Self {
        AppError::Config(err.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_not_found_error() {
        let err = AppError::NotFound("User not found".to_string());
        assert_eq!(err.to_string(), "Resource not found: User not found");
    }

    #[test]
    fn test_validation_error() {
        let err = AppError::Validation("Invalid email".to_string());
        assert_eq!(err.to_string(), "Validation error: Invalid email");
    }
}
