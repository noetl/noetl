//! Keychain service for token/credential caching.

use chrono::{Duration, Utc};

use crate::crypto::Encryptor;
use crate::db::models::{
    KeychainDeleteResponse, KeychainEntrySummary, KeychainGetResponse, KeychainListResponse,
    KeychainSetRequest, KeychainSetResponse,
};
use crate::db::queries::keychain as queries;
use crate::db::DbPool;
use crate::error::AppResult;

/// Service for keychain operations.
#[derive(Clone)]
pub struct KeychainService {
    pool: DbPool,
    encryptor: Encryptor,
}

impl KeychainService {
    /// Create a new keychain service.
    ///
    /// # Arguments
    ///
    /// * `pool` - Database connection pool
    /// * `encryption_key` - Base64-encoded 32-byte encryption key
    pub fn new(pool: DbPool, encryption_key: &str) -> AppResult<Self> {
        let encryptor = Encryptor::from_base64(encryption_key)?;
        Ok(Self { pool, encryptor })
    }

    /// Get a keychain entry.
    pub async fn get(
        &self,
        catalog_id: i64,
        keychain_name: &str,
        execution_id: Option<i64>,
        scope_type: &str,
    ) -> AppResult<KeychainGetResponse> {
        let cache_key =
            queries::build_cache_key(keychain_name, catalog_id, scope_type, execution_id);

        let entry = match queries::get_keychain_by_cache_key(&self.pool, &cache_key).await? {
            Some(e) => e,
            None => {
                return Ok(KeychainGetResponse {
                    status: "not_found".to_string(),
                    data: None,
                    expires_at: None,
                    auto_renew: None,
                    access_count: None,
                });
            }
        };

        // Check if expired
        if let Some(expires_at) = entry.expires_at {
            if expires_at < Utc::now() {
                return Ok(KeychainGetResponse {
                    status: "expired".to_string(),
                    data: None,
                    expires_at: Some(expires_at),
                    auto_renew: Some(entry.auto_renew),
                    access_count: Some(entry.access_count),
                });
            }
        }

        // Increment access count
        queries::increment_access_count(&self.pool, entry.id).await?;

        // Decrypt data
        let data = self.encryptor.decrypt_json(&entry.data)?;

        Ok(KeychainGetResponse {
            status: "found".to_string(),
            data: Some(data),
            expires_at: entry.expires_at,
            auto_renew: Some(entry.auto_renew),
            access_count: Some(entry.access_count + 1),
        })
    }

    /// Set a keychain entry.
    pub async fn set(
        &self,
        catalog_id: i64,
        keychain_name: &str,
        request: KeychainSetRequest,
    ) -> AppResult<KeychainSetResponse> {
        let cache_key = queries::build_cache_key(
            keychain_name,
            catalog_id,
            &request.scope_type,
            request.execution_id,
        );

        // Calculate expiry time
        let expires_at = request.expires_at.or_else(|| {
            request
                .expires_in
                .map(|seconds| Utc::now() + Duration::seconds(seconds))
        });

        // Encrypt data
        let encrypted_data = self.encryptor.encrypt_json(&request.data)?;

        // Upsert entry
        queries::upsert_keychain_entry(
            &self.pool,
            &cache_key,
            catalog_id,
            keychain_name,
            &request.scope_type,
            request.execution_id,
            &encrypted_data,
            expires_at,
            request.auto_renew,
            request.renew_config.as_ref(),
        )
        .await?;

        Ok(KeychainSetResponse {
            status: "success".to_string(),
            cache_key,
            expires_at,
        })
    }

    /// Delete a keychain entry.
    pub async fn delete(
        &self,
        catalog_id: i64,
        keychain_name: &str,
        execution_id: Option<i64>,
        scope_type: &str,
    ) -> AppResult<KeychainDeleteResponse> {
        let cache_key =
            queries::build_cache_key(keychain_name, catalog_id, scope_type, execution_id);

        let deleted = queries::delete_keychain_by_cache_key(&self.pool, &cache_key).await?;

        Ok(KeychainDeleteResponse {
            status: if deleted { "deleted" } else { "not_found" }.to_string(),
            cache_key: if deleted { Some(cache_key) } else { None },
        })
    }

    /// List all keychain entries for a catalog.
    pub async fn list_by_catalog(&self, catalog_id: i64) -> AppResult<KeychainListResponse> {
        let entries = queries::list_keychain_by_catalog(&self.pool, catalog_id).await?;
        let now = Utc::now();

        let summaries: Vec<KeychainEntrySummary> = entries
            .into_iter()
            .map(|e| {
                let expired = e.expires_at.map(|exp| exp < now).unwrap_or(false);

                KeychainEntrySummary {
                    keychain_name: e.keychain_name,
                    scope_type: e.scope_type,
                    execution_id: e.execution_id.map(|id| id.to_string()),
                    expires_at: e.expires_at,
                    expired,
                    access_count: e.access_count,
                    accessed_at: e.accessed_at,
                    created_at: e.created_at,
                }
            })
            .collect();

        Ok(KeychainListResponse {
            catalog_id: catalog_id.to_string(),
            entries: summaries,
        })
    }

    /// Delete all expired entries (maintenance task).
    pub async fn cleanup_expired(&self) -> AppResult<u64> {
        queries::delete_expired_entries(&self.pool).await
    }

    /// Delete all entries for an execution.
    pub async fn cleanup_execution(&self, execution_id: i64) -> AppResult<u64> {
        queries::delete_keychain_by_execution(&self.pool, execution_id).await
    }
}
