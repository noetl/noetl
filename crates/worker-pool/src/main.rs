//! NoETL Worker Pool binary.
//!
//! Runs a worker that receives commands via NATS and executes tools.

use anyhow::Result;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use worker_pool::{Worker, WorkerConfig};

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,worker_pool=debug".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    // Load environment variables
    dotenvy::dotenv().ok();

    tracing::info!("Starting NoETL Worker Pool");

    // Load configuration
    let config = WorkerConfig::from_env()?;
    tracing::info!(
        worker_id = %config.worker_id,
        pool_name = %config.pool_name,
        server_url = %config.server_url,
        "Worker configuration loaded"
    );

    // Create and run worker
    let worker = Worker::new(config).await?;

    // Handle shutdown signals
    let shutdown = async {
        tokio::signal::ctrl_c()
            .await
            .expect("Failed to install CTRL+C handler");
        tracing::info!("Shutdown signal received");
    };

    tokio::select! {
        result = worker.run() => {
            if let Err(e) = result {
                tracing::error!(error = %e, "Worker error");
                return Err(e);
            }
        }
        _ = shutdown => {
            tracing::info!("Shutting down worker");
        }
    }

    tracing::info!("Worker stopped");
    Ok(())
}
