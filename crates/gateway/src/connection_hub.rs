//! Connection hub for managing client SSE and WebSocket connections.
//!
//! Supports multiple clients per session (multiple browser tabs) and
//! routes playbook callback results to the appropriate client.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tokio::sync::{mpsc, RwLock};
use serde::{Deserialize, Serialize};

/// JSON-RPC 2.0 compatible message format (MCP-compatible)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JsonRpcMessage {
    pub jsonrpc: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub method: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub params: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<JsonRpcError>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JsonRpcError {
    pub code: i32,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<serde_json::Value>,
}

impl JsonRpcMessage {
    /// Create a notification (no id, no response expected)
    pub fn notification(method: &str, params: serde_json::Value) -> Self {
        Self {
            jsonrpc: "2.0".to_string(),
            id: None,
            method: Some(method.to_string()),
            params: Some(params),
            result: None,
            error: None,
        }
    }

    /// Create a response with result
    pub fn response(id: serde_json::Value, result: serde_json::Value) -> Self {
        Self {
            jsonrpc: "2.0".to_string(),
            id: Some(id),
            method: None,
            params: None,
            result: Some(result),
            error: None,
        }
    }

    /// Create an error response
    pub fn error_response(id: Option<serde_json::Value>, code: i32, message: &str, data: Option<serde_json::Value>) -> Self {
        Self {
            jsonrpc: "2.0".to_string(),
            id,
            method: None,
            params: None,
            result: None,
            error: Some(JsonRpcError {
                code,
                message: message.to_string(),
                data,
            }),
        }
    }
}

/// Error codes (JSON-RPC 2.0 standard + custom)
pub mod error_codes {
    pub const PARSE_ERROR: i32 = -32700;
    pub const INVALID_REQUEST: i32 = -32600;
    pub const METHOD_NOT_FOUND: i32 = -32601;
    pub const INVALID_PARAMS: i32 = -32602;
    pub const INTERNAL_ERROR: i32 = -32603;
    // Custom codes
    pub const PLAYBOOK_FAILED: i32 = -32000;
    pub const TIMEOUT: i32 = -32001;
    pub const UNAUTHORIZED: i32 = -32002;
    pub const PERMISSION_DENIED: i32 = -32003;
}

/// SSE sender channel
pub type SseSender = mpsc::UnboundedSender<JsonRpcMessage>;

/// WebSocket sender channel (Phase 2)
pub type WsSender = mpsc::UnboundedSender<JsonRpcMessage>;

/// Connection type enum
#[derive(Debug, Clone)]
pub enum ConnectionType {
    Sse(SseSender),
    #[allow(dead_code)]
    WebSocket(WsSender),
}

/// Client connection info
#[derive(Debug, Clone)]
pub struct ClientConnection {
    pub client_id: String,
    pub session_token: String,
    pub connection: ConnectionType,
    pub connected_at: chrono::DateTime<chrono::Utc>,
}

/// Connection hub for managing client connections
#[derive(Clone)]
pub struct ConnectionHub {
    /// All connections: client_id -> connection
    connections: Arc<RwLock<HashMap<String, ClientConnection>>>,
    /// Session to clients mapping (one session can have multiple clients/tabs)
    session_clients: Arc<RwLock<HashMap<String, HashSet<String>>>>,
}

