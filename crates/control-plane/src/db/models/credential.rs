//! Credential database model.
//!
//! Credentials are stored encrypted at rest using AES-GCM encryption.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

/// Credential entry with encrypted data.
#[derive(Debug, Clone, FromRow)]
pub struct CredentialEntry {
    /// Unique credential ID
    pub id: i64,

    /// Credential name (unique identifier)
    pub name: String,

    /// Credential type (e.g., "postgres", "httpBearerAuth", "oauth2")
    #[sqlx(rename = "type")]
    pub credential_type: String,

    /// Encrypted credential data (JSON)
    pub data: Vec<u8>,

    /// Additional metadata (JSON)
    #[sqlx(default)]
    pub meta: Option<serde_json::Value>,

    /// Tags for categorization
    #[sqlx(default)]
    pub tags: Option<Vec<String>>,

    /// Description
    #[sqlx(default)]
    pub description: Option<String>,

    /// Creation timestamp
    pub created_at: DateTime<Utc>,

    /// Last update timestamp
    pub updated_at: DateTime<Utc>,
}

/// Request to create or update a credential.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CredentialCreateRequest {
    /// Credential name
    pub name: String,

    /// Credential type
    #[serde(rename = "type")]
    pub credential_type: String,

    /// Credential data (will be encrypted)
    pub data: serde_json::Value,

    /// Additional metadata
    #[serde(default)]
    pub meta: Option<serde_json::Value>,

    /// Tags for categorization
    #[serde(default)]
    pub tags: Option<Vec<String>>,

    /// Description
    #[serde(default)]
    pub description: Option<String>,
}

/// Response after creating/updating a credential.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CredentialResponse {
    /// Credential ID
    pub id: String,

    /// Credential name
    pub name: String,

    /// Credential type
    #[serde(rename = "type")]
    pub credential_type: String,

    /// Additional metadata
    #[serde(skip_serializing_if = "Option::is_none")]
    pub meta: Option<serde_json::Value>,

    /// Tags
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<Vec<String>>,

    /// Description
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,

    /// Decrypted credential data (only included when requested)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<serde_json::Value>,

    /// Creation timestamp
    pub created_at: DateTime<Utc>,

    /// Last update timestamp
    pub updated_at: DateTime<Utc>,
}

/// Response for listing credentials.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CredentialListResponse {
    /// List of credentials
    pub items: Vec<CredentialResponse>,

    /// Applied filter
    #[serde(skip_serializing_if = "Option::is_none")]
    pub filter: Option<CredentialFilter>,
}

/// Filter for listing credentials.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CredentialFilter {
    /// Filter by type
    #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
    pub credential_type: Option<String>,

    /// Free-text search
    #[serde(skip_serializing_if = "Option::is_none")]
    pub q: Option<String>,
}

/// Request to generate a GCP access token.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct GCPTokenRequest {
    /// OAuth scopes
    #[serde(default)]
    pub scopes: Option<Vec<String>>,

    /// Credential name or ID
    #[serde(default)]
    pub credential: Option<String>,

    /// Credential ID
    #[serde(default)]
    pub credential_id: Option<String>,

    /// Service account JSON as object or string
    #[serde(default)]
    pub credentials_info: Option<serde_json::Value>,

    /// GCP Secret Manager path
    #[serde(default)]
    pub service_account_secret: Option<String>,

    /// Path to service account JSON file
    #[serde(default)]
    pub credentials_path: Option<String>,

    /// Use GCE metadata server
    #[serde(default)]
    pub use_metadata: Option<bool>,

    /// Store generated token as credential
    #[serde(default)]
    pub store_as: Option<String>,

    /// Type for stored credential
    #[serde(default)]
    pub store_type: Option<String>,

    /// Tags for stored credential
    #[serde(default)]
    pub store_tags: Option<Vec<String>>,
}

/// Response containing GCP access token.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GCPTokenResponse {
    /// Access token
    pub access_token: String,

    /// Token expiry time
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token_expiry: Option<DateTime<Utc>>,

    /// Scopes granted
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scopes: Option<Vec<String>>,
}
