//! Request store for tracking pending playbook execution requests.
//!
//! Uses NATS JetStream K/V to store request_id -> client mapping.
//! This enables routing callbacks to the correct client when playbooks complete.

use async_nats::jetstream::{self, kv::Store};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;

/// Pending request data stored in NATS K/V
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PendingRequest {
    /// Client ID to route callback to
    pub client_id: String,
    /// Session token for verification
    pub session_token: String,
    /// NoETL execution ID
    pub execution_id: String,
    /// Playbook path being executed
    pub playbook_path: String,
    /// Unix timestamp when request was created
    pub created_at: i64,
}

/// Request store backed by NATS JetStream K/V
#[derive(Clone)]
pub struct RequestStore {
    store: Arc<RwLock<Option<Store>>>,
    bucket_name: String,
    ttl_secs: u64,
}

impl RequestStore {
    /// Create a new request store (not yet connected)
    pub fn new(bucket_name: String, ttl_secs: u64) -> Self {
        Self {
            store: Arc::new(RwLock::new(None)),
            bucket_name,
            ttl_secs,
        }
    }

    /// Connect to NATS and initialize the K/V store.
    /// Returns Ok(true) if connected successfully, Ok(false) if connection failed gracefully.
    pub async fn connect(&self, nats_url: &str) -> anyhow::Result<bool> {
        // Parse URL to extract credentials if present (nats://user:pass@host:port)
        let client = if let Ok(url) = url::Url::parse(nats_url) {
            let host = url.host_str().unwrap_or("localhost");
            let port = url.port().unwrap_or(4222);
            let server_addr = format!("{}:{}", host, port);

            let result = if !url.username().is_empty() {
                let user = url.username();
                let pass = url.password().unwrap_or("");
                tracing::debug!(
                    "Request store: connecting to NATS with auth: {} (user: {})",
                    server_addr,
                    user
                );
                async_nats::ConnectOptions::with_user_and_password(user.to_string(), pass.to_string())
                    .connect(&server_addr)
                    .await
            } else {
                tracing::debug!("Request store: connecting to NATS: {}", server_addr);
                async_nats::connect(&server_addr).await
            };

            match result {
                Ok(c) => c,
                Err(e) => {
                    tracing::warn!(
                        "Request store: failed to connect to NATS ({}), request tracking disabled",
                        e
                    );
                    return Ok(false);
                }
            }
        } else {
            match async_nats::connect(nats_url).await {
                Ok(c) => c,
                Err(e) => {
                    tracing::warn!(
                        "Request store: failed to connect to NATS ({}), request tracking disabled",
                        e
                    );
                    return Ok(false);
                }
            }
        };

        let jetstream = jetstream::new(client);

        // Try to get existing bucket or create new one
        let store = match jetstream.get_key_value(&self.bucket_name).await {
            Ok(store) => {
                tracing::info!("Connected to existing K/V bucket: {}", self.bucket_name);
                store
            }
            Err(e) => {
                // Try to create the bucket
                match jetstream
                    .create_key_value(jetstream::kv::Config {
                        bucket: self.bucket_name.clone(),
                        description: "Pending playbook execution requests for callback routing".to_string(),
                        max_value_size: 1024 * 4, // 4KB max per request
                        history: 1,               // No history needed
                        max_age: Duration::from_secs(self.ttl_secs),
                        ..Default::default()
                    })
                    .await
                {
                    Ok(store) => {
                        tracing::info!("Created K/V bucket: {}", self.bucket_name);
                        store
                    }
                    Err(create_err) => {
                        tracing::warn!(
                            "Request store: K/V bucket unavailable (get: {}, create: {}), request tracking disabled",
                            e,
                            create_err
                        );
                        return Ok(false);
                    }
                }
            }
        };

        let mut guard = self.store.write().await;
        *guard = Some(store);

        tracing::info!(
            "Request store initialized: bucket={}, ttl={}s",
            self.bucket_name,
            self.ttl_secs
        );

        Ok(true)
    }

    /// Check if store is connected
    pub async fn is_connected(&self) -> bool {
        self.store.read().await.is_some()
    }

    /// Store a pending request
    pub async fn put(&self, request_id: &str, request: &PendingRequest) -> anyhow::Result<()> {
        let guard = self.store.read().await;
        let store = match guard.as_ref() {
            Some(s) => s,
            None => {
                tracing::warn!("Request store not connected, skipping put");
                return Ok(());
            }
        };

        let data = serde_json::to_vec(request)?;
        store.put(request_id, data.into()).await?;

        tracing::debug!(
            "Request stored: request_id={}, client_id={}, execution_id={}",
            &request_id[..8.min(request_id.len())],
            &request.client_id[..8.min(request.client_id.len())],
            &request.execution_id[..8.min(request.execution_id.len())]
        );

        Ok(())
    }

    /// Get a pending request
    pub async fn get(&self, request_id: &str) -> Option<PendingRequest> {
        let guard = self.store.read().await;
        let store = guard.as_ref()?;

        match store.get(request_id).await {
            Ok(Some(entry)) => match serde_json::from_slice::<PendingRequest>(&entry) {
                Ok(request) => {
                    tracing::debug!(
                        "Request found: request_id={}, client_id={}",
                        &request_id[..8.min(request_id.len())],
                        &request.client_id[..8.min(request.client_id.len())]
                    );
                    Some(request)
                }
                Err(e) => {
                    tracing::warn!("Failed to deserialize pending request: {}", e);
                    None
                }
            },
            Ok(None) => {
                tracing::debug!(
                    "Request not found: request_id={}",
                    &request_id[..8.min(request_id.len())]
                );
                None
            }
            Err(e) => {
                tracing::warn!("Request store get error: {}", e);
                None
            }
        }
    }

    /// Remove a completed/failed request
    pub async fn remove(&self, request_id: &str) -> anyhow::Result<()> {
        let guard = self.store.read().await;
        let store = match guard.as_ref() {
            Some(s) => s,
            None => return Ok(()),
        };

        // Delete the key (ignore if not found)
        let _ = store.delete(request_id).await;

        tracing::debug!(
            "Request removed: request_id={}",
            &request_id[..8.min(request_id.len())]
        );

        Ok(())
    }

    /// Get all pending requests for a client (for reconnection recovery)
    /// Note: This is inefficient for large datasets - consider indexing if needed
    pub async fn get_by_client(&self, client_id: &str) -> Vec<(String, PendingRequest)> {
        let guard = self.store.read().await;
        let store = match guard.as_ref() {
            Some(s) => s,
            None => return Vec::new(),
        };

        let mut results = Vec::new();

        // Get all keys and filter by client_id
        // Note: NATS K/V doesn't support queries, so we iterate
        match store.keys().await {
            Ok(mut keys) => {
                use futures::StreamExt;
                while let Some(key) = keys.next().await {
                    if let Ok(key) = key {
                        if let Some(request) = self.get(&key).await {
                            if request.client_id == client_id {
                                results.push((key, request));
                            }
                        }
                    }
                }
            }
            Err(e) => {
                tracing::warn!("Failed to iterate request store keys: {}", e);
            }
        }

        tracing::debug!(
            "Found {} pending requests for client_id={}",
            results.len(),
            &client_id[..8.min(client_id.len())]
        );

        results
    }
}
