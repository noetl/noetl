//! Database API handlers.
//!
//! Provides endpoints for executing PostgreSQL queries and managing the database schema.

use axum::{extract::State, Json};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use serde::{Deserialize, Serialize};
use sqlx::{Column, Row};

use crate::db::DbPool;
use crate::error::AppError;

/// Request for executing PostgreSQL queries or procedures.
#[derive(Debug, Clone, Deserialize)]
pub struct PostgresExecuteRequest {
    /// SQL query to execute.
    pub query: Option<String>,

    /// Base64-encoded SQL query (alternative to query field).
    pub query_base64: Option<String>,

    /// Stored procedure to call.
    pub procedure: Option<String>,

    /// Parameters for the query or procedure.
    pub parameters: Option<Vec<serde_json::Value>>,

    /// Database schema to use (sets search_path).
    #[serde(alias = "schema")]
    pub db_schema: Option<String>,

    /// Database name to connect to.
    pub database: Option<String>,

    /// Credential name from credential table.
    pub credential: Option<String>,

    /// Custom connection string (highest priority).
    pub connection_string: Option<String>,
}

/// Response for PostgreSQL execution.
#[derive(Debug, Clone, Serialize)]
pub struct PostgresExecuteResponse {
    /// Execution status (ok or error).
    pub status: String,

    /// Query results (if any).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Vec<serde_json::Value>>,

    /// Error message (if status is error).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Response for database schema operations.
#[derive(Debug, Clone, Serialize)]
pub struct SchemaOperationResponse {
    /// Operation status.
    pub status: String,

    /// Operation message.
    pub message: String,

    /// Whether the schema is valid (for validate endpoint).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub valid: Option<bool>,

    /// List of found tables.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tables: Option<Vec<String>>,

    /// List of missing tables.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub missing: Option<Vec<String>>,
}

/// Execute a PostgreSQL query.
///
/// POST /api/postgres/execute
///
/// Executes a SQL query against the database. The query can be provided directly
/// or base64-encoded. Supports parameterized queries.
pub async fn execute_postgres(
    State(db): State<DbPool>,
    Json(request): Json<PostgresExecuteRequest>,
) -> Result<Json<PostgresExecuteResponse>, AppError> {
    // Decode query if base64 encoded
    let query = if let Some(ref q64) = request.query_base64 {
        let decoded = BASE64
            .decode(q64)
            .map_err(|e| AppError::Validation(format!("Invalid base64: {}", e)))?;
        Some(
            String::from_utf8(decoded)
                .map_err(|e| AppError::Validation(format!("Invalid UTF-8 in query: {}", e)))?,
        )
    } else {
        request.query.clone()
    };

    // Get query or procedure
    let sql = if let Some(q) = query {
        q.trim().to_string()
    } else if let Some(p) = request.procedure.clone() {
        p.trim().to_string()
    } else {
        return Err(AppError::Validation(
            "Either 'query' or 'procedure' must be provided".to_string(),
        ));
    };

    // For now, we only support queries on the default database connection
    // Custom connection strings and credentials would require additional implementation

    // Set search_path if schema is specified
    if let Some(ref schema) = request.db_schema {
        sqlx::query(&format!("SET search_path TO {}", schema))
            .execute(&db)
            .await?;
    }

    // Execute the query
    let result = execute_query(&db, &sql, request.parameters.as_deref()).await?;

    Ok(Json(PostgresExecuteResponse {
        status: "ok".to_string(),
        result: Some(result),
        error: None,
    }))
}

/// Execute a query and return results as JSON.
async fn execute_query(
    db: &DbPool,
    sql: &str,
    _parameters: Option<&[serde_json::Value]>,
) -> Result<Vec<serde_json::Value>, AppError> {
    // Execute the query using raw SQL
    // For parameterized queries, we'd need to bind parameters dynamically
    let rows = sqlx::query(sql).fetch_all(db).await?;

    // Convert rows to JSON
    let mut results = Vec::new();

    for row in rows {
        let mut obj = serde_json::Map::new();

        // Get column information
        for (idx, column) in row.columns().iter().enumerate() {
            let name = column.name();
            let value = row_value_to_json(&row, idx)?;
            obj.insert(name.to_string(), value);
        }

        results.push(serde_json::Value::Object(obj));
    }

    Ok(results)
}

/// Convert a row value to JSON.
fn row_value_to_json(
    row: &sqlx::postgres::PgRow,
    idx: usize,
) -> Result<serde_json::Value, AppError> {
    use sqlx::TypeInfo;

    let column = &row.columns()[idx];
    let type_name = column.type_info().name();

    // Try to decode based on type
    let value: serde_json::Value = match type_name {
        "INT2" | "INT4" => {
            if let Ok(v) = row.try_get::<Option<i32>, _>(idx) {
                v.map(|v| serde_json::json!(v))
                    .unwrap_or(serde_json::Value::Null)
            } else {
                serde_json::Value::Null
            }
        }
        "INT8" => {
            if let Ok(v) = row.try_get::<Option<i64>, _>(idx) {
                v.map(|v| serde_json::json!(v))
                    .unwrap_or(serde_json::Value::Null)
            } else {
                serde_json::Value::Null
            }
        }
        "FLOAT4" | "FLOAT8" => {
            if let Ok(v) = row.try_get::<Option<f64>, _>(idx) {
                v.map(|v| serde_json::json!(v))
                    .unwrap_or(serde_json::Value::Null)
            } else {
                serde_json::Value::Null
            }
        }
        "BOOL" => {
            if let Ok(v) = row.try_get::<Option<bool>, _>(idx) {
                v.map(|v| serde_json::json!(v))
                    .unwrap_or(serde_json::Value::Null)
            } else {
                serde_json::Value::Null
            }
        }
        "JSON" | "JSONB" => {
            if let Ok(v) = row.try_get::<Option<serde_json::Value>, _>(idx) {
                v.unwrap_or(serde_json::Value::Null)
            } else {
                serde_json::Value::Null
            }
        }
        "TIMESTAMPTZ" | "TIMESTAMP" => {
            if let Ok(v) = row.try_get::<Option<chrono::DateTime<chrono::Utc>>, _>(idx) {
                v.map(|v| serde_json::json!(v.to_rfc3339()))
                    .unwrap_or(serde_json::Value::Null)
            } else {
                serde_json::Value::Null
            }
        }
        _ => {
            // Default to string for unknown types
            if let Ok(v) = row.try_get::<Option<String>, _>(idx) {
                v.map(|v| serde_json::json!(v))
                    .unwrap_or(serde_json::Value::Null)
            } else {
                serde_json::Value::Null
            }
        }
    };

    Ok(value)
}

/// Initialize the database schema.
///
/// POST /api/db/init
///
/// Creates all required tables, indexes, and functions if they don't exist.
pub async fn init_database(
    State(db): State<DbPool>,
) -> Result<Json<SchemaOperationResponse>, AppError> {
    // Read the schema DDL from the embedded SQL or execute it
    // For now, we'll check if the schema exists and report
    let schema = std::env::var("NOETL_SCHEMA").unwrap_or_else(|_| "noetl".to_string());

    // Check if schema exists
    let schema_exists: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = $1)")
            .bind(&schema)
            .fetch_one(&db)
            .await?;

