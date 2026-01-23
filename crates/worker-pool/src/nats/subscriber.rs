//! NATS JetStream subscriber for command notifications.

use anyhow::Result;
use async_nats::jetstream::{self, consumer::pull::Config as ConsumerConfig, Context};
use futures::StreamExt;
use serde::{Deserialize, Serialize};

/// Command notification received from NATS.
///
/// This is a lightweight notification that triggers command fetching.
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

/// NATS JetStream subscriber for command notifications.
pub struct NatsSubscriber {
    /// JetStream context.
    js: Context,

    /// Stream name.
    stream: String,

    /// Consumer name.
    consumer: String,

    /// Subject to subscribe to.
    subject: String,
}

impl NatsSubscriber {
    /// Connect to NATS and create a subscriber.
    pub async fn connect(
        nats_url: &str,
        stream: &str,
        consumer: &str,
    ) -> Result<Self> {
        let client = async_nats::connect(nats_url).await?;
        let js = jetstream::new(client);

        // Ensure stream exists
        let stream_config = jetstream::stream::Config {
            name: stream.to_string(),
            subjects: vec!["noetl.commands".to_string()],
            ..Default::default()
        };

        // Try to get existing stream or create new one
        match js.get_stream(stream).await {
            Ok(_) => {
                tracing::debug!(stream = %stream, "Using existing NATS stream");
            }
            Err(_) => {
                js.create_stream(stream_config).await?;
                tracing::info!(stream = %stream, "Created NATS stream");
            }
        }

        Ok(Self {
            js,
            stream: stream.to_string(),
            consumer: consumer.to_string(),
            subject: "noetl.commands".to_string(),
        })
    }

    /// Create or get the durable consumer.
    async fn ensure_consumer(&self) -> Result<jetstream::consumer::Consumer<jetstream::consumer::pull::Config>> {
        let stream = self.js.get_stream(&self.stream).await?;

        let consumer_config = ConsumerConfig {
            durable_name: Some(self.consumer.clone()),
            filter_subject: self.subject.clone(),
            ..Default::default()
        };

        // Try to get existing consumer or create new one
        match stream.get_consumer(&self.consumer).await {
            Ok(consumer) => Ok(consumer),
            Err(_) => {
                let consumer = stream.create_consumer(consumer_config).await?;
                tracing::info!(consumer = %self.consumer, "Created NATS consumer");
                Ok(consumer)
            }
        }
    }

    /// Receive the next command notification.
    ///
    /// This blocks until a message is available or the operation times out.
    pub async fn receive(&self) -> Result<Option<(CommandNotification, async_nats::jetstream::Message)>> {
        let consumer = self.ensure_consumer().await?;

        // Fetch one message with a timeout
        let mut messages = consumer.fetch().max_messages(1).messages().await?;

        if let Some(msg) = messages.next().await {
            let msg = msg.map_err(|e| anyhow::anyhow!("Failed to receive message: {}", e))?;
            let notification: CommandNotification = serde_json::from_slice(&msg.payload)?;
            return Ok(Some((notification, msg)));
        }

        Ok(None)
    }

    /// Acknowledge a message.
    pub async fn ack(&self, msg: &async_nats::jetstream::Message) -> Result<()> {
        msg.ack()
            .await
            .map_err(|e| anyhow::anyhow!("Failed to ack message: {}", e))?;
        Ok(())
    }

    /// Negatively acknowledge a message (will be redelivered).
    pub async fn nack(&self, msg: &async_nats::jetstream::Message) -> Result<()> {
        msg.ack_with(async_nats::jetstream::AckKind::Nak(None))
            .await
            .map_err(|e| anyhow::anyhow!("Failed to nack message: {}", e))?;
        Ok(())
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
        assert!(json.contains("cmd-abc123"));

        let parsed: CommandNotification = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.execution_id, 12345);
    }
}
