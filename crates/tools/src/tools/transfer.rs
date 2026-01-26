//! Data transfer tool for moving data between database systems.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::auth::AuthResolver;
use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::registry::{AuthConfig, Tool, ToolConfig};
use crate::result::ToolResult;
use crate::template::TemplateEngine;

/// Transfer source type.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum SourceType {
    Snowflake,
    Postgres,
    #[serde(alias = "HTTP")]
    Http,
    DuckDb,
}

/// Transfer target type.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum TargetType {
    Snowflake,
    Postgres,
    DuckDb,
}

/// Transfer mode.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum TransferMode {
    /// Append to existing data.
    #[default]
    Append,
    /// Replace all data in target.
    Replace,
    /// Upsert based on primary key.
    Upsert,
}

/// Source configuration for data transfer.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceConfig {
    /// Source type (snowflake, postgres, http, duckdb).
    #[serde(alias = "tool", alias = "kind")]
    #[serde(rename = "type")]
    pub source_type: SourceType,

    /// SQL query to fetch data from source.
    pub query: String,

    /// Authentication configuration.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auth: Option<AuthConfig>,

    /// URL for HTTP sources.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,

    /// HTTP method for HTTP sources.
    #[serde(default = "default_http_method")]
    pub method: String,

    /// HTTP headers for HTTP sources.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub headers: Option<HashMap<String, String>>,

    /// JSON path for extracting data from HTTP response.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data_path: Option<String>,

    /// Connection string (for postgres/duckdb).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub connection: Option<String>,

    /// Snowflake-specific configuration.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub account: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub user: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub password: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub warehouse: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub database: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub schema: Option<String>,
}

fn default_http_method() -> String {
    "GET".to_string()
}

/// Target configuration for data transfer.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TargetConfig {
    /// Target type (snowflake, postgres, duckdb).
    #[serde(alias = "tool", alias = "kind")]
    #[serde(rename = "type")]
    pub target_type: TargetType,

    /// Target table name.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub table: Option<String>,

    /// Custom query for INSERT/UPSERT operations.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub query: Option<String>,

    /// Authentication configuration.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auth: Option<AuthConfig>,

    /// Column mapping from source to target.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mapping: Option<HashMap<String, String>>,

    /// Connection string (for postgres/duckdb).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub connection: Option<String>,

    /// Snowflake-specific configuration.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub account: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub user: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub password: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub warehouse: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub database: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub schema: Option<String>,
}

/// Transfer tool configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransferConfig {
    /// Source configuration.
    pub source: SourceConfig,

    /// Target configuration.
    pub target: TargetConfig,

    /// Number of rows per batch.
    #[serde(default = "default_chunk_size")]
    pub chunk_size: usize,

    /// Transfer mode.
    #[serde(default)]
    pub mode: TransferMode,
}

fn default_chunk_size() -> usize {
    1000
}

/// Transfer result data.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransferResultData {
    /// Transfer direction description.
    pub direction: String,

    /// Source type.
    pub source_type: String,

    /// Target type.
    pub target_type: String,

    /// Transfer mode used.
    pub mode: String,

    /// Number of rows transferred.
    pub rows_transferred: usize,

    /// Number of chunks processed.
    pub chunks_processed: usize,

    /// Target table name.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_table: Option<String>,

    /// Columns transferred.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub columns: Option<Vec<String>>,
}

/// Data transfer tool.
pub struct TransferTool {
    http_client: reqwest::Client,
    auth_resolver: AuthResolver,
    template_engine: TemplateEngine,
}

impl TransferTool {
    /// Create a new transfer tool.
    pub fn new() -> Self {
        Self {
            http_client: reqwest::Client::new(),
            auth_resolver: AuthResolver::new(),
            template_engine: TemplateEngine::new(),
        }
    }

