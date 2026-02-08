//! Server-Sent Events (SSE) endpoint for real-time playbook callbacks.
//!
//! Clients connect to GET /events with their session token to receive
//! playbook execution results in real-time via SSE.

use axum::{
    extract::{Query, State},
    response::{
        sse::{Event, Sse},
        IntoResponse,
    },
};
use futures::stream::Stream;
use serde::{Deserialize, Serialize};
use std::convert::Infallible;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::mpsc;
use tokio_stream::wrappers::UnboundedReceiverStream;
use tokio_stream::StreamExt;
use uuid::Uuid;

use crate::connection_hub::{ConnectionHub, JsonRpcMessage, SseSender};
use crate::request_store::{PendingRequest, RequestStore};
use crate::session_cache::SessionCache;

/// SSE connection query parameters
#[derive(Debug, Deserialize)]
pub struct SseParams {
    /// Session token for authentication
    pub session_token: String,
    /// Optional client_id for reconnection
    pub client_id: Option<String>,
}

/// SSE app state
pub struct SseState {
    pub connection_hub: Arc<ConnectionHub>,
    pub request_store: Arc<RequestStore>,
    pub session_cache: Arc<SessionCache>,
    pub heartbeat_interval_secs: u64,
}

/// Initialization response data
#[derive(Serialize)]
struct InitResponse {
    #[serde(rename = "protocolVersion")]
    protocol_version: String,
    #[serde(rename = "serverInfo")]
    server_info: ServerInfo,
    #[serde(rename = "clientId")]
    client_id: String,
    capabilities: Capabilities,
    #[serde(rename = "pendingRequests", skip_serializing_if = "Option::is_none")]
    pending_requests: Option<Vec<PendingRequestInfo>>,
}

#[derive(Serialize)]
struct ServerInfo {
    name: String,
    version: String,
}

#[derive(Serialize)]
struct Capabilities {
    playbooks: bool,
    callbacks: bool,
}

#[derive(Serialize)]
struct PendingRequestInfo {
    #[serde(rename = "requestId")]
    request_id: String,
    #[serde(rename = "executionId")]
    execution_id: String,
    #[serde(rename = "playbookPath")]
    playbook_path: String,
}

