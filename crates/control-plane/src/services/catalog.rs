//! Catalog service for managing playbooks and resources.

use base64::{engine::general_purpose::STANDARD as BASE64, Engine};

use crate::db::models::{
    CatalogEntries, CatalogEntry, CatalogEntryRequest, CatalogEntryResponse,
    CatalogRegisterRequest, CatalogRegisterResponse,
};
use crate::db::queries::catalog as queries;
use crate::db::DbPool;
use crate::error::{AppError, AppResult};

/// Service for catalog operations.
#[derive(Clone)]
pub struct CatalogService {
    pool: DbPool,
}

impl CatalogService {
    /// Create a new catalog service.
    pub fn new(pool: DbPool) -> Self {
        Self { pool }
    }

    /// Register a new resource in the catalog.
    pub async fn register(
        &self,
        request: CatalogRegisterRequest,
    ) -> AppResult<CatalogRegisterResponse> {
        // Decode content if base64 encoded
        let content = self.decode_content(&request.content)?;

        // Parse YAML to extract metadata
        let yaml: serde_yaml::Value = serde_yaml::from_str(&content)
            .map_err(|e| AppError::Validation(format!("Invalid YAML: {}", e)))?;

        // Extract metadata
        let metadata = yaml
            .get("metadata")
            .ok_or_else(|| AppError::Validation("Missing 'metadata' section".to_string()))?;

        let path = metadata
            .get("path")
            .and_then(|v| v.as_str())
            .or_else(|| metadata.get("name").and_then(|v| v.as_str()))
            .ok_or_else(|| {
                AppError::Validation("Missing 'path' or 'name' in metadata".to_string())
            })?
            .to_string();

        let kind = yaml
            .get("kind")
            .and_then(|v| v.as_str())
            .unwrap_or(&request.resource_type)
            .to_string();

        // Get next version
        let version = queries::get_next_version(&self.pool, &path).await?;

        // Extract optional fields
        let payload = yaml
            .get("workload")
            .map(|v| serde_json::to_value(v).unwrap_or(serde_json::Value::Null));
        let layout = yaml
            .get("workflow")
            .map(|v| serde_json::to_value(v).unwrap_or(serde_json::Value::Null));
        let meta = metadata
            .get("labels")
            .map(|v| serde_json::to_value(v).unwrap_or(serde_json::Value::Null));

        // Insert into database
        let catalog_id = queries::insert_catalog_entry(
            &self.pool,
            &path,
            &kind,
            version,
            &content,
            layout.as_ref(),
            payload.as_ref(),
            meta.as_ref(),
        )
        .await?;

        Ok(CatalogRegisterResponse {
            status: "success".to_string(),
            message: format!("Resource '{}' version '{}' registered.", path, version),
            path,
            version,
            catalog_id: catalog_id.to_string(),
            kind,
        })
    }

    /// List catalog entries.
    pub async fn list(&self, resource_type: Option<&str>) -> AppResult<CatalogEntries> {
        let entries = queries::list_catalog_entries(&self.pool, resource_type).await?;

        let responses: Vec<CatalogEntryResponse> = entries.into_iter().map(|e| e.into()).collect();

        Ok(CatalogEntries { entries: responses })
    }

    /// Get a specific catalog resource.
    pub async fn get_resource(&self, request: CatalogEntryRequest) -> AppResult<CatalogEntry> {
        // Priority: catalog_id > path + version
        if let Some(catalog_id) = &request.catalog_id {
            let id: i64 = catalog_id
                .parse()
                .map_err(|_| AppError::Validation("Invalid catalog_id".to_string()))?;

            return queries::get_catalog_by_id(&self.pool, id)
                .await?
                .ok_or_else(|| {
                    AppError::NotFound(format!("Catalog entry '{}' not found", catalog_id))
                });
        }

        if let Some(path) = &request.path {
            // Check for specific version or "latest"
            if let Some(version_str) = &request.version {
                if version_str == "latest" {
                    return queries::get_catalog_latest(&self.pool, path)
                        .await?
                        .ok_or_else(|| {
                            AppError::NotFound(format!("Catalog entry '{}' not found", path))
                        });
                }

                let version: i32 = version_str
                    .parse()
                    .map_err(|_| AppError::Validation("Invalid version number".to_string()))?;

                return queries::get_catalog_by_path_version(&self.pool, path, version)
                    .await?
                    .ok_or_else(|| {
                        AppError::NotFound(format!(
                            "Catalog entry '{}' version {} not found",
                            path, version
                        ))
                    });
            }

            // Default to latest if no version specified
            return queries::get_catalog_latest(&self.pool, path)
                .await?
                .ok_or_else(|| AppError::NotFound(format!("Catalog entry '{}' not found", path)));
        }

        Err(AppError::Validation(
            "Either 'catalog_id' or 'path' must be provided".to_string(),
        ))
    }

    /// Decode content that may be base64 encoded.
    fn decode_content(&self, content: &str) -> AppResult<String> {
        // Try to decode as base64 first
        if let Ok(decoded) = BASE64.decode(content) {
            if let Ok(s) = String::from_utf8(decoded) {
                return Ok(s);
            }
        }

        // Return as-is if not valid base64
        Ok(content.to_string())
    }
}