    /// Execute data transfer.
    pub async fn execute_transfer(
        &self,
        config: &TransferConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let start = std::time::Instant::now();

        // Validate transfer direction is supported
        self.validate_transfer_direction(&config.source.source_type, &config.target.target_type)?;

        // Execute transfer based on source/target types
        let result_data = match (&config.source.source_type, &config.target.target_type) {
            (SourceType::Postgres, TargetType::Postgres) => {
                self.transfer_postgres_to_postgres(config, ctx).await?
            }
            (SourceType::Http, TargetType::Postgres) => {
                self.transfer_http_to_postgres(config, ctx).await?
            }
            (SourceType::DuckDb, TargetType::Postgres) => {
                self.transfer_duckdb_to_postgres(config, ctx).await?
            }
            (SourceType::Postgres, TargetType::DuckDb) => {
                self.transfer_postgres_to_duckdb(config, ctx).await?
            }
            _ => {
                return Err(ToolError::Configuration(format!(
                    "Transfer from {:?} to {:?} is not yet implemented",
                    config.source.source_type, config.target.target_type
                )));
            }
        };

        let duration_ms = start.elapsed().as_millis() as u64;

        Ok(ToolResult::success(serde_json::to_value(&result_data).unwrap()).with_duration(duration_ms))
    }

    /// Validate that the transfer direction is supported.
    fn validate_transfer_direction(
        &self,
        source: &SourceType,
        target: &TargetType,
    ) -> Result<(), ToolError> {
        let supported = matches!(
            (source, target),
            (SourceType::Postgres, TargetType::Postgres)
                | (SourceType::Http, TargetType::Postgres)
                | (SourceType::DuckDb, TargetType::Postgres)
                | (SourceType::Postgres, TargetType::DuckDb)
                | (SourceType::Snowflake, TargetType::Postgres)
                | (SourceType::Postgres, TargetType::Snowflake)
        );

        if !supported {
            return Err(ToolError::Configuration(format!(
                "Unsupported transfer direction: {:?} to {:?}",
                source, target
            )));
        }

        Ok(())
    }

