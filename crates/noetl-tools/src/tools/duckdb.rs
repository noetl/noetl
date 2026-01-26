//! DuckDB query execution tool.

use async_trait::async_trait;
use base64::Engine;
use duckdb::Connection;
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};

use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::registry::{Tool, ToolConfig};
use crate::result::ToolResult;
use crate::template::TemplateEngine;

/// DuckDB tool configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DuckdbConfig {
    /// SQL query to execute.
    pub query: String,

    /// Query parameters.
    #[serde(default)]
    pub params: Vec<serde_json::Value>,

    /// Database path (None for in-memory).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub db_path: Option<String>,

    /// Whether to return results as JSON objects (default: true).
    #[serde(default = "default_as_objects")]
    pub as_objects: bool,
}

fn default_as_objects() -> bool {
    true
}

/// DuckDB query execution tool.
pub struct DuckdbTool {
    /// Default connection for in-memory database.
    default_conn: Arc<Mutex<Connection>>,
    template_engine: TemplateEngine,
}

impl DuckdbTool {
    /// Create a new DuckDB tool.
    pub fn new() -> Self {
        let conn = Connection::open_in_memory().expect("Failed to create in-memory DuckDB");
        Self {
            default_conn: Arc::new(Mutex::new(conn)),
            template_engine: TemplateEngine::new(),
        }
    }

    /// Create a DuckDB tool with a specific database path.
    pub fn with_db_path(path: &str) -> Result<Self, ToolError> {
        let conn = Connection::open(path)
            .map_err(|e| ToolError::Database(format!("Failed to open database: {}", e)))?;
        Ok(Self {
            default_conn: Arc::new(Mutex::new(conn)),
            template_engine: TemplateEngine::new(),
        })
    }

    /// Execute a query and return results.
    pub fn execute_query(
        &self,
        query: &str,
        params: &[serde_json::Value],
        db_path: Option<&str>,
        as_objects: bool,
    ) -> Result<ToolResult, ToolError> {
        let start = std::time::Instant::now();

        // Get or create connection
        let conn = if let Some(path) = db_path {
            Connection::open(path)
                .map_err(|e| ToolError::Database(format!("Failed to open database: {}", e)))?
        } else {
            // Use default connection
            let _guard = self.default_conn.lock().map_err(|e| {
                ToolError::Database(format!("Failed to acquire connection lock: {}", e))
            })?;
            // Clone connection or create new in-memory one
            Connection::open_in_memory()
                .map_err(|e| ToolError::Database(format!("Failed to create connection: {}", e)))?
        };

        // Convert params to duckdb types
        let duckdb_params: Vec<Box<dyn duckdb::ToSql>> = params
            .iter()
            .map(|v| json_to_duckdb_param(v))
            .collect();

        // Execute query
        let mut stmt = conn
            .prepare(query)
            .map_err(|e| ToolError::Database(format!("Failed to prepare query: {}", e)))?;

        // Check if it's a SELECT or returns rows
        let is_select = query.trim().to_uppercase().starts_with("SELECT")
            || query.trim().to_uppercase().starts_with("WITH");

        let result = if is_select {
            // Query with results
            let param_refs: Vec<&dyn duckdb::ToSql> =
                duckdb_params.iter().map(|p| p.as_ref()).collect();

            // Use query_map to process rows, which handles borrowing internally
            let mapped_rows = stmt
                .query_map(param_refs.as_slice(), |row| {
                    // Get all values from the row using duckdb::types::Value which handles any type
                    let mut values = Vec::new();
                    let mut idx = 0;
                    // Try reading up to 100 columns (practical limit)
                    while idx < 100 {
                        let value: Result<duckdb::types::Value, _> = row.get(idx);
                        match value {
                            Ok(v) => {
                                values.push(duckdb_value_to_json(&v));
                                idx += 1;
                            }
                            Err(_) => break,
                        }
                    }
                    Ok(values)
                })
                .map_err(|e| ToolError::Database(format!("Query failed: {}", e)))?;

            // Collect results
            let mut results: Vec<Vec<serde_json::Value>> = Vec::new();
            for row_result in mapped_rows {
                let row = row_result
                    .map_err(|e| ToolError::Database(format!("Failed to fetch row: {}", e)))?;
                results.push(row);
            }

            // Get column info from statement now that rows are done
            let column_count = stmt.column_count();
            let column_names: Vec<String> = (0..column_count)
                .map(|i| stmt.column_name(i).map_or("", |v| v).to_string())
                .collect();

            // Convert to final format
            let final_results: Vec<serde_json::Value> = if as_objects {
                results
                    .into_iter()
                    .map(|values| {
                        let mut obj = serde_json::Map::new();
                        for (i, value) in values.into_iter().enumerate() {
                            let name = column_names.get(i).map(|s| s.as_str()).unwrap_or("");
                            obj.insert(name.to_string(), value);
                        }
                        serde_json::Value::Object(obj)
                    })
                    .collect()
            } else {
                results
                    .into_iter()
                    .map(serde_json::Value::Array)
                    .collect()
            };

            serde_json::json!({
                "columns": column_names,
                "rows": final_results,
                "row_count": final_results.len()
            })
        } else {
            // Execute without results (INSERT, UPDATE, DELETE, etc.)
            let param_refs: Vec<&dyn duckdb::ToSql> =
                duckdb_params.iter().map(|p| p.as_ref()).collect();

            let affected = stmt
                .execute(param_refs.as_slice())
                .map_err(|e| ToolError::Database(format!("Execute failed: {}", e)))?;

            serde_json::json!({
                "affected_rows": affected
            })
        };

        let duration_ms = start.elapsed().as_millis() as u64;

        Ok(ToolResult::success(result).with_duration(duration_ms))
    }

