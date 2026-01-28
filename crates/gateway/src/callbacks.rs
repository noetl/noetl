//! NATS-based callback system for async playbook execution results.
//!
//! When gateway starts a playbook, it generates a unique request_id and
//! subscribes to the NATS subject `noetl.callbacks.{request_id}`.
//! The playbook publishes results to that subject when done.
//! Gateway receives via subscription and delivers to waiting HTTP request.

use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{oneshot, RwLock, mpsc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Result delivered via callback
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CallbackResult {
    pub request_id: String,
    #[serde(default)]
    pub execution_id: Option<String>,
    #[serde(default)]
    pub step: Option<String>,
    #[serde(default = "default_status")]
    pub status: String,
    #[serde(default)]
    pub data: serde_json::Value,
}

fn default_status() -> String {
    "success".to_string()
}

/// Callback manager using NATS pub/sub
///
/// Local channels are still needed for HTTP request-response,
/// but message routing happens via NATS subscriptions.
#[derive(Clone)]
pub struct CallbackManager {
    /// Map of request_id -> oneshot sender (for delivering to waiting HTTP requests)
    pending: Arc<RwLock<HashMap<String, oneshot::Sender<CallbackResult>>>>,
    /// NATS subject prefix for callbacks
    subject_prefix: String,
}

impl CallbackManager {
    pub fn new(subject_prefix: Option<String>) -> Self {
        Self {
            pending: Arc::new(RwLock::new(HashMap::new())),
            subject_prefix: subject_prefix.unwrap_or_else(|| "noetl.callbacks".to_string()),
        }
    }

    /// Generate a new request_id and register a callback
    /// Returns (request_id, nats_subject, receiver)
    pub async fn register(&self) -> (String, String, oneshot::Receiver<CallbackResult>) {
        let request_id = Uuid::new_v4().to_string();
        let subject = format!("{}.{}", self.subject_prefix, request_id);
        let (tx, rx) = oneshot::channel();

        self.pending.write().await.insert(request_id.clone(), tx);
        tracing::debug!("Registered callback: request_id={}, subject={}", request_id, subject);

        (request_id, subject, rx)
    }

    /// Deliver a result to a waiting callback (called when NATS message arrives)
    pub async fn deliver(&self, result: CallbackResult) -> bool {
        let request_id = result.request_id.clone();

        if let Some(tx) = self.pending.write().await.remove(&request_id) {
            match tx.send(result) {
                Ok(()) => {
                    tracing::debug!("Delivered callback for request_id={}", request_id);
                    true
                }
                Err(_) => {
                    tracing::warn!("Callback receiver dropped for request_id={}", request_id);
                    false
                }
            }
        } else {
            tracing::warn!("No pending callback for request_id={}", request_id);
            false
        }
    }

    /// Cancel a pending callback (cleanup on timeout)
    pub async fn cancel(&self, request_id: &str) {
        self.pending.write().await.remove(request_id);
        tracing::debug!("Cancelled callback for request_id={}", request_id);
    }

    /// Get the NATS subject pattern for subscribing to all callbacks
    pub fn subscription_subject(&self) -> String {
        format!("{}.>", self.subject_prefix)
    }
}

/// Start the NATS callback listener
/// This should be called once at gateway startup
pub async fn start_nats_listener(
    nats_url: &str,
    manager: Arc<CallbackManager>,
) -> anyhow::Result<()> {
    let client = async_nats::connect(nats_url).await?;
    let subject = manager.subscription_subject();

    tracing::info!("Subscribing to NATS callbacks: {}", subject);

    let mut subscriber = client.subscribe(subject).await?;

    tokio::spawn(async move {
        while let Some(msg) = subscriber.next().await {
            match serde_json::from_slice::<CallbackResult>(&msg.payload) {
                Ok(result) => {
                    tracing::info!(
                        "Received NATS callback: request_id={}, step={:?}",
                        result.request_id,
                        result.step
                    );
                    manager.deliver(result).await;
                }
                Err(e) => {
                    tracing::warn!("Failed to parse callback message: {}", e);
                }
            }
        }
        tracing::warn!("NATS callback subscription ended");
    });

    Ok(())
}

use futures::StreamExt;
