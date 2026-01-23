//! Keychain API handlers.
//!
//! Endpoints for token/credential caching with scope support.

use axum::{
    extract::{Path, Query, State},
    Json,
};
use serde::Deserialize;

use crate::db::models::{
    KeychainDeleteResponse, KeychainGetResponse, KeychainListResponse, KeychainSetRequest,
    KeychainSetResponse,
};
use crate::error::AppResult;
use crate::services::KeychainService;

/// Query parameters for keychain operations.
#[derive(Debug, Deserialize, Default)]
pub struct KeychainQuery {
    /// Execution ID for local/shared scope
    pub execution_id: Option<i64>,

    /// Scope type: "local", "global", or "shared"
    #[serde(default = "default_scope")]
    pub scope_type: String,
}

fn default_scope() -> String {
    "global".to_string()
}

/// Get a keychain entry.
///
/// `GET /api/keychain/{catalog_id}/{keychain_name}`
///
/// # Path Parameters
///
/// - `catalog_id`: Catalog ID of the playbook
/// - `keychain_name`: Name of the keychain entry
///
/// # Query Parameters
///
/// - `execution_id`: Execution ID for local/shared scope
/// - `scope_type`: Scope type ("local", "global", "shared")
///
/// # Response
///
/// ```json
/// {
///   "status": "found",
///   "data": {"access_token": "..."},
///   "expires_at": "2025-01-01T01:00:00Z",
///   "auto_renew": true,
///   "access_count": 5
/// }
/// ```
pub async fn get(
    State(service): State<KeychainService>,
    Path((catalog_id, keychain_name)): Path<(i64, String)>,
    Query(query): Query<KeychainQuery>,
) -> AppResult<Json<KeychainGetResponse>> {
    let response = service
        .get(
            catalog_id,
            &keychain_name,
            query.execution_id,
            &query.scope_type,
        )
        .await?;
    Ok(Json(response))
}

/// Set a keychain entry.
///
/// `POST /api/keychain/{catalog_id}/{keychain_name}`
///
/// # Path Parameters
///
/// - `catalog_id`: Catalog ID of the playbook
/// - `keychain_name`: Name of the keychain entry
///
/// # Request Body
///
/// ```json
/// {
///   "data": {"access_token": "...", "refresh_token": "..."},
///   "scope_type": "global",
///   "expires_in": 3600,
///   "auto_renew": true,
///   "renew_config": {...}
/// }
/// ```
///
/// # Response
///
/// ```json
/// {
///   "status": "success",
///   "cache_key": "token:123456789:global",
///   "expires_at": "2025-01-01T01:00:00Z"
/// }
/// ```
pub async fn set(
    State(service): State<KeychainService>,
    Path((catalog_id, keychain_name)): Path<(i64, String)>,
    Json(request): Json<KeychainSetRequest>,
) -> AppResult<Json<KeychainSetResponse>> {
    let response = service.set(catalog_id, &keychain_name, request).await?;
    Ok(Json(response))
}

/// Delete a keychain entry.
///
/// `DELETE /api/keychain/{catalog_id}/{keychain_name}`
///
/// # Path Parameters
///
/// - `catalog_id`: Catalog ID of the playbook
/// - `keychain_name`: Name of the keychain entry
///
/// # Query Parameters
///
/// - `execution_id`: Execution ID for local/shared scope
/// - `scope_type`: Scope type ("local", "global", "shared")
///
/// # Response
///
/// ```json
/// {
///   "status": "deleted",
///   "cache_key": "token:123456789:global"
/// }
/// ```
pub async fn delete(
    State(service): State<KeychainService>,
    Path((catalog_id, keychain_name)): Path<(i64, String)>,
    Query(query): Query<KeychainQuery>,
) -> AppResult<Json<KeychainDeleteResponse>> {
    let response = service
        .delete(
            catalog_id,
            &keychain_name,
            query.execution_id,
            &query.scope_type,
        )
        .await?;
    Ok(Json(response))
}

/// List all keychain entries for a catalog.
///
/// `GET /api/keychain/catalog/{catalog_id}`
///
/// # Path Parameters
///
/// - `catalog_id`: Catalog ID of the playbook
///
/// # Response
///
/// ```json
/// {
///   "catalog_id": "123456789",
///   "entries": [
///     {
///       "keychain_name": "api_token",
///       "scope_type": "global",
///       "expires_at": "2025-01-01T01:00:00Z",
///       "expired": false,
///       "access_count": 5
///     }
///   ]
/// }
/// ```
pub async fn list_by_catalog(
    State(service): State<KeychainService>,
    Path(catalog_id): Path<i64>,
) -> AppResult<Json<KeychainListResponse>> {
    let response = service.list_by_catalog(catalog_id).await?;
    Ok(Json(response))
}