    /// Parse DuckDB config from tool config.
    fn parse_config(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<DuckdbConfig, ToolError> {
        let template_ctx = ctx.to_template_context();
        let rendered_config = self.template_engine.render_value(&config.config, &template_ctx)?;

        serde_json::from_value(rendered_config)
            .map_err(|e| ToolError::Configuration(format!("Invalid duckdb config: {}", e)))
    }
}

impl Default for DuckdbTool {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for DuckdbTool {
    fn name(&self) -> &'static str {
        "duckdb"
    }

    async fn execute(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let duckdb_config = self.parse_config(config, ctx)?;

        tracing::debug!(
            query = %duckdb_config.query,
            params_count = duckdb_config.params.len(),
            db_path = ?duckdb_config.db_path,
            "Executing DuckDB query"
        );

        // Execute in a blocking task since DuckDB is sync
        let query = duckdb_config.query.clone();
        let params = duckdb_config.params.clone();
        let db_path = duckdb_config.db_path.clone();
        let as_objects = duckdb_config.as_objects;
        let tool = Self::new();

        tokio::task::spawn_blocking(move || {
            tool.execute_query(&query, &params, db_path.as_deref(), as_objects)
        })
        .await
        .map_err(|e| ToolError::Database(format!("Task join error: {}", e)))?
    }
}

/// Convert JSON value to DuckDB parameter.
fn json_to_duckdb_param(value: &serde_json::Value) -> Box<dyn duckdb::ToSql> {
    match value {
        serde_json::Value::Null => Box::new(Option::<String>::None),
        serde_json::Value::Bool(b) => Box::new(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Box::new(i)
            } else if let Some(f) = n.as_f64() {
                Box::new(f)
            } else {
                Box::new(n.to_string())
            }
        }
        serde_json::Value::String(s) => Box::new(s.clone()),
        _ => Box::new(value.to_string()),
    }
}

