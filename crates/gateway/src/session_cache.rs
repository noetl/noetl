//! Session cache using NATS JetStream K/V store.
//!
//! Provides fast session validation by checking the K/V cache before
//! triggering playbook execution. Sessions are cached with a configurable TTL.

use async_nats::jetstream::{self, kv::Store};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;

/// Cached session data matching the structure from auth0_login playbook
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CachedSession {
    pub session_token: String,
    pub user_id: i32,
    pub email: String,
    pub display_name: String,
    pub expires_at: String,
    pub is_active: bool,
    #[serde(default)]
    pub roles: Vec<String>,
}

/// Session cache backed by NATS JetStream K/V
#[derive(Clone)]
pub struct SessionCache {
    store: Arc<RwLock<Option<Store>>>,
    bucket_name: String,
    ttl_secs: u64,
}

impl SessionCache {
    /// Create a new session cache (not yet connected)
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
                tracing::debug!("Session cache: connecting to NATS with auth: {} (user: {})", server_addr, user);
                async_nats::ConnectOptions::with_user_and_password(user.to_string(), pass.to_string())
                    .connect(&server_addr)
                    .await
            } else {
                tracing::debug!("Session cache: connecting to NATS: {}", server_addr);
                async_nats::connect(&server_addr).await
            };

            match result {
                Ok(c) => c,
                Err(e) => {
                    tracing::warn!(
                        "Session cache: failed to connect to NATS ({}), caching disabled",
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
                        "Session cache: failed to connect to NATS ({}), caching disabled",
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
                        description: "Session cache for gateway authentication".to_string(),
                        max_value_size: 1024 * 10, // 10KB max per session
                        history: 1,                 // No history needed for cache
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
                            "Session cache: K/V bucket unavailable (get: {}, create: {}), caching disabled",
                            e, create_err
                        );
                        return Ok(false);
                    }
                }
            }
        };

        let mut guard = self.store.write().await;
        *guard = Some(store);

        tracing::info!(
            "Session cache initialized: bucket={}, ttl={}s",
            self.bucket_name,
            self.ttl_secs
        );

        Ok(true)
    }

    /// Check if cache is connected
    pub async fn is_connected(&self) -> bool {
        self.store.read().await.is_some()
    }

    /// Get a cached session by token
    pub async fn get(&self, session_token: &str) -> Option<CachedSession> {
        let guard = self.store.read().await;
        let store = guard.as_ref()?;

        match store.get(session_token).await {
            Ok(Some(entry)) => {
                match serde_json::from_slice::<CachedSession>(&entry) {
                    Ok(session) => {
                        // Verify session is still active
                        if session.is_active {
                            tracing::debug!("Session cache HIT: {}", &session_token[..8.min(session_token.len())]);
                            Some(session)
                        } else {
                            tracing::debug!("Session cache HIT but inactive: {}", &session_token[..8.min(session_token.len())]);
                            None
                        }
                    }
                    Err(e) => {
                        tracing::warn!("Failed to deserialize cached session: {}", e);
                        None
                    }
                }
            }
            Ok(None) => {
                tracing::debug!("Session cache MISS: {}", &session_token[..8.min(session_token.len())]);
                None
            }
            Err(e) => {
                tracing::warn!("Session cache get error: {}", e);
                None
            }
        }
    }

    /// Cache a session
    pub async fn put(&self, session: &CachedSession) -> anyhow::Result<()> {
        let guard = self.store.read().await;
        let store = match guard.as_ref() {
            Some(s) => s,
            None => {
                tracing::warn!("Session cache not connected, skipping put");
                return Ok(());
            }
        };

        let data = serde_json::to_vec(session)?;
        store.put(&session.session_token, data.into()).await?;

        tracing::debug!(
            "Session cached: token={}, user={}",
            &session.session_token[..8.min(session.session_token.len())],
            session.email
        );

        Ok(())
    }

    /// Invalidate a cached session
    pub async fn invalidate(&self, session_token: &str) -> anyhow::Result<()> {
        let guard = self.store.read().await;
        let store = match guard.as_ref() {
            Some(s) => s,
            None => return Ok(()),
        };

        // Delete the key (ignore if not found)
        let _ = store.delete(session_token).await;

        tracing::debug!(
            "Session invalidated: {}",
            &session_token[..8.min(session_token.len())]
        );

        Ok(())
    }
}
