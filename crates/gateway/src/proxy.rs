//! Transparent proxy module for forwarding authenticated requests to NoETL server.
//!
//! This module provides a catch-all proxy that forwards any authenticated request
//! to the underlying NoETL API server. This means:
//!
//! 1. Gateway only handles authentication
//! 2. All NoETL API functionality is available through the proxy
//! 3. No gateway changes needed when NoETL adds new APIs
//!
//! Usage:
//! - `/noetl/*path` - Forwards to `{NOETL_BASE_URL}/api/*path`
//! - Requires valid session token in Authorization header

use axum::{
    body::Body,
    extract::{Path, State},
    http::{header, Method, Request, Response, StatusCode},
    response::IntoResponse,
};
use std::sync::Arc;

use crate::noetl_client::NoetlClient;

/// Shared state for proxy handlers.
#[derive(Clone)]
pub struct ProxyState {
    pub noetl_base_url: String,
    pub http_client: reqwest::Client,
}

impl ProxyState {
    pub fn new(noetl_base_url: String) -> Self {
        Self {
            noetl_base_url,
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(300)) // 5 min timeout for long operations
                .build()
                .unwrap_or_default(),
        }
    }
}

/// Proxy handler for GET requests.
pub async fn proxy_get(
    State(state): State<Arc<ProxyState>>,
    Path(path): Path<String>,
    req: Request<Body>,
) -> impl IntoResponse {
    proxy_request(state, &path, Method::GET, req).await
}

/// Proxy handler for POST requests.
pub async fn proxy_post(
    State(state): State<Arc<ProxyState>>,
    Path(path): Path<String>,
    req: Request<Body>,
) -> impl IntoResponse {
    proxy_request(state, &path, Method::POST, req).await
}

/// Proxy handler for PUT requests.
pub async fn proxy_put(
    State(state): State<Arc<ProxyState>>,
    Path(path): Path<String>,
    req: Request<Body>,
) -> impl IntoResponse {
    proxy_request(state, &path, Method::PUT, req).await
}

/// Proxy handler for DELETE requests.
pub async fn proxy_delete(
    State(state): State<Arc<ProxyState>>,
    Path(path): Path<String>,
    req: Request<Body>,
) -> impl IntoResponse {
    proxy_request(state, &path, Method::DELETE, req).await
}

/// Proxy handler for PATCH requests.
pub async fn proxy_patch(
    State(state): State<Arc<ProxyState>>,
    Path(path): Path<String>,
    req: Request<Body>,
) -> impl IntoResponse {
    proxy_request(state, &path, Method::PATCH, req).await
}

/// Core proxy logic that forwards requests to NoETL server.
async fn proxy_request(
    state: Arc<ProxyState>,
    path: &str,
    method: Method,
    req: Request<Body>,
) -> Response<Body> {
    // Build target URL
    let base = state.noetl_base_url.trim_end_matches('/');
    let target_url = format!("{}/api/{}", base, path);

    // Get query string if present
    let query = req.uri().query().map(|q| format!("?{}", q)).unwrap_or_default();
    let full_url = format!("{}{}", target_url, query);

    tracing::debug!(target_url = %full_url, method = %method, "Proxying request to NoETL");

    // Build the proxied request
    let mut proxy_req = match method {
        Method::GET => state.http_client.get(&full_url),
        Method::POST => state.http_client.post(&full_url),
        Method::PUT => state.http_client.put(&full_url),
        Method::DELETE => state.http_client.delete(&full_url),
        Method::PATCH => state.http_client.patch(&full_url),
        _ => {
            return Response::builder()
                .status(StatusCode::METHOD_NOT_ALLOWED)
                .body(Body::from("Method not allowed"))
                .unwrap();
        }
    };

    // Forward Content-Type header
    if let Some(content_type) = req.headers().get(header::CONTENT_TYPE) {
        if let Ok(ct) = content_type.to_str() {
            proxy_req = proxy_req.header(header::CONTENT_TYPE, ct);
        }
    }

    // Forward Accept header
    if let Some(accept) = req.headers().get(header::ACCEPT) {
        if let Ok(a) = accept.to_str() {
            proxy_req = proxy_req.header(header::ACCEPT, a);
        }
    }

    // Forward custom headers that might be needed
    for (name, value) in req.headers() {
        let name_str = name.as_str().to_lowercase();
        // Forward x-* headers (custom headers from client)
        if name_str.starts_with("x-") {
            if let Ok(v) = value.to_str() {
                proxy_req = proxy_req.header(name.as_str(), v);
            }
        }
    }

    // Get request body for non-GET methods
    let body_bytes = match method {
        Method::GET | Method::DELETE => vec![],
        _ => {
            match axum::body::to_bytes(req.into_body(), 10 * 1024 * 1024).await {
                Ok(bytes) => bytes.to_vec(),
                Err(e) => {
                    tracing::error!("Failed to read request body: {}", e);
                    return Response::builder()
                        .status(StatusCode::BAD_REQUEST)
                        .body(Body::from("Failed to read request body"))
                        .unwrap();
                }
            }
        }
    };

    if !body_bytes.is_empty() {
        // Log request body for debugging
        if let Ok(body_str) = std::str::from_utf8(&body_bytes) {
            tracing::debug!(path = %path, body = %body_str, "Proxying request body to NoETL");
        }
        proxy_req = proxy_req.body(body_bytes);
    }

    // Send the request
    let proxy_response = match proxy_req.send().await {
        Ok(resp) => resp,
        Err(e) => {
            tracing::error!("Proxy request failed: {}", e);
            return Response::builder()
                .status(StatusCode::BAD_GATEWAY)
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(format!(r#"{{"error": "Proxy request failed: {}"}}"#, e)))
                .unwrap();
        }
    };

    // Build response
    let status = proxy_response.status();
    let mut response_builder = Response::builder().status(status);

    // Forward response headers
    for (name, value) in proxy_response.headers() {
        let name_str = name.as_str().to_lowercase();
        // Forward content-type, content-length, and custom headers
        if name_str == "content-type"
            || name_str == "content-length"
            || name_str.starts_with("x-")
        {
            if let Ok(v) = value.to_str() {
                response_builder = response_builder.header(name.as_str(), v);
            }
        }
    }

    // Get response body
    match proxy_response.bytes().await {
        Ok(bytes) => {
            response_builder
                .body(Body::from(bytes.to_vec()))
                .unwrap_or_else(|_| {
                    Response::builder()
                        .status(StatusCode::INTERNAL_SERVER_ERROR)
                        .body(Body::from("Failed to build response"))
                        .unwrap()
                })
        }
        Err(e) => {
            tracing::error!("Failed to read proxy response: {}", e);
            Response::builder()
                .status(StatusCode::BAD_GATEWAY)
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(format!(r#"{{"error": "Failed to read response: {}"}}"#, e)))
                .unwrap()
        }
    }
}
