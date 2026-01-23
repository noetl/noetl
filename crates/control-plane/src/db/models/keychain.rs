//! Keychain database model.
//!
//! The keychain provides token/credential caching with scope support
//! (local, shared, global) for playbook executions.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

/// Keychain entry for cached tokens/credentials.
#[derive(Debug, Clone, FromRow)]
pub struct KeychainEntry {
    /// Unique keychain entry ID
    pub id: i64,

    /// Cache key (format: {keychain_name}:{catalog_id}:{scope_suffix})
    pub cache_key: String,

    /// Catalog ID
    pub catalog_id: i64,

    /// Keychain name
    pub keychain_name: String,

    /// Scope type (local, shared, global)
    pub scope_type: String,

    /// Execution ID (for local/shared scope)
    #[sqlx(default)]
    pub execution_id: Option<i64>,

    /// Encrypted token/credential data
    pub data: Vec<u8>,

    /// Token expiry time
    #[sqlx(default)]
    pub expires_at: Option<DateTime<Utc>>,

    /// Auto-renewal enabled
    #[sqlx(default)]
    pub auto_renew: bool,

    /// Renewal configuration (JSON)
    #[sqlx(default)]
    pub renew_config: Option<serde_json::Value>,

    /// Access count
    #[sqlx(default)]
    pub access_count: i32,

    /// Last accessed timestamp
    #[sqlx(default)]
    pub accessed_at: Option<DateTime<Utc>>,

    /// Creation timestamp
    pub created_at: DateTime<Utc>,

    /// Last update timestamp
    pub updated_at: DateTime<Utc>,
}

/// Request to set a keychain entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeychainSetRequest {
    /// Token/credential data
    pub data: serde_json::Value,

    /// Scope type (local, shared, global)
    #[serde(default = "default_scope")]
    pub scope_type: String,

    /// Execution ID (required for local/shared scope)
    #[serde(default)]
    pub execution_id: Option<i64>,

    /// Token expiry time
    #[serde(default)]
    pub expires_at: Option<DateTime<Utc>>,

    /// Expiry in seconds from now
    #[serde(default)]
    pub expires_in: Option<i64>,

    /// Enable auto-renewal
    #[serde(default)]
    pub auto_renew: bool,

    /// Renewal configuration
    #[serde(default)]
    pub renew_config: Option<serde_json::Value>,
}

fn default_scope() -> String {
    "global".to_string()
}

/// Response after setting a keychain entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeychainSetResponse {
    /// Operation status
    pub status: String,

    /// Cache key
    pub cache_key: String,

    /// Expiry time
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<DateTime<Utc>>,
}

/// Response when getting a keychain entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeychainGetResponse {
    /// Operation status (found, expired, not_found)
    pub status: String,

    /// Token/credential data
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<serde_json::Value>,

    /// Expiry time
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<DateTime<Utc>>,

    /// Auto-renewal enabled
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auto_renew: Option<bool>,

    /// Access count
    #[serde(skip_serializing_if = "Option::is_none")]
    pub access_count: Option<i32>,
}

/// Response after deleting a keychain entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeychainDeleteResponse {
    /// Operation status
    pub status: String,

    /// Deleted cache key
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cache_key: Option<String>,
}

/// Response listing keychain entries for a catalog.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeychainListResponse {
    /// Catalog ID
    pub catalog_id: String,

    /// List of keychain entries
    pub entries: Vec<KeychainEntrySummary>,
}

/// Summary of a keychain entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeychainEntrySummary {
    /// Keychain name
    pub keychain_name: String,

    /// Scope type
    pub scope_type: String,

    /// Execution ID (if applicable)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub execution_id: Option<String>,

    /// Expiry time
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<DateTime<Utc>>,

    /// Whether expired
    pub expired: bool,

    /// Access count
    pub access_count: i32,

    /// Last accessed time
    #[serde(skip_serializing_if = "Option::is_none")]
    pub accessed_at: Option<DateTime<Utc>>,

    /// Creation time
    pub created_at: DateTime<Utc>,
}