/// SSE endpoint handler
///
/// GET /events?session_token=xxx&client_id=yyy
///
/// Returns Server-Sent Events stream with JSON-RPC 2.0 messages
pub async fn sse_handler(
    State(state): State<Arc<SseState>>,
    Query(params): Query<SseParams>,
) -> axum::response::Response {
    use axum::response::IntoResponse;

    // Validate session token
    let session = match state.session_cache.get(&params.session_token).await {
        Some(s) if s.is_active => s,
        _ => {
            // Return error as SSE event then close
            let error_msg = JsonRpcMessage::error_response(
                None,
                crate::connection_hub::error_codes::UNAUTHORIZED,
                "Invalid or expired session",
                None,
            );
            let event = Event::default()
                .event("error")
                .data(serde_json::to_string(&error_msg).unwrap_or_default());

            let error_stream = futures::stream::once(async move { Ok::<_, Infallible>(event) });
            return Sse::new(error_stream)
                .keep_alive(axum::response::sse::KeepAlive::new())
                .into_response();
        }
    };

    // Generate or reuse client_id
    let client_id = params.client_id.unwrap_or_else(|| Uuid::new_v4().to_string());

    // Create channel for sending events to client
    let (tx, rx): (SseSender, mpsc::UnboundedReceiver<JsonRpcMessage>) = mpsc::unbounded_channel();

    // Register connection
    state
        .connection_hub
        .register_sse(client_id.clone(), params.session_token.clone(), tx.clone())
        .await;

    // Get pending requests for reconnection recovery
    let pending_requests = if state.request_store.is_connected().await {
        let requests = state.request_store.get_by_client(&client_id).await;
        if requests.is_empty() {
            None
        } else {
            Some(
                requests
                    .into_iter()
                    .map(|(request_id, req)| PendingRequestInfo {
                        request_id,
                        execution_id: req.execution_id,
                        playbook_path: req.playbook_path,
                    })
                    .collect(),
            )
        }
    } else {
        None
    };

    // Send initialization message
    let init_response = InitResponse {
        protocol_version: "2024-11-05".to_string(),
        server_info: ServerInfo {
            name: "noetl-gateway".to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
        },
        client_id: client_id.clone(),
        capabilities: Capabilities {
            playbooks: true,
            callbacks: true,
        },
        pending_requests,
    };

    let init_msg = JsonRpcMessage::response(
        serde_json::json!(1),
        serde_json::to_value(init_response).unwrap_or_default(),
    );

    let _ = tx.send(init_msg);

    tracing::info!(
        "SSE connection established: client_id={}, user={}",
        &client_id[..8.min(client_id.len())],
        session.email
    );

    // Create stream from receiver
    let message_stream = UnboundedReceiverStream::new(rx);

    // Clone for cleanup
    let hub = state.connection_hub.clone();
    let client_id_for_cleanup = client_id.clone();
    let heartbeat_interval = state.heartbeat_interval_secs;

    // Create heartbeat stream
    let heartbeat_stream = async_stream::stream! {
        let mut interval = tokio::time::interval(Duration::from_secs(heartbeat_interval));
        loop {
            interval.tick().await;
            let ping = JsonRpcMessage::notification("ping", serde_json::json!({}));
            yield ping;
        }
    };

    // Merge message stream with heartbeat
    let combined_stream = futures::stream::select(
        message_stream,
        Box::pin(heartbeat_stream) as std::pin::Pin<Box<dyn Stream<Item = JsonRpcMessage> + Send>>,
    );

    // Map to SSE events
    let event_stream = combined_stream.map(move |msg| {
        let event_type = msg.method.as_deref().unwrap_or("message");
        let data = serde_json::to_string(&msg).unwrap_or_default();
        Ok::<_, Infallible>(Event::default().event(event_type).data(data))
    });

    // Wrap in a stream that cleans up on drop
    let cleanup_stream = CleanupStream {
        inner: Box::pin(event_stream),
        hub,
        client_id: client_id_for_cleanup,
        cleaned_up: false,
    };

    Sse::new(cleanup_stream)
        .keep_alive(
            axum::response::sse::KeepAlive::new()
                .interval(Duration::from_secs(15))
                .text("ping"),
        )
        .into_response()
}

/// Stream wrapper that cleans up connection on drop
struct CleanupStream<S> {
    inner: std::pin::Pin<Box<S>>,
    hub: Arc<ConnectionHub>,
    client_id: String,
    cleaned_up: bool,
}

impl<S: Stream<Item = Result<Event, Infallible>> + Send> Stream for CleanupStream<S> {
    type Item = Result<Event, Infallible>;

