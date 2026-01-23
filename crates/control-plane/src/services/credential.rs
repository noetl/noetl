//! Credential service for managing encrypted credentials.

use crate::crypto::Encryptor;
use crate::db::models::{
    CredentialCreateRequest, CredentialEntry, CredentialFilter, CredentialListResponse,
    CredentialResponse,
};
use crate::db::queries::credential as queries;
use crate::db::DbPool;
use crate::error::{AppError, AppResult};

/// Service for credential operations.
#[derive(Clone)]
pub struct CredentialService {
    pool: DbPool,
    encryptor: Encryptor,
}

impl CredentialService {
    /// Create a new credential service.
    ///
    /// # Arguments
    ///
    /// * `pool` - Database connection pool
    /// * `encryption_key` - Base64-encoded 32-byte encryption key
    pub fn new(pool: DbPool, encryption_key: &str) -> AppResult<Self> {
        let encryptor = Encryptor::from_base64(encryption_key)?;
        Ok(Self { pool, encryptor })
    }

    /// Create or update a credential.
    pub async fn create_or_update(
        &self,
        request: CredentialCreateRequest,
    ) -> AppResult<CredentialResponse> {
        // Encrypt the data
        let encrypted_data = self.encryptor.encrypt_json(&request.data)?;

        // Check if credential already exists
        if let Some(existing) = queries::get_credential_by_name(&self.pool, &request.name).await? {
            // Update existing credential
            queries::update_credential(
                &self.pool,
                existing.id,
                &request.credential_type,
                &encrypted_data,
                request.meta.as_ref(),
                request.tags.as_deref(),
                request.description.as_deref(),
            )
            .await?;

            // Fetch updated credential
            let updated = queries::get_credential_by_id(&self.pool, existing.id)
                .await?
                .ok_or_else(|| {
                    AppError::Internal("Failed to fetch updated credential".to_string())
                })?;

            return Ok(self.entry_to_response(updated, None));
        }

        // Create new credential
        let id = queries::insert_credential(
            &self.pool,
            &request.name,
            &request.credential_type,
            &encrypted_data,
            request.meta.as_ref(),
            request.tags.as_deref(),
            request.description.as_deref(),
        )
        .await?;

        // Fetch created credential
        let created = queries::get_credential_by_id(&self.pool, id)
            .await?
            .ok_or_else(|| AppError::Internal("Failed to fetch created credential".to_string()))?;

        Ok(self.entry_to_response(created, None))
    }

    /// Get a credential by identifier (ID or name).
    pub async fn get(&self, identifier: &str, include_data: bool) -> AppResult<CredentialResponse> {
        let entry = self.find_credential(identifier).await?;

        let data = if include_data {
            Some(self.encryptor.decrypt_json(&entry.data)?)
        } else {
            None
        };

        Ok(self.entry_to_response(entry, data))
    }

    /// List credentials with optional filtering.
    pub async fn list(
        &self,
        credential_type: Option<&str>,
        search: Option<&str>,
    ) -> AppResult<CredentialListResponse> {
        let entries = queries::list_credentials(&self.pool, credential_type, search).await?;

        let items: Vec<CredentialResponse> = entries
            .into_iter()
            .map(|e| self.entry_to_response(e, None))
            .collect();

        let filter = if credential_type.is_some() || search.is_some() {
            Some(CredentialFilter {
                credential_type: credential_type.map(|s| s.to_string()),
                q: search.map(|s| s.to_string()),
            })
        } else {
            None
        };

        Ok(CredentialListResponse { items, filter })
    }

    /// Delete a credential by identifier.
    pub async fn delete(&self, identifier: &str) -> AppResult<String> {
        // Find the credential first to get the ID
        let entry = self.find_credential(identifier).await?;
        let id = entry.id;

        // Delete by ID
        let deleted = queries::delete_credential_by_id(&self.pool, id).await?;

        if deleted {
            Ok(id.to_string())
        } else {
            Err(AppError::Internal(
                "Failed to delete credential".to_string(),
            ))
        }
    }

    /// Find a credential by identifier (ID or name).
    async fn find_credential(&self, identifier: &str) -> AppResult<CredentialEntry> {
        // Try to parse as ID first
        if let Ok(id) = identifier.parse::<i64>() {
            if let Some(entry) = queries::get_credential_by_id(&self.pool, id).await? {
                return Ok(entry);
            }
        }

        // Try to find by name
        queries::get_credential_by_name(&self.pool, identifier)
            .await?
            .ok_or_else(|| AppError::NotFound(format!("Credential '{}' not found", identifier)))
    }

    /// Convert a credential entry to a response.
    fn entry_to_response(
        &self,
        entry: CredentialEntry,
        data: Option<serde_json::Value>,
    ) -> CredentialResponse {
        CredentialResponse {
            id: entry.id.to_string(),
            name: entry.name,
            credential_type: entry.credential_type,
            meta: entry.meta,
            tags: entry.tags,
            description: entry.description,
            data,
            created_at: entry.created_at,
            updated_at: entry.updated_at,
        }
    }
}