/// Convert DuckDB Value to JSON.
fn duckdb_value_to_json(value: &duckdb::types::Value) -> serde_json::Value {
    use duckdb::types::Value;
    match value {
        Value::Null => serde_json::Value::Null,
        Value::Boolean(b) => serde_json::json!(*b),
        Value::TinyInt(n) => serde_json::json!(*n),
        Value::SmallInt(n) => serde_json::json!(*n),
        Value::Int(n) => serde_json::json!(*n),
        Value::BigInt(n) => serde_json::json!(*n),
        Value::HugeInt(n) => serde_json::json!(n.to_string()),
        Value::UTinyInt(n) => serde_json::json!(*n),
        Value::USmallInt(n) => serde_json::json!(*n),
        Value::UInt(n) => serde_json::json!(*n),
        Value::UBigInt(n) => serde_json::json!(*n),
        Value::Float(f) => serde_json::json!(*f),
        Value::Double(f) => serde_json::json!(*f),
        Value::Decimal(d) => serde_json::json!(d.to_string()),
        Value::Text(s) => serde_json::json!(s),
        Value::Blob(b) => serde_json::json!(base64::engine::general_purpose::STANDARD.encode(b)),
        Value::Timestamp(_, t) => serde_json::json!(t),
        Value::Date32(d) => serde_json::json!(*d),
        Value::Time64(_, t) => serde_json::json!(*t),
        Value::Interval { months, days, nanos } => serde_json::json!({
            "months": months,
            "days": days,
            "nanos": nanos
        }),
        Value::List(list) => {
            let values: Vec<serde_json::Value> = list.iter().map(duckdb_value_to_json).collect();
            serde_json::Value::Array(values)
        }
        Value::Enum(s) => serde_json::json!(s),
        Value::Struct(fields) => {
            let obj: serde_json::Map<String, serde_json::Value> = fields
                .iter()
                .map(|(k, v)| (k.clone(), duckdb_value_to_json(v)))
                .collect();
            serde_json::Value::Object(obj)
        }
        Value::Array(arr) => {
            let values: Vec<serde_json::Value> = arr.iter().map(duckdb_value_to_json).collect();
            serde_json::Value::Array(values)
        }
        Value::Map(map) => {
            // For DuckDB maps, convert to JSON object
            let obj: serde_json::Map<String, serde_json::Value> = map
                .iter()
                .map(|(k, v)| (format!("{:?}", k), duckdb_value_to_json(v)))
                .collect();
            serde_json::Value::Object(obj)
        }
        Value::Union(inner) => duckdb_value_to_json(inner),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_duckdb_config_deserialization() {
        let json = serde_json::json!({
            "query": "SELECT * FROM test",
            "params": [1, "hello"],
            "db_path": "/tmp/test.db"
        });

        let config: DuckdbConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.query, "SELECT * FROM test");
        assert_eq!(config.params.len(), 2);
        assert_eq!(config.db_path, Some("/tmp/test.db".to_string()));
    }

    #[test]
    fn test_duckdb_config_defaults() {
        let json = serde_json::json!({
            "query": "SELECT 1"
        });

        let config: DuckdbConfig = serde_json::from_value(json).unwrap();
        assert!(config.params.is_empty());
        assert!(config.db_path.is_none());
        assert!(config.as_objects);
    }

    #[test]
    fn test_duckdb_simple_query() {
        let tool = DuckdbTool::new();
        let result = tool
            .execute_query("SELECT 1 as num, 'hello' as msg", &[], None, true)
            .unwrap();

        assert!(result.is_success());
        let data = result.data.unwrap();
        assert_eq!(data["row_count"], 1);
        let rows = data["rows"].as_array().unwrap();
        assert_eq!(rows[0]["num"], 1);
        assert_eq!(rows[0]["msg"], "hello");
    }

    #[test]
    fn test_duckdb_with_params() {
        let tool = DuckdbTool::new();
        let params = vec![serde_json::json!(42), serde_json::json!("test")];
        let result = tool
            .execute_query("SELECT ? as num, ? as str", &params, None, true)
            .unwrap();

        assert!(result.is_success());
        let data = result.data.unwrap();
        let rows = data["rows"].as_array().unwrap();
        assert_eq!(rows[0]["num"], 42);
        assert_eq!(rows[0]["str"], "test");
    }

    #[test]
    fn test_duckdb_create_and_query() {
        // Use a temp file so the table persists across queries
        let tmp_dir = std::env::temp_dir();
        let db_path = tmp_dir.join("noetl_test_duckdb.db");
        let db_path_str = db_path.to_str().unwrap();

        // Clean up any existing test db
        let _ = std::fs::remove_file(&db_path);

        let tool = DuckdbTool::new();

        // Create table
        let result = tool
            .execute_query(
                "CREATE TABLE test (id INTEGER, name VARCHAR)",
                &[],
                Some(db_path_str),
                true,
            )
            .unwrap();
        assert!(result.is_success());

        // Insert data
        let result = tool
            .execute_query(
                "INSERT INTO test VALUES (1, 'Alice'), (2, 'Bob')",
                &[],
                Some(db_path_str),
                true,
            )
            .unwrap();
        assert!(result.is_success());

        // Clean up
        let _ = std::fs::remove_file(&db_path);
    }

    #[test]
    fn test_duckdb_as_arrays() {
        let tool = DuckdbTool::new();
        let result = tool
            .execute_query("SELECT 1, 2, 3", &[], None, false)
            .unwrap();

        assert!(result.is_success());
        let data = result.data.unwrap();
        let rows = data["rows"].as_array().unwrap();
        assert!(rows[0].is_array());
    }

    #[tokio::test]
    async fn test_duckdb_tool_interface() {
        let tool = DuckdbTool::new();
        assert_eq!(tool.name(), "duckdb");

        let config = ToolConfig {
            kind: "duckdb".to_string(),
            config: serde_json::json!({
                "query": "SELECT 42 as answer"
            }),
            timeout: None,
            retry: None,
            auth: None,
        };

        let ctx = ExecutionContext::default();
        let result = tool.execute(&config, &ctx).await.unwrap();
        assert!(result.is_success());
    }
}