    fn poll_next(
        mut self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<Option<Self::Item>> {
        self.inner.as_mut().poll_next(cx)
    }
}

impl<S> Drop for CleanupStream<S> {
    fn drop(&mut self) {
        if !self.cleaned_up {
            self.cleaned_up = true;
            let hub = self.hub.clone();
            let client_id = self.client_id.clone();
            tokio::spawn(async move {
                hub.unregister(&client_id).await;
                tracing::info!(
                    "SSE connection closed: client_id={}",
                    &client_id[..8.min(client_id.len())]
                );
            });
        }
    }
}

/// Worker callback request (received from playbooks)
#[derive(Debug, Deserialize)]
pub struct WorkerCallback {
    pub request_id: String,
    #[serde(default)]
    pub execution_id: Option<String>,
    #[serde(default = "default_status")]
    pub status: String,
    #[serde(default)]
    pub data: serde_json::Value,
    #[serde(default)]
    pub error: Option<WorkerCallbackError>,
}

fn default_status() -> String {
    "COMPLETED".to_string()
}

#[derive(Debug, Deserialize, Serialize)]
pub struct WorkerCallbackError {
    pub code: Option<i32>,
    pub message: String,
    #[serde(default)]
    pub data: Option<serde_json::Value>,
}

/// Internal callback handler
///
/// POST /api/internal/callback
///
/// Receives playbook results from workers and routes to connected clients
pub async fn callback_handler(
    State(state): State<Arc<SseState>>,
    axum::Json(callback): axum::Json<WorkerCallback>,
) -> impl IntoResponse {
    tracing::info!(
        "Callback received: request_id={}, status={}",
        &callback.request_id[..8.min(callback.request_id.len())],
        callback.status
    );

    // Look up the pending request
    let pending_request = match state.request_store.get(&callback.request_id).await {
        Some(req) => req,
        None => {
            tracing::warn!(
                "Callback for unknown request_id: {}",
                &callback.request_id[..8.min(callback.request_id.len())]
            );
            return (
                axum::http::StatusCode::NOT_FOUND,
                axum::Json(serde_json::json!({"error": "Request not found"})),
            );
        }
    };

    // Build the JSON-RPC notification
    let message = if callback.status == "FAILED" || callback.error.is_some() {
        let error = callback.error.unwrap_or(WorkerCallbackError {
            code: Some(crate::connection_hub::error_codes::PLAYBOOK_FAILED),
            message: "Playbook execution failed".to_string(),
            data: None,
        });

        JsonRpcMessage::notification(
            "playbook/result",
            serde_json::json!({
                "requestId": callback.request_id,
                "executionId": callback.execution_id.unwrap_or(pending_request.execution_id),
                "status": "FAILED",
                "error": {
                    "code": error.code.unwrap_or(crate::connection_hub::error_codes::PLAYBOOK_FAILED),
                    "message": error.message,
                    "data": error.data
                }
            }),
        )
    } else {
        JsonRpcMessage::notification(
            "playbook/result",
            serde_json::json!({
                "requestId": callback.request_id,
                "executionId": callback.execution_id.unwrap_or(pending_request.execution_id),
                "status": callback.status,
                "data": callback.data
            }),
        )
    };

    // Send to client
    let sent = state
        .connection_hub
        .send_to_client(&pending_request.client_id, message)
        .await
        .unwrap_or(false);

    if sent {
        tracing::info!(
            "Callback delivered to client: request_id={}, client_id={}",
            &callback.request_id[..8.min(callback.request_id.len())],
            &pending_request.client_id[..8.min(pending_request.client_id.len())]
        );
    } else {
        tracing::warn!(
            "Client not connected for callback: request_id={}, client_id={}",
            &callback.request_id[..8.min(callback.request_id.len())],
            &pending_request.client_id[..8.min(pending_request.client_id.len())]
        );
        // Don't remove the request - client might reconnect
        return (
            axum::http::StatusCode::ACCEPTED,
            axum::Json(serde_json::json!({"status": "queued", "clientDisconnected": true})),
        );
    }

    // Remove the request from store
    let _ = state.request_store.remove(&callback.request_id).await;

    (
        axum::http::StatusCode::OK,
        axum::Json(serde_json::json!({"status": "delivered"})),
    )
}

/// Progress notification handler (optional)
///
/// POST /api/internal/progress
///
/// Receives progress updates from workers
pub async fn progress_handler(
    State(state): State<Arc<SseState>>,
    axum::Json(progress): axum::Json<ProgressUpdate>,
) -> impl IntoResponse {
    // Look up the pending request
    let pending_request = match state.request_store.get(&progress.request_id).await {
        Some(req) => req,
        None => {
            return (
                axum::http::StatusCode::NOT_FOUND,
                axum::Json(serde_json::json!({"error": "Request not found"})),
            );
        }
    };

    // Build progress notification
    let message = JsonRpcMessage::notification(
        "playbook/progress",
        serde_json::json!({
            "requestId": progress.request_id,
            "executionId": progress.execution_id.unwrap_or(pending_request.execution_id),
            "step": progress.step,
            "message": progress.message,
            "progress": progress.progress
        }),
    );

    // Send to client
    let _ = state
        .connection_hub
        .send_to_client(&pending_request.client_id, message)
        .await;

    (
        axum::http::StatusCode::OK,
        axum::Json(serde_json::json!({"status": "sent"})),
    )
}

#[derive(Debug, Deserialize)]
pub struct ProgressUpdate {
    pub request_id: String,
    #[serde(default)]
    pub execution_id: Option<String>,
    #[serde(default)]
    pub step: Option<String>,
    #[serde(default)]
    pub message: Option<String>,
    #[serde(default)]
    pub progress: Option<f32>,
}