impl ConnectionHub {
    pub fn new() -> Self {
        Self {
            connections: Arc::new(RwLock::new(HashMap::new())),
            session_clients: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Register a new SSE connection
    pub async fn register_sse(&self, client_id: String, session_token: String, sender: SseSender) {
        let connection = ClientConnection {
            client_id: client_id.clone(),
            session_token: session_token.clone(),
            connection: ConnectionType::Sse(sender),
            connected_at: chrono::Utc::now(),
        };

        // Add to connections map
        self.connections.write().await.insert(client_id.clone(), connection);

        // Add to session -> clients mapping
        self.session_clients
            .write()
            .await
            .entry(session_token.clone())
            .or_insert_with(HashSet::new)
            .insert(client_id.clone());

        tracing::info!(
            "SSE connection registered: client_id={}, session={}",
            &client_id[..8.min(client_id.len())],
            &session_token[..8.min(session_token.len())]
        );
    }

    /// Register a new WebSocket connection (Phase 2)
    #[allow(dead_code)]
    pub async fn register_ws(&self, client_id: String, session_token: String, sender: WsSender) {
        let connection = ClientConnection {
            client_id: client_id.clone(),
            session_token: session_token.clone(),
            connection: ConnectionType::WebSocket(sender),
            connected_at: chrono::Utc::now(),
        };

        self.connections.write().await.insert(client_id.clone(), connection);
        self.session_clients
            .write()
            .await
            .entry(session_token.clone())
            .or_insert_with(HashSet::new)
            .insert(client_id.clone());

        tracing::info!(
            "WebSocket connection registered: client_id={}, session={}",
            &client_id[..8.min(client_id.len())],
            &session_token[..8.min(session_token.len())]
        );
    }

    /// Unregister a connection (on disconnect)
    pub async fn unregister(&self, client_id: &str) {
        let mut connections = self.connections.write().await;
        if let Some(conn) = connections.remove(client_id) {
            // Remove from session mapping
            let mut session_clients = self.session_clients.write().await;
            if let Some(clients) = session_clients.get_mut(&conn.session_token) {
                clients.remove(client_id);
                if clients.is_empty() {
                    session_clients.remove(&conn.session_token);
                }
            }

            tracing::info!(
                "Connection unregistered: client_id={}, session={}",
                &client_id[..8.min(client_id.len())],
                &conn.session_token[..8.min(conn.session_token.len())]
            );
        }
    }

    /// Send message to specific client
    pub async fn send_to_client(&self, client_id: &str, message: JsonRpcMessage) -> anyhow::Result<bool> {
        let connections = self.connections.read().await;
        if let Some(conn) = connections.get(client_id) {
            match &conn.connection {
                ConnectionType::Sse(sender) => {
                    if sender.send(message).is_ok() {
                        tracing::debug!("Message sent to client: {}", &client_id[..8.min(client_id.len())]);
                        return Ok(true);
                    }
                }
                ConnectionType::WebSocket(sender) => {
                    if sender.send(message).is_ok() {
                        tracing::debug!("Message sent to client: {}", &client_id[..8.min(client_id.len())]);
                        return Ok(true);
                    }
                }
            }
        }
        Ok(false)
    }

    /// Send message to all clients of a session
    #[allow(dead_code)]
    pub async fn send_to_session(&self, session_token: &str, message: JsonRpcMessage) -> anyhow::Result<usize> {
        let session_clients = self.session_clients.read().await;
        let clients = match session_clients.get(session_token) {
            Some(c) => c.clone(),
            None => return Ok(0),
        };
        drop(session_clients);

        let mut sent = 0;
        for client_id in clients {
            if self.send_to_client(&client_id, message.clone()).await? {
                sent += 1;
            }
        }
        Ok(sent)
    }

    /// Check if client is connected
    pub async fn is_connected(&self, client_id: &str) -> bool {
        self.connections.read().await.contains_key(client_id)
    }

    /// Get all client_ids for a session
    #[allow(dead_code)]
    pub async fn get_session_clients(&self, session_token: &str) -> Vec<String> {
        self.session_clients
            .read()
            .await
            .get(session_token)
            .map(|c| c.iter().cloned().collect())
            .unwrap_or_default()
    }

    /// Get total connection count
    pub async fn connection_count(&self) -> usize {
        self.connections.read().await.len()
    }

    /// Broadcast ping to all connections (for keepalive)
    pub async fn broadcast_ping(&self) {
        let message = JsonRpcMessage::notification("ping", serde_json::json!({}));
        let connections = self.connections.read().await;

        for (client_id, conn) in connections.iter() {
            let result = match &conn.connection {
                ConnectionType::Sse(sender) => sender.send(message.clone()).is_ok(),
                ConnectionType::WebSocket(sender) => sender.send(message.clone()).is_ok(),
            };
            if !result {
                tracing::debug!("Ping failed for client: {}", &client_id[..8.min(client_id.len())]);
            }
        }
    }
}

impl Default for ConnectionHub {
    fn default() -> Self {
        Self::new()
    }
}
