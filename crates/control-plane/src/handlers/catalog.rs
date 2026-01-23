//! Catalog API handlers.
//!
//! Endpoints for managing playbooks, tools, and other resources
//! in the NoETL catalog.

use axum::{extract::State, http::StatusCode, Json};

use crate::db::models::{
    CatalogEntries, CatalogEntriesRequest, CatalogEntryRequest, CatalogEntryResponse,
    CatalogRegisterRequest, CatalogRegisterResponse,
};
use crate::error::AppResult;
use crate::services::CatalogService;

/// Register a new catalog resource.
///
/// `POST /api/catalog/register`
///
/// # Request Body
///
/// ```json
/// {
///   "content": "apiVersion: noetl.io/v1\nkind: Playbook\n...",
///   "resource_type": "Playbook"
/// }
/// ```
///
/// # Response
///
/// ```json
/// {
///   "status": "success",
///   "message": "Resource 'path/to/playbook' version '1' registered.",
///   "path": "path/to/playbook",
///   "version": 1,
///   "catalog_id": "123456789",
///   "kind": "Playbook"
/// }
/// ```
pub async fn register(
    State(service): State<CatalogService>,
    Json(request): Json<CatalogRegisterRequest>,
) -> AppResult<(StatusCode, Json<CatalogRegisterResponse>)> {
    let response = service.register(request).await?;
    Ok((StatusCode::OK, Json(response)))
}

/// List all catalog resources.
///
/// `POST /api/catalog/list`
///
/// # Request Body
///
/// ```json
/// {
///   "resource_type": "Playbook"  // optional filter
/// }
/// ```
///
/// # Response
///
/// ```json
/// {
///   "entries": [
///     {
///       "catalog_id": "123456789",
///       "path": "path/to/playbook",
///       "kind": "Playbook",
///       "version": 1,
///       "created_at": "2025-01-01T00:00:00Z"
///     }
///   ]
/// }
/// ```
pub async fn list(
    State(service): State<CatalogService>,
    Json(request): Json<CatalogEntriesRequest>,
) -> AppResult<Json<CatalogEntries>> {
    let entries = service.list(request.resource_type.as_deref()).await?;
    Ok(Json(entries))
}

/// Get a specific catalog resource.
///
/// `POST /api/catalog/resource`
///
/// # Request Body
///
/// Lookup by catalog_id:
/// ```json
/// {
///   "catalog_id": "123456789"
/// }
/// ```
///
/// Lookup by path and version:
/// ```json
/// {
///   "path": "path/to/playbook",
///   "version": "latest"
/// }
/// ```
///
/// # Response
///
/// ```json
/// {
///   "catalog_id": "123456789",
///   "path": "path/to/playbook",
///   "kind": "Playbook",
///   "version": 1,
///   "content": "apiVersion: noetl.io/v1...",
///   "created_at": "2025-01-01T00:00:00Z"
/// }
/// ```
pub async fn get_resource(
    State(service): State<CatalogService>,
    Json(request): Json<CatalogEntryRequest>,
) -> AppResult<Json<CatalogEntryResponse>> {
    let entry = service.get_resource(request).await?;
    Ok(Json(entry.into()))
}
