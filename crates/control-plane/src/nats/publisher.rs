//! NATS command notification publisher.
//!
//! Server uses this to notify workers of new commands via JetStream.
//!
//! Architecture:
//! - Server publishes lightweight command notifications to NATS subject
//! - Workers subscribe and fetch full command details from server API
//! - Workers execute and emit events back to server

use async_nats::jetstream::{self, Context};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use thiserror::Error;

/// Default NATS subject for command notifications.
pub const DEFAULT_SUBJECT: &str = "noetl.commands";

/// Default JetStream stream name.
pub const DEFAULT_STREAM: &str = "noetl_commands";

/// Errors that can occur during NATS operations.
#[derive(Debug, Error)]
pub enum NatsError {
    #[error("NATS connection error: {0}")]
    Connection(String),

    #[error("JetStream error: {0}")]
    JetStream(String),

    #[error("Publish error: {0}")]
    Publish(String),

    #[error("Not connected to NATS")]
    NotConnected,
}

/// Command notification message published to NATS.
///
/// Workers receive this notification and fetch full command details
/// from the server API using the event_id.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandNotification {
    /// Execution ID this command belongs to.
    pub execution_id: i64,

    /// Event ID containing the full command details.
    pub event_id: i64,

    /// Unique command identifier for atomic claiming.
    pub command_id: String,

    /// Step name this command is for.
    pub step: String,

    /// Server URL for fetching command details.
    pub server_url: String,
}

/// NATS JetStream publisher for command notifications.
///
/// This is an optional component - the server works without NATS
/// in direct polling mode.
#[derive(Clone)]
pub struct NatsPublisher {
    /// JetStream context.
    js: Context,

    /// Subject to publish to.
    subject: String,
}

impl NatsPublisher {
    /// Create a new NATS publisher from an existing client.
    ///
    /// # Arguments
    ///
    /// * `client` - Connected NATS client
    /// * `subject` - Subject to publish command notifications to
    /// * `stream_name` - JetStream stream name
    ///
    /// # Returns
    ///
    /// A new `NatsPublisher` or error if stream setup fails.
    pub async fn new(
        client: Arc<async_nats::Client>,
        subject: Option<&str>,
        stream_name: Option<&str>,
    ) -> Result<Self, NatsError> {
        let subject = subject.unwrap_or(DEFAULT_SUBJECT).to_string();
        let stream = stream_name.unwrap_or(DEFAULT_STREAM);

        // Get JetStream context
        let js = jetstream::new((*client).clone());

        // Ensure stream exists
        Self::ensure_stream(&js, stream, &subject).await?;

        Ok(Self { js, subject })
    }

    /// Ensure the JetStream stream exists.
    async fn ensure_stream(js: &Context, stream: &str, subject: &str) -> Result<(), NatsError> {
        // Try to get existing stream info
        match js.get_stream(stream).await {
            Ok(_) => {
                tracing::debug!(stream = %stream, "Using existing NATS stream");
                Ok(())
            }
            Err(_) => {
                // Create stream if it doesn't exist
                let config = jetstream::stream::Config {
                    name: stream.to_string(),
                    subjects: vec![subject.to_string()],
                    max_age: std::time::Duration::from_secs(3600), // 1 hour retention
                    storage: jetstream::stream::StorageType::File,
                    ..Default::default()
                };

                js.create_stream(config)
                    .await
                    .map_err(|e| NatsError::JetStream(e.to_string()))?;

                tracing::info!(stream = %stream, subject = %subject, "Created NATS stream");
                Ok(())
            }
        }
    }

    /// Publish a command notification.
    ///
    /// Workers subscribe to these notifications and fetch full command
    /// details from the server API.
    ///
    /// # Arguments
    ///
    /// * `notification` - Command notification to publish
    ///
    /// # Returns
    ///
    /// Ok if published successfully, error otherwise.
    pub async fn publish_command(
        &self,
        notification: CommandNotification,
    ) -> Result<(), NatsError> {
        let payload = serde_json::to_vec(&notification)
            .map_err(|e| NatsError::Publish(format!("Serialization error: {}", e)))?;

        self.js
            .publish(self.subject.clone(), payload.into())
            .await
            .map_err(|e| NatsError::Publish(e.to_string()))?
            .await
            .map_err(|e| NatsError::Publish(e.to_string()))?;

        tracing::debug!(
            execution_id = notification.execution_id,
            event_id = notification.event_id,
            command_id = %notification.command_id,
            step = %notification.step,
            "Published command notification"
        );

        Ok(())
    }

    /// Publish a command notification with individual parameters.
    ///
    /// Convenience method that builds a CommandNotification from parameters.
    pub async fn publish(
        &self,
        execution_id: i64,
        event_id: i64,
        command_id: &str,
        step: &str,
        server_url: &str,
    ) -> Result<(), NatsError> {
        let notification = CommandNotification {
            execution_id,
            event_id,
            command_id: command_id.to_string(),
            step: step.to_string(),
            server_url: server_url.to_string(),
        };

        self.publish_command(notification).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_command_notification_serialization() {
        let notification = CommandNotification {
            execution_id: 12345,
            event_id: 67890,
            command_id: "cmd-abc123".to_string(),
            step: "process_data".to_string(),
            server_url: "http://localhost:8082".to_string(),
        };

        let json = serde_json::to_string(&notification).unwrap();
        assert!(json.contains("12345"));
        assert!(json.contains("67890"));
        assert!(json.contains("cmd-abc123"));
        assert!(json.contains("process_data"));
    }

    #[test]
    fn test_command_notification_deserialization() {
        let json = r#"{
            "execution_id": 12345,
            "event_id": 67890,
            "command_id": "cmd-abc123",
            "step": "process_data",
            "server_url": "http://localhost:8082"
        }"#;

        let notification: CommandNotification = serde_json::from_str(json).unwrap();
        assert_eq!(notification.execution_id, 12345);
        assert_eq!(notification.event_id, 67890);
        assert_eq!(notification.command_id, "cmd-abc123");
        assert_eq!(notification.step, "process_data");
        assert_eq!(notification.server_url, "http://localhost:8082");
    }

    #[test]
    fn test_default_constants() {
        assert_eq!(DEFAULT_SUBJECT, "noetl.commands");
        assert_eq!(DEFAULT_STREAM, "noetl_commands");
    }
}
