//! Worker lifecycle management.

use anyhow::Result;
use std::sync::Arc;
use tokio::sync::Semaphore;

use crate::client::{ClaimResult, ControlPlaneClient};
use crate::config::WorkerConfig;
use crate::executor::CommandExecutor;
use crate::nats::NatsSubscriber;

/// Worker pool that processes commands.
pub struct Worker {
    /// Worker configuration.
    config: WorkerConfig,

    /// NATS subscriber for command notifications.
    subscriber: NatsSubscriber,

    /// Control plane HTTP client.
    client: ControlPlaneClient,

    /// Command executor.
    executor: Arc<CommandExecutor>,

    /// Semaphore for concurrency control.
    semaphore: Arc<Semaphore>,
}

impl Worker {
    /// Create a new worker.
    pub async fn new(config: WorkerConfig) -> Result<Self> {
        // Connect to NATS
        let subscriber = NatsSubscriber::connect(
            &config.nats_url,
            &config.nats_stream,
            &config.nats_consumer,
        )
        .await?;

        // Create HTTP client
        let client = ControlPlaneClient::new(&config.server_url);

        // Create executor
        let executor = Arc::new(CommandExecutor::new(
            client.clone(),
            config.worker_id.clone(),
        ));

        // Create semaphore for concurrency control
        let semaphore = Arc::new(Semaphore::new(config.max_concurrent_tasks));

        Ok(Self {
            config,
            subscriber,
            client,
            executor,
            semaphore,
        })
    }

    /// Run the worker.
    pub async fn run(&self) -> Result<()> {
        // Register worker
        self.register().await?;

        // Start heartbeat task
        let heartbeat_handle = self.start_heartbeat();

        // Process commands
        let result = self.process_commands().await;

        // Stop heartbeat
        heartbeat_handle.abort();

        // Deregister worker
        self.deregister().await?;

        result
    }

    /// Register the worker with the control plane.
    async fn register(&self) -> Result<()> {
        let hostname = hostname::get()
            .map(|h| h.to_string_lossy().to_string())
            .unwrap_or_else(|_| "unknown".to_string());

        self.client
            .register_worker(&self.config.worker_id, &self.config.pool_name, &hostname)
            .await?;

        tracing::info!(
            worker_id = %self.config.worker_id,
            pool_name = %self.config.pool_name,
            hostname = %hostname,
            "Worker registered"
        );

        Ok(())
    }

    /// Deregister the worker.
    async fn deregister(&self) -> Result<()> {
        self.client
            .deregister_worker(&self.config.worker_id, &self.config.pool_name)
            .await?;

        tracing::info!(
            worker_id = %self.config.worker_id,
            "Worker deregistered"
        );

        Ok(())
    }

    /// Start the heartbeat background task.
    fn start_heartbeat(&self) -> tokio::task::JoinHandle<()> {
        let client = self.client.clone();
        let worker_id = self.config.worker_id.clone();
        let pool_name = self.config.pool_name.clone();
        let interval = self.config.heartbeat_interval;

        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(interval);
            ticker.tick().await; // Skip first immediate tick

            loop {
                ticker.tick().await;

                if let Err(e) = client.heartbeat(&worker_id, &pool_name).await {
                    tracing::warn!(error = %e, "Heartbeat failed");
                } else {
                    tracing::trace!("Heartbeat sent");
                }
            }
        })
    }

    /// Process commands from NATS.
    async fn process_commands(&self) -> Result<()> {
        loop {
            // Wait for available slot
            let permit = self.semaphore.clone().acquire_owned().await?;

            // Receive notification
            match self.subscriber.receive().await? {
                Some((notification, msg)) => {
                    tracing::debug!(
                        execution_id = notification.execution_id,
                        command_id = %notification.command_id,
                        step = %notification.step,
                        "Received command notification"
                    );

                    // Try to claim the command
                    match self
                        .client
                        .claim_command(
                            notification.execution_id,
                            &notification.command_id,
                            &self.config.worker_id,
                        )
                        .await?
                    {
                        ClaimResult::Claimed => {
                            tracing::debug!(
                                command_id = %notification.command_id,
                                "Command claimed"
                            );

                            // Acknowledge NATS message
                            self.subscriber.ack(&msg).await?;

                            // Spawn task to process command
                            let client = self.client.clone();
                            let executor = self.executor.clone();
                            let event_id = notification.event_id;
                            let command_id = notification.command_id.clone();

                            tokio::spawn(async move {
                                // Keep permit until done
                                let _permit = permit;

                                // Fetch full command
                                match client.fetch_command(event_id).await {
                                    Ok(command) => {
                                        if let Err(e) = executor.execute(&command).await {
                                            tracing::error!(
                                                command_id = %command_id,
                                                error = %e,
                                                "Command execution failed"
                                            );
                                        }
                                    }
                                    Err(e) => {
                                        tracing::error!(
                                            event_id,
                                            error = %e,
                                            "Failed to fetch command"
                                        );
                                    }
                                }
                            });
                        }
                        ClaimResult::AlreadyClaimed => {
                            tracing::debug!(
                                command_id = %notification.command_id,
                                "Command already claimed by another worker"
                            );

                            // Acknowledge message (another worker has it)
                            self.subscriber.ack(&msg).await?;

                            // Release permit immediately
                            drop(permit);
                        }
                        ClaimResult::Failed(error) => {
                            tracing::error!(
                                command_id = %notification.command_id,
                                error = %error,
                                "Failed to claim command"
                            );

                            // Nack message for redelivery
                            self.subscriber.nack(&msg).await?;

                            // Release permit
                            drop(permit);
                        }
                    }
                }
                None => {
                    // No message, release permit and continue
                    drop(permit);
                    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_worker_config() {
        let config = WorkerConfig::default();
        assert!(!config.worker_id.is_empty());
        assert_eq!(config.pool_name, "default");
    }
}
