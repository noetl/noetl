//! Catalog database model.
//!
//! The catalog stores registered playbooks, tools, and other resources
//! with version control support.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

/// Catalog entry representing a registered resource.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct CatalogEntry {
    /// Unique catalog ID (snowflake-like ID)
    pub id: i64,

    /// Resource path (e.g., "tests/fixtures/playbooks/hello_world")
    pub path: String,

    /// Resource kind (e.g., "Playbook", "Tool", "Model")
    pub kind: String,

    /// Version number (auto-incremented per path)
    pub version: i32,

    /// Raw YAML content
    pub content: String,

    /// Parsed layout/structure (JSON)
    #[sqlx(default)]
    pub layout: Option<serde_json::Value>,

    /// Parsed payload/workload (JSON)
    #[sqlx(default)]
    pub payload: Option<serde_json::Value>,

    /// Additional metadata (JSON)
    #[sqlx(default)]
    pub meta: Option<serde_json::Value>,

    /// Creation timestamp
    pub created_at: DateTime<Utc>,
}

/// Request to register a new catalog resource.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CatalogRegisterRequest {
    /// YAML content (plain text or base64 encoded)
    pub content: String,

    /// Resource type (default: "Playbook")
    #[serde(default = "default_resource_type")]
    pub resource_type: String,
}

fn default_resource_type() -> String {
    "Playbook".to_string()
}

/// Response after registering a catalog resource.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CatalogRegisterResponse {
    /// Operation status
    pub status: String,

    /// Status message
    pub message: String,

    /// Resource path
    pub path: String,

    /// Version number
    pub version: i32,

    /// Catalog ID
    pub catalog_id: String,

    /// Resource kind
    pub kind: String,
}

/// Request to list catalog entries.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct CatalogEntriesRequest {
    /// Filter by resource type
    #[serde(default)]
    pub resource_type: Option<String>,
}

/// Response containing list of catalog entries.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CatalogEntries {
    /// List of catalog entries
    pub entries: Vec<CatalogEntryResponse>,
}

/// Catalog entry response (subset of fields).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CatalogEntryResponse {
    /// Catalog ID
    pub catalog_id: String,

    /// Resource path
    pub path: String,

    /// Resource kind
    pub kind: String,

    /// Version number
    pub version: i32,

    /// Raw YAML content
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,

    /// Parsed payload/workload (JSON)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub payload: Option<serde_json::Value>,

    /// Additional metadata (JSON)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub meta: Option<serde_json::Value>,

    /// Creation timestamp
    pub created_at: DateTime<Utc>,
}

impl From<CatalogEntry> for CatalogEntryResponse {
    fn from(entry: CatalogEntry) -> Self {
        Self {
            catalog_id: entry.id.to_string(),
            path: entry.path,
            kind: entry.kind,
            version: entry.version,
            content: Some(entry.content),
            payload: entry.payload,
            meta: entry.meta,
            created_at: entry.created_at,
        }
    }
}

/// Request to get a specific catalog resource.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct CatalogEntryRequest {
    /// Direct catalog entry ID
    #[serde(default)]
    pub catalog_id: Option<String>,

    /// Resource path
    #[serde(default)]
    pub path: Option<String>,

    /// Version identifier (number or "latest")
    #[serde(default)]
    pub version: Option<String>,
}
