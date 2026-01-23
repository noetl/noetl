//! Event emitter with retry logic.

use anyhow::Result;
use std::time::Duration;

use crate::client::{ControlPlaneClient, WorkerEvent};

/// Event emitter with automatic retry.
pub struct EventEmitter {
    client: ControlPlaneClient,
    max_retries: u32,
    initial_delay: Duration,
    max_delay: Duration,
}

impl EventEmitter {
    /// Create a new event emitter.
    pub fn new(client: ControlPlaneClient) -> Self {
        Self {
            client,
            max_retries: 3,
            initial_delay: Duration::from_millis(500),
            max_delay: Duration::from_secs(10),
        }
    }

    /// Create an event emitter with custom retry settings.
    pub fn with_retry(
        client: ControlPlaneClient,
        max_retries: u32,
        initial_delay: Duration,
        max_delay: Duration,
    ) -> Self {
        Self {
            client,
            max_retries,
            initial_delay,
            max_delay,
        }
    }

    /// Emit an event with retry.
    pub async fn emit(&self, event: WorkerEvent) -> Result<()> {
        let mut delay = self.initial_delay;

        for attempt in 0..=self.max_retries {
            match self.client.emit_event(event.clone()).await {
                Ok(()) => return Ok(()),
                Err(e) if attempt < self.max_retries => {
                    tracing::warn!(
                        attempt = attempt + 1,
                        max_retries = self.max_retries,
                        error = %e,
                        event_type = %event.event_type,
                        "Event emission failed, retrying"
                    );
                    tokio::time::sleep(delay).await;
                    delay = std::cmp::min(delay * 2, self.max_delay);
                }
                Err(e) => {
                    tracing::error!(
                        event_type = %event.event_type,
                        error = %e,
                        "Event emission failed after all retries"
                    );
                    return Err(e);
                }
            }
        }

        Ok(())
    }

    /// Emit a command.claimed event.
    pub async fn emit_command_claimed(
        &self,
        execution_id: i64,
        command_id: &str,
        worker_id: &str,
    ) -> Result<()> {
        self.emit(WorkerEvent {
            event_type: "command.claimed".to_string(),
            execution_id,
            payload: serde_json::json!({
                "command_id": command_id,
                "worker_id": worker_id,
            }),
        })
        .await
    }

    /// Emit a command.started event.
    pub async fn emit_command_started(
        &self,
        execution_id: i64,
        command_id: &str,
        worker_id: &str,
        step: &str,
    ) -> Result<()> {
        self.emit(WorkerEvent {
            event_type: "command.started".to_string(),
            execution_id,
            payload: serde_json::json!({
                "command_id": command_id,
                "worker_id": worker_id,
                "step": step,
            }),
        })
        .await
    }

    /// Emit a call.done event.
    pub async fn emit_call_done(
        &self,
        execution_id: i64,
        command_id: &str,
        call_index: usize,
        result: &serde_json::Value,
    ) -> Result<()> {
        self.emit(WorkerEvent {
            event_type: "call.done".to_string(),
            execution_id,
            payload: serde_json::json!({
                "command_id": command_id,
                "call_index": call_index,
                "result": result,
            }),
        })
        .await
    }

    /// Emit a call.error event.
    pub async fn emit_call_error(
        &self,
        execution_id: i64,
        command_id: &str,
        call_index: usize,
        error: &str,
    ) -> Result<()> {
        self.emit(WorkerEvent {
            event_type: "call.error".to_string(),
            execution_id,
            payload: serde_json::json!({
                "command_id": command_id,
                "call_index": call_index,
                "error": error,
            }),
        })
        .await
    }

    /// Emit a step.exit event.
    pub async fn emit_step_exit(
        &self,
        execution_id: i64,
        step: &str,
        status: &str,
        data: Option<&serde_json::Value>,
    ) -> Result<()> {
        self.emit(WorkerEvent {
            event_type: "step.exit".to_string(),
            execution_id,
            payload: serde_json::json!({
                "step": step,
                "status": status,
                "data": data,
            }),
        })
        .await
    }

    /// Emit a command.completed event.
    pub async fn emit_command_completed(
        &self,
        execution_id: i64,
        command_id: &str,
        status: &str,
    ) -> Result<()> {
        self.emit(WorkerEvent {
            event_type: "command.completed".to_string(),
            execution_id,
            payload: serde_json::json!({
                "command_id": command_id,
                "status": status,
            }),
        })
        .await
    }

    /// Emit a command.failed event.
    pub async fn emit_command_failed(
        &self,
        execution_id: i64,
        command_id: &str,
        error: &str,
    ) -> Result<()> {
        self.emit(WorkerEvent {
            event_type: "command.failed".to_string(),
            execution_id,
            payload: serde_json::json!({
                "command_id": command_id,
                "error": error,
            }),
        })
        .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_event_emitter_creation() {
        let client = ControlPlaneClient::new("http://localhost:8082");
        let emitter = EventEmitter::new(client);

        assert_eq!(emitter.max_retries, 3);
        assert_eq!(emitter.initial_delay, Duration::from_millis(500));
    }

    #[test]
    fn test_event_emitter_custom_retry() {
        let client = ControlPlaneClient::new("http://localhost:8082");
        let emitter = EventEmitter::with_retry(
            client,
            5,
            Duration::from_millis(100),
            Duration::from_secs(5),
        );

        assert_eq!(emitter.max_retries, 5);
        assert_eq!(emitter.initial_delay, Duration::from_millis(100));
        assert_eq!(emitter.max_delay, Duration::from_secs(5));
    }
}
