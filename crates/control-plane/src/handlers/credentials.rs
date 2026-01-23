//! Credential API handlers.
//!
//! Endpoints for managing encrypted credentials.

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::Deserialize;

use crate::db::models::{CredentialCreateRequest, CredentialListResponse, CredentialResponse};
use crate::error::AppResult;
use crate::services::CredentialService;

/// Query parameters for listing credentials.
#[derive(Debug, Deserialize, Default)]
pub struct ListCredentialsQuery {
    /// Filter by credential type
    #[serde(rename = "type")]
    pub credential_type: Option<String>,

    /// Free-text search
    pub q: Option<String>,
}

/// Query parameters for getting a credential.
#[derive(Debug, Deserialize, Default)]
pub struct GetCredentialQuery {
    /// Include decrypted data in response
    #[serde(default)]
    pub include_data: bool,

    /// Execution ID (for audit logging)
    pub execution_id: Option<i64>,

    /// Parent execution ID (for audit logging)
    pub parent_execution_id: Option<i64>,
}

/// Create or update a credential.
///
/// `POST /api/credentials`
///
/// # Request Body
///
/// ```json
/// {
///   "name": "my-database-creds",
///   "type": "postgres",
///   "data": {
///     "username": "admin",
///     "password": "secret123",
///     "host": "db.example.com"
///   },
///   "meta": {"environment": "production"},
///   "tags": ["database", "production"],
///   "description": "Production database credentials"
/// }
/// ```
///
/// # Response
///
/// ```json
/// {
///   "id": "123456789",
///   "name": "my-database-creds",
///   "type": "postgres",
///   "created_at": "2025-01-01T00:00:00Z",
///   "updated_at": "2025-01-01T00:00:00Z"
/// }
/// ```
pub async fn create_or_update(
    State(service): State<CredentialService>,
    Json(request): Json<CredentialCreateRequest>,
) -> AppResult<(StatusCode, Json<CredentialResponse>)> {
    let response = service.create_or_update(request).await?;
    Ok((StatusCode::OK, Json(response)))
}

/// List credentials with optional filtering.
///
/// `GET /api/credentials`
///
/// # Query Parameters
///
/// - `type`: Filter by credential type
/// - `q`: Free-text search on name and description
///
/// # Response
///
/// ```json
/// {
///   "items": [...],
///   "filter": {"type": "postgres", "q": "production"}
/// }
/// ```
pub async fn list(
    State(service): State<CredentialService>,
    Query(query): Query<ListCredentialsQuery>,
) -> AppResult<Json<CredentialListResponse>> {
    let response = service
        .list(query.credential_type.as_deref(), query.q.as_deref())
        .await?;
    Ok(Json(response))
}

/// Get a credential by ID or name.
///
/// `GET /api/credentials/{identifier}`
///
/// # Path Parameters
///
/// - `identifier`: Credential ID (numeric) or name (string)
///
/// # Query Parameters
///
/// - `include_data`: If true, includes decrypted credential data
///
/// # Response
///
/// ```json
/// {
///   "id": "123456789",
///   "name": "my-database-creds",
///   "type": "postgres",
///   "data": {...},  // only if include_data=true
///   "created_at": "2025-01-01T00:00:00Z"
/// }
/// ```
pub async fn get(
    State(service): State<CredentialService>,
    Path(identifier): Path<String>,
    Query(query): Query<GetCredentialQuery>,
) -> AppResult<Json<CredentialResponse>> {
    let response = service.get(&identifier, query.include_data).await?;
    Ok(Json(response))
}

/// Delete a credential.
///
/// `DELETE /api/credentials/{identifier}`
///
/// # Path Parameters
///
/// - `identifier`: Credential ID (numeric) or name (string)
///
/// # Response
///
/// ```json
/// {
///   "message": "Credential deleted successfully",
///   "id": "123456789"
/// }
/// ```
pub async fn delete(
    State(service): State<CredentialService>,
    Path(identifier): Path<String>,
) -> AppResult<Json<serde_json::Value>> {
    let id = service.delete(&identifier).await?;
    Ok(Json(serde_json::json!({
        "message": "Credential deleted successfully",
        "id": id
    })))
}
