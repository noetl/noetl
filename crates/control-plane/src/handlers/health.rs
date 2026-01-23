//! Health check endpoints for the NoETL Control Plane API.

use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};

use crate::db::pool::health_check as db_health_check;
use crate::state::AppState;

/// Health check response.
#[derive(Debug, Serialize, Deserialize)]
pub struct HealthCheckResponse {
    /// Health status ("ok" or "unhealthy")
    pub status: String,
}

/// Detailed health check response for the API.
#[derive(Debug, Serialize, Deserialize)]
pub struct ApiHealthResponse {
    /// Overall health status
    pub status: String,

    /// Database connectivity status
    #[serde(skip_serializing_if = "Option::is_none")]
    pub database: Option<String>,

    /// NATS connectivity status
    #[serde(skip_serializing_if = "Option::is_none")]
    pub nats: Option<String>,

    /// Server uptime in seconds
    #[serde(skip_serializing_if = "Option::is_none")]
    pub uptime_seconds: Option<u64>,

    /// Server version
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
}

/// Basic health check endpoint.
///
/// `GET /health`
///
/// Returns a simple health status. This endpoint is suitable for
/// load balancer health checks as it returns quickly.
///
/// # Returns
///
/// - `200 OK` with `{"status": "ok"}` if the server is running
pub async fn health_check() -> Json<HealthCheckResponse> {
    Json(HealthCheckResponse {
        status: "ok".to_string(),
    })
}

/// Detailed API health check endpoint.
///
/// `GET /api/health`
///
/// Returns detailed health status including database and NATS connectivity.
///
/// # Arguments
///
/// * `state` - Application state containing database pool and NATS client
///
/// # Returns
///
/// - `200 OK` with detailed health status if all services are healthy
/// - `503 Service Unavailable` if any critical service is unhealthy
pub async fn api_health(State(state): State<AppState>) -> (StatusCode, Json<ApiHealthResponse>) {
    let db_healthy = db_health_check(&state.db).await;

    let nats_status = if state.has_nats() {
        Some("connected".to_string())
    } else {
        Some("not_configured".to_string())
    };

    let overall_status = if db_healthy {
        "ok".to_string()
    } else {
        "unhealthy".to_string()
    };

    let status_code = if db_healthy {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };

    let response = ApiHealthResponse {
        status: overall_status,
        database: Some(if db_healthy {
            "connected".to_string()
        } else {
            "disconnected".to_string()
        }),
        nats: nats_status,
        uptime_seconds: Some(state.uptime_seconds()),
        version: Some(env!("CARGO_PKG_VERSION").to_string()),
    };

    (status_code, Json(response))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_health_check() {
        let response = health_check().await;
        assert_eq!(response.status, "ok");
    }
}