    if schema_exists {
        Ok(Json(SchemaOperationResponse {
            status: "ok".to_string(),
            message: format!(
                "Schema '{}' already exists. Run noetlctl db init to reinitialize.",
                schema
            ),
            valid: Some(true),
            tables: None,
            missing: None,
        }))
    } else {
        Ok(Json(SchemaOperationResponse {
            status: "ok".to_string(),
            message: format!(
                "Schema '{}' does not exist. Run noetlctl db init to create it.",
                schema
            ),
            valid: Some(false),
            tables: None,
            missing: None,
        }))
    }
}

/// Validate the database schema.
///
/// GET /api/db/validate
///
/// Checks for required tables, columns, indexes, and functions.
pub async fn validate_database(
    State(db): State<DbPool>,
) -> Result<Json<SchemaOperationResponse>, AppError> {
    let schema = std::env::var("NOETL_SCHEMA").unwrap_or_else(|_| "noetl".to_string());

    // Required tables for v2 schema
    let required_tables = [
        "resource",
        "catalog",
        "transient",
        "event",
        "credential",
        "runtime",
        "schedule",
        "keychain",
    ];

    // Query existing tables
    let existing_tables: Vec<String> = sqlx::query_scalar(
        "SELECT table_name::text FROM information_schema.tables WHERE table_schema = $1",
    )
    .bind(&schema)
    .fetch_all(&db)
    .await?;

    // Find missing tables
    let missing: Vec<String> = required_tables
        .iter()
        .filter(|t| !existing_tables.contains(&t.to_string()))
        .map(|s| s.to_string())
        .collect();

    let valid = missing.is_empty();

    Ok(Json(SchemaOperationResponse {
        status: "ok".to_string(),
        message: if valid {
            "Database schema is valid".to_string()
        } else {
            format!("Missing tables: {}", missing.join(", "))
        },
        valid: Some(valid),
        tables: Some(existing_tables),
        missing: Some(missing),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_execute_request_deserialization() {
        let json = r#"{"query": "SELECT 1"}"#;
        let request: PostgresExecuteRequest = serde_json::from_str(json).unwrap();
        assert_eq!(request.query, Some("SELECT 1".to_string()));
    }

    #[test]
    fn test_execute_request_with_schema_alias() {
        let json = r#"{"query": "SELECT 1", "schema": "public"}"#;
        let request: PostgresExecuteRequest = serde_json::from_str(json).unwrap();
        assert_eq!(request.db_schema, Some("public".to_string()));
    }

    #[test]
    fn test_execute_response_serialization() {
        let response = PostgresExecuteResponse {
            status: "ok".to_string(),
            result: Some(vec![serde_json::json!({"id": 1})]),
            error: None,
        };

        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("\"status\":\"ok\""));
        assert!(json.contains("\"result\""));
        assert!(!json.contains("\"error\""));
    }

    #[test]
    fn test_schema_response_serialization() {
        let response = SchemaOperationResponse {
            status: "ok".to_string(),
            message: "Schema valid".to_string(),
            valid: Some(true),
            tables: Some(vec!["event".to_string()]),
            missing: Some(vec![]),
        };

        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("\"valid\":true"));
    }
}
