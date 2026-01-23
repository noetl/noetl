//! Worker configuration.

use std::time::Duration;
use anyhow::Result;

/// Worker pool configuration.
#[derive(Debug, Clone)]
pub struct WorkerConfig {
    /// Unique worker identifier (UUID).
    pub worker_id: String,

    /// Worker pool name.
    pub pool_name: String,

    /// Control plane server URL.
    pub server_url: String,

    /// NATS server URL.
    pub nats_url: String,

    /// NATS stream name.
    pub nats_stream: String,

    /// NATS consumer name.
    pub nats_consumer: String,

    /// Heartbeat interval.
    pub heartbeat_interval: Duration,

    /// Maximum concurrent tasks.
    pub max_concurrent_tasks: usize,
}

impl WorkerConfig {
    /// Load configuration from environment variables.
    pub fn from_env() -> Result<Self> {
        let worker_id = std::env::var("WORKER_ID")
            .unwrap_or_else(|_| uuid::Uuid::new_v4().to_string());

        let pool_name = std::env::var("WORKER_POOL_NAME")
            .unwrap_or_else(|_| "default".to_string());

        let server_url = std::env::var("NOETL_SERVER_URL")
            .unwrap_or_else(|_| "http://localhost:8082".to_string());

        let nats_url = std::env::var("NATS_URL")
            .unwrap_or_else(|_| "nats://localhost:4222".to_string());

        let nats_stream = std::env::var("NATS_STREAM")
            .unwrap_or_else(|_| "noetl_commands".to_string());

        let nats_consumer = std::env::var("NATS_CONSUMER")
            .unwrap_or_else(|_| "worker-pool".to_string());

        let heartbeat_secs: u64 = std::env::var("WORKER_HEARTBEAT_INTERVAL")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(15);

        let max_concurrent: usize = std::env::var("WORKER_MAX_CONCURRENT")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(4);

        Ok(Self {
            worker_id,
            pool_name,
            server_url,
            nats_url,
            nats_stream,
            nats_consumer,
            heartbeat_interval: Duration::from_secs(heartbeat_secs),
            max_concurrent_tasks: max_concurrent,
        })
    }
}

impl Default for WorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: uuid::Uuid::new_v4().to_string(),
            pool_name: "default".to_string(),
            server_url: "http://localhost:8082".to_string(),
            nats_url: "nats://localhost:4222".to_string(),
            nats_stream: "noetl_commands".to_string(),
            nats_consumer: "worker-pool".to_string(),
            heartbeat_interval: Duration::from_secs(15),
            max_concurrent_tasks: 4,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_default() {
        let config = WorkerConfig::default();
        assert_eq!(config.pool_name, "default");
        assert_eq!(config.max_concurrent_tasks, 4);
    }
}