    /// Transfer data from PostgreSQL to PostgreSQL.
    async fn transfer_postgres_to_postgres(
        &self,
        config: &TransferConfig,
        _ctx: &ExecutionContext,
    ) -> Result<TransferResultData, ToolError> {
        use crate::tools::postgres::PostgresTool;

        let pg_tool = PostgresTool::new();

        // Get source connection
        let source_conn = config.source.connection.as_ref().ok_or_else(|| {
            ToolError::Configuration("Source connection string required".to_string())
        })?;

        // Get target connection
        let target_conn = config.target.connection.as_ref().ok_or_else(|| {
            ToolError::Configuration("Target connection string required".to_string())
        })?;

        let target_table = config.target.table.as_ref().ok_or_else(|| {
            ToolError::Configuration("Target table name required".to_string())
        })?;

        // Fetch data from source
        let source_result = pg_tool
            .execute_query(&config.source.query, &[], source_conn, None, true)
            .await?;

        let source_data = source_result
            .data
            .ok_or_else(|| ToolError::Database("No data returned from source".to_string()))?;

        let rows = source_data["rows"]
            .as_array()
            .ok_or_else(|| ToolError::Database("Invalid source data format".to_string()))?;

        let columns: Vec<String> = source_data["columns"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        if rows.is_empty() {
            return Ok(TransferResultData {
                direction: "postgres_to_postgres".to_string(),
                source_type: "postgres".to_string(),
                target_type: "postgres".to_string(),
                mode: format!("{:?}", config.mode).to_lowercase(),
                rows_transferred: 0,
                chunks_processed: 0,
                target_table: Some(target_table.clone()),
                columns: Some(columns),
            });
        }

        // Handle replace mode - truncate target first
        if matches!(config.mode, TransferMode::Replace) {
            let truncate_query = format!("TRUNCATE TABLE {}", target_table);
            pg_tool
                .execute_query(&truncate_query, &[], target_conn, None, false)
                .await?;
        }

        // Build INSERT query
        let insert_columns = columns.join(", ");
        let placeholders: Vec<String> = (1..=columns.len()).map(|i| format!("${}", i)).collect();
        let insert_query = format!(
            "INSERT INTO {} ({}) VALUES ({})",
            target_table,
            insert_columns,
            placeholders.join(", ")
        );

        // Insert data in chunks
        let mut rows_transferred = 0;
        let mut chunks_processed = 0;

        for chunk in rows.chunks(config.chunk_size) {
            for row in chunk {
                let params: Vec<serde_json::Value> = columns
                    .iter()
                    .map(|col| row.get(col).cloned().unwrap_or(serde_json::Value::Null))
                    .collect();

                pg_tool
                    .execute_query(&insert_query, &params, target_conn, None, false)
                    .await?;
                rows_transferred += 1;
            }
            chunks_processed += 1;
        }

        Ok(TransferResultData {
            direction: "postgres_to_postgres".to_string(),
            source_type: "postgres".to_string(),
            target_type: "postgres".to_string(),
            mode: format!("{:?}", config.mode).to_lowercase(),
            rows_transferred,
            chunks_processed,
            target_table: Some(target_table.clone()),
            columns: Some(columns),
        })
    }

    /// Transfer data from HTTP to PostgreSQL.
    async fn transfer_http_to_postgres(
        &self,
        config: &TransferConfig,
        _ctx: &ExecutionContext,
    ) -> Result<TransferResultData, ToolError> {
        use crate::tools::postgres::PostgresTool;

        let pg_tool = PostgresTool::new();

        // Get HTTP URL
        let url = config.source.url.as_ref().ok_or_else(|| {
            ToolError::Configuration("Source URL required for HTTP transfer".to_string())
        })?;

        // Get target connection
        let target_conn = config.target.connection.as_ref().ok_or_else(|| {
            ToolError::Configuration("Target connection string required".to_string())
        })?;

        let target_table = config.target.table.as_ref().ok_or_else(|| {
            ToolError::Configuration("Target table name required".to_string())
        })?;

        // Fetch data from HTTP source
        let mut request = match config.source.method.to_uppercase().as_str() {
            "POST" => self.http_client.post(url),
            _ => self.http_client.get(url),
        };

        // Add headers
        if let Some(ref headers) = config.source.headers {
            for (k, v) in headers {
                request = request.header(k, v);
            }
        }

        let response = request
            .send()
            .await
            .map_err(|e| ToolError::Http(format!("HTTP request failed: {}", e)))?;

        let json_data: serde_json::Value = response
            .json()
            .await
            .map_err(|e| ToolError::Http(format!("Failed to parse JSON response: {}", e)))?;

        // Extract data using data_path if provided
        let data = if let Some(ref path) = config.source.data_path {
            extract_json_path(&json_data, path)?
        } else {
            json_data
        };

        // Convert to array
        let rows = match data {
            serde_json::Value::Array(arr) => arr,
            obj @ serde_json::Value::Object(_) => vec![obj],
            _ => {
                return Err(ToolError::Http(
                    "HTTP response data must be an array or object".to_string(),
                ))
            }
        };

        if rows.is_empty() {
            return Ok(TransferResultData {
                direction: "http_to_postgres".to_string(),
                source_type: "http".to_string(),
                target_type: "postgres".to_string(),
                mode: format!("{:?}", config.mode).to_lowercase(),
                rows_transferred: 0,
                chunks_processed: 0,
                target_table: Some(target_table.clone()),
                columns: None,
            });
        }

        // Get columns from mapping or first row
        let columns: Vec<String> = if let Some(ref mapping) = config.target.mapping {
            mapping.keys().cloned().collect()
        } else if let serde_json::Value::Object(obj) = &rows[0] {
            obj.keys().cloned().collect()
        } else {
            return Err(ToolError::Configuration(
                "Cannot determine columns from HTTP data".to_string(),
            ));
        };

        // Handle replace mode
        if matches!(config.mode, TransferMode::Replace) {
            let truncate_query = format!("TRUNCATE TABLE {}", target_table);
            pg_tool
                .execute_query(&truncate_query, &[], target_conn, None, false)
                .await?;
        }

        // Build INSERT query
        let insert_columns = columns.join(", ");
        let placeholders: Vec<String> = (1..=columns.len()).map(|i| format!("${}", i)).collect();
        let insert_query = format!(
            "INSERT INTO {} ({}) VALUES ({})",
            target_table,
            insert_columns,
            placeholders.join(", ")
        );

        // Insert data in chunks
        let mut rows_transferred = 0;
        let mut chunks_processed = 0;

        let mapping = config.target.mapping.as_ref();

        for chunk in rows.chunks(config.chunk_size) {
            for row in chunk {
                let params: Vec<serde_json::Value> = columns
                    .iter()
                    .map(|col| {
                        let source_field = mapping
                            .and_then(|m| m.get(col))
                            .map(|s| s.as_str())
                            .unwrap_or(col);
                        row.get(source_field)
                            .cloned()
                            .unwrap_or(serde_json::Value::Null)
                    })
                    .collect();

                pg_tool
                    .execute_query(&insert_query, &params, target_conn, None, false)
                    .await?;
                rows_transferred += 1;
            }
            chunks_processed += 1;
        }

        Ok(TransferResultData {
            direction: "http_to_postgres".to_string(),
            source_type: "http".to_string(),
            target_type: "postgres".to_string(),
            mode: format!("{:?}", config.mode).to_lowercase(),
            rows_transferred,
            chunks_processed,
            target_table: Some(target_table.clone()),
            columns: Some(columns),
        })
    }

    /// Transfer data from DuckDB to PostgreSQL.
    async fn transfer_duckdb_to_postgres(
        &self,
        config: &TransferConfig,
        _ctx: &ExecutionContext,
    ) -> Result<TransferResultData, ToolError> {
        use crate::tools::duckdb::DuckdbTool;
        use crate::tools::postgres::PostgresTool;

        let duckdb_tool = DuckdbTool::new();
        let pg_tool = PostgresTool::new();

        let db_path = config.source.connection.as_deref();
        let target_conn = config.target.connection.as_ref().ok_or_else(|| {
            ToolError::Configuration("Target connection string required".to_string())
        })?;

        let target_table = config.target.table.as_ref().ok_or_else(|| {
            ToolError::Configuration("Target table name required".to_string())
        })?;

        // Fetch data from DuckDB
        let source_result = duckdb_tool.execute_query(&config.source.query, &[], db_path, true)?;

        let source_data = source_result
            .data
            .ok_or_else(|| ToolError::Database("No data returned from source".to_string()))?;

        let rows = source_data["rows"]
            .as_array()
            .ok_or_else(|| ToolError::Database("Invalid source data format".to_string()))?;

        let columns: Vec<String> = source_data["columns"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        if rows.is_empty() {
            return Ok(TransferResultData {
                direction: "duckdb_to_postgres".to_string(),
                source_type: "duckdb".to_string(),
                target_type: "postgres".to_string(),
                mode: format!("{:?}", config.mode).to_lowercase(),
                rows_transferred: 0,
                chunks_processed: 0,
                target_table: Some(target_table.clone()),
                columns: Some(columns),
            });
        }

        // Handle replace mode
        if matches!(config.mode, TransferMode::Replace) {
            let truncate_query = format!("TRUNCATE TABLE {}", target_table);
            pg_tool
                .execute_query(&truncate_query, &[], target_conn, None, false)
                .await?;
        }

        // Build INSERT query
        let insert_columns = columns.join(", ");
        let placeholders: Vec<String> = (1..=columns.len()).map(|i| format!("${}", i)).collect();
        let insert_query = format!(
            "INSERT INTO {} ({}) VALUES ({})",
            target_table,
            insert_columns,
            placeholders.join(", ")
        );

        // Insert data in chunks
        let mut rows_transferred = 0;
        let mut chunks_processed = 0;

        for chunk in rows.chunks(config.chunk_size) {
            for row in chunk {
                let params: Vec<serde_json::Value> = columns
                    .iter()
                    .map(|col| row.get(col).cloned().unwrap_or(serde_json::Value::Null))
                    .collect();

                pg_tool
                    .execute_query(&insert_query, &params, target_conn, None, false)
                    .await?;
                rows_transferred += 1;
            }
            chunks_processed += 1;
        }

        Ok(TransferResultData {
            direction: "duckdb_to_postgres".to_string(),
            source_type: "duckdb".to_string(),
            target_type: "postgres".to_string(),
            mode: format!("{:?}", config.mode).to_lowercase(),
            rows_transferred,
            chunks_processed,
            target_table: Some(target_table.clone()),
            columns: Some(columns),
        })
    }

    /// Transfer data from PostgreSQL to DuckDB.
    async fn transfer_postgres_to_duckdb(
        &self,
        config: &TransferConfig,
        _ctx: &ExecutionContext,
    ) -> Result<TransferResultData, ToolError> {
        use crate::tools::duckdb::DuckdbTool;
        use crate::tools::postgres::PostgresTool;

        let pg_tool = PostgresTool::new();
        let duckdb_tool = DuckdbTool::new();

        let source_conn = config.source.connection.as_ref().ok_or_else(|| {
            ToolError::Configuration("Source connection string required".to_string())
        })?;

        let db_path = config.target.connection.as_deref();
        let target_table = config.target.table.as_ref().ok_or_else(|| {
            ToolError::Configuration("Target table name required".to_string())
        })?;

        // Fetch data from PostgreSQL
        let source_result = pg_tool
            .execute_query(&config.source.query, &[], source_conn, None, true)
            .await?;

        let source_data = source_result
            .data
            .ok_or_else(|| ToolError::Database("No data returned from source".to_string()))?;

        let rows = source_data["rows"]
            .as_array()
            .ok_or_else(|| ToolError::Database("Invalid source data format".to_string()))?;

        let columns: Vec<String> = source_data["columns"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        if rows.is_empty() {
            return Ok(TransferResultData {
                direction: "postgres_to_duckdb".to_string(),
                source_type: "postgres".to_string(),
                target_type: "duckdb".to_string(),
                mode: format!("{:?}", config.mode).to_lowercase(),
                rows_transferred: 0,
                chunks_processed: 0,
                target_table: Some(target_table.clone()),
                columns: Some(columns),
            });
        }

        // Handle replace mode - drop and recreate table
        if matches!(config.mode, TransferMode::Replace) {
            let drop_query = format!("DROP TABLE IF EXISTS {}", target_table);
            let _ = duckdb_tool.execute_query(&drop_query, &[], db_path, true);
        }

        // Build INSERT query with placeholders
        let insert_columns = columns.join(", ");
        let placeholders: Vec<String> = (0..columns.len()).map(|_| "?".to_string()).collect();
        let insert_query = format!(
            "INSERT INTO {} ({}) VALUES ({})",
            target_table,
            insert_columns,
            placeholders.join(", ")
        );

        // Insert data in chunks
        let mut rows_transferred = 0;
        let mut chunks_processed = 0;

        for chunk in rows.chunks(config.chunk_size) {
            for row in chunk {
                let params: Vec<serde_json::Value> = columns
                    .iter()
                    .map(|col| row.get(col).cloned().unwrap_or(serde_json::Value::Null))
                    .collect();

                duckdb_tool.execute_query(&insert_query, &params, db_path, true)?;
                rows_transferred += 1;
            }
            chunks_processed += 1;
        }

        Ok(TransferResultData {
            direction: "postgres_to_duckdb".to_string(),
            source_type: "postgres".to_string(),
            target_type: "duckdb".to_string(),
            mode: format!("{:?}", config.mode).to_lowercase(),
            rows_transferred,
            chunks_processed,
            target_table: Some(target_table.clone()),
            columns: Some(columns),
        })
    }

    /// Parse transfer config from tool config.
    fn parse_config(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<TransferConfig, ToolError> {
        let template_ctx = ctx.to_template_context();
        let rendered_config = self
            .template_engine
            .render_value(&config.config, &template_ctx)?;

        serde_json::from_value(rendered_config)
            .map_err(|e| ToolError::Configuration(format!("Invalid transfer config: {}", e)))
    }
}

/// Extract nested value from JSON using dot notation path.
fn extract_json_path(json: &serde_json::Value, path: &str) -> Result<serde_json::Value, ToolError> {
    let mut current = json;

    for segment in path.split('.') {
        current = current.get(segment).ok_or_else(|| {
            ToolError::Http(format!("Path segment '{}' not found in JSON", segment))
        })?;
    }

    Ok(current.clone())
}

impl Default for TransferTool {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for TransferTool {
    fn name(&self) -> &'static str {
        "transfer"
    }

    async fn execute(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let transfer_config = self.parse_config(config, ctx)?;

        tracing::debug!(
            source = ?transfer_config.source.source_type,
            target = ?transfer_config.target.target_type,
            mode = ?transfer_config.mode,
            chunk_size = transfer_config.chunk_size,
            "Executing data transfer"
        );

        self.execute_transfer(&transfer_config, ctx).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_transfer_config_deserialization() {
        let json = serde_json::json!({
            "source": {
                "type": "postgres",
                "query": "SELECT * FROM users",
                "connection": "postgres://localhost/source"
            },
            "target": {
                "type": "postgres",
                "table": "users_copy",
                "connection": "postgres://localhost/target"
            },
            "chunk_size": 500,
            "mode": "append"
        });

        let config: TransferConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.source.source_type, SourceType::Postgres);
        assert_eq!(config.target.target_type, TargetType::Postgres);
        assert_eq!(config.chunk_size, 500);
    }

    #[test]
    fn test_transfer_config_defaults() {
        let json = serde_json::json!({
            "source": {
                "type": "http",
                "url": "https://api.example.com/data",
                "query": ""
            },
            "target": {
                "type": "postgres",
                "table": "imported_data",
                "connection": "postgres://localhost/db"
            }
        });

        let config: TransferConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.chunk_size, 1000);
        assert!(matches!(config.mode, TransferMode::Append));
    }

    #[test]
    fn test_extract_json_path() {
        let json = serde_json::json!({
            "data": {
                "results": {
                    "items": [1, 2, 3]
                }
            }
        });

        let result = extract_json_path(&json, "data.results.items").unwrap();
        assert_eq!(result, serde_json::json!([1, 2, 3]));
    }

    #[test]
    fn test_extract_json_path_not_found() {
        let json = serde_json::json!({"data": {"items": []}});
        let result = extract_json_path(&json, "data.results");
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_transfer_tool_interface() {
        let tool = TransferTool::new();
        assert_eq!(tool.name(), "transfer");
    }

    #[test]
    fn test_transfer_result_serialization() {
        let result = TransferResultData {
            direction: "postgres_to_postgres".to_string(),
            source_type: "postgres".to_string(),
            target_type: "postgres".to_string(),
            mode: "append".to_string(),
            rows_transferred: 100,
            chunks_processed: 10,
            target_table: Some("users".to_string()),
            columns: Some(vec!["id".to_string(), "name".to_string()]),
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("postgres_to_postgres"));
        assert!(json.contains("100"));
    }
}
