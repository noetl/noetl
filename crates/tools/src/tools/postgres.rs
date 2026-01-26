//! PostgreSQL query execution tool.

use async_trait::async_trait;
use deadpool_postgres::{Config, Pool, Runtime};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use tokio_postgres::types::ToSql;
use tokio_postgres::NoTls;

use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::registry::{Tool, ToolConfig};
use crate::result::ToolResult;
use crate::template::TemplateEngine;

/// PostgreSQL tool configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PostgresConfig {
    /// SQL query to execute.
    pub query: String,

    /// Query parameters.
    #[serde(default)]
    pub params: Vec<serde_json::Value>,

    /// Connection string (e.g., "postgresql://user:pass@host/db").
    #[serde(skip_serializing_if = "Option::is_none")]
    pub connection_string: Option<String>,

    /// Host (alternative to connection_string).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub host: Option<String>,

    /// Port (default: 5432).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub port: Option<u16>,

    /// Database name.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub database: Option<String>,

    /// Username.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub user: Option<String>,

    /// Password (or credential name).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub password: Option<String>,

    /// Schema to set search_path.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub schema: Option<String>,

    /// Whether to return results as JSON objects (default: true).
    #[serde(default = "default_as_objects")]
    pub as_objects: bool,
}

fn default_as_objects() -> bool {
    true
}

/// PostgreSQL query execution tool.
pub struct PostgresTool {
    /// Connection pools keyed by connection string.
    pools: Arc<RwLock<HashMap<String, Pool>>>,
    template_engine: TemplateEngine,
}

impl PostgresTool {
    /// Create a new PostgreSQL tool.
    pub fn new() -> Self {
        Self {
            pools: Arc::new(RwLock::new(HashMap::new())),
            template_engine: TemplateEngine::new(),
        }
    }

    /// Get or create a connection pool for the given connection string.
    async fn get_pool(&self, connection_string: &str) -> Result<Pool, ToolError> {
        // Check if pool exists
        {
            let pools = self.pools.read().await;
            if let Some(pool) = pools.get(connection_string) {
                return Ok(pool.clone());
            }
        }

        // Create new pool
        let mut config = Config::new();
        config.url = Some(connection_string.to_string());

        let pool = config
            .create_pool(Some(Runtime::Tokio1), NoTls)
            .map_err(|e| ToolError::Database(format!("Failed to create pool: {}", e)))?;

        // Store pool
        {
            let mut pools = self.pools.write().await;
            pools.insert(connection_string.to_string(), pool.clone());
        }

        Ok(pool)
    }

    /// Build connection string from config.
    fn build_connection_string(&self, config: &PostgresConfig, ctx: &ExecutionContext) -> Result<String, ToolError> {
        if let Some(ref conn_str) = config.connection_string {
            return Ok(conn_str.clone());
        }

        let host = config.host.as_deref().unwrap_or("localhost");
        let port = config.port.unwrap_or(5432);
        let database = config.database.as_deref().unwrap_or("postgres");
        let user = config.user.as_deref().unwrap_or("postgres");

        // Try to get password from secrets or config
        let password = if let Some(ref pw) = config.password {
            // Check if it's a credential reference
            ctx.get_secret(pw).map(|s| s.to_string()).unwrap_or_else(|| pw.clone())
        } else {
            String::new()
        };

        let conn_str = if password.is_empty() {
            format!("postgresql://{}@{}:{}/{}", user, host, port, database)
        } else {
            format!("postgresql://{}:{}@{}:{}/{}", user, password, host, port, database)
        };

        Ok(conn_str)
    }

    /// Execute a query and return results.
    pub async fn execute_query(
        &self,
        query: &str,
        params: &[serde_json::Value],
        connection_string: &str,
        schema: Option<&str>,
        as_objects: bool,
    ) -> Result<ToolResult, ToolError> {
        let start = std::time::Instant::now();

        let pool = self.get_pool(connection_string).await?;
        let client = pool
            .get()
            .await
            .map_err(|e| ToolError::Database(format!("Failed to get connection: {}", e)))?;

        // Set search_path if schema specified
        if let Some(schema) = schema {
            client
                .execute(&format!("SET search_path TO {}", schema), &[])
                .await
                .map_err(|e| ToolError::Database(format!("Failed to set schema: {}", e)))?;
        }

        // Convert params
        let pg_params: Vec<Box<dyn ToSql + Sync + Send>> = params
            .iter()
            .map(|v| json_to_pg_param(v))
            .collect();

        let param_refs: Vec<&(dyn ToSql + Sync)> = pg_params
            .iter()
            .map(|p| p.as_ref() as &(dyn ToSql + Sync))
            .collect();

        // Check if it's a SELECT query
        let is_select = query.trim().to_uppercase().starts_with("SELECT")
            || query.trim().to_uppercase().starts_with("WITH");

        let result = if is_select {
            // Execute query with results
            let rows = client
                .query(query, &param_refs)
                .await
                .map_err(|e| ToolError::Database(format!("Query failed: {}", e)))?;

            if rows.is_empty() {
                serde_json::json!({
                    "columns": [],
                    "rows": [],
                    "row_count": 0
                })
            } else {
                // Get column names
                let columns: Vec<String> = rows[0]
                    .columns()
                    .iter()
                    .map(|c| c.name().to_string())
                    .collect();

                // Convert rows to JSON
                let json_rows: Vec<serde_json::Value> = rows
                    .iter()
                    .map(|row| {
                        if as_objects {
                            let mut obj = serde_json::Map::new();
                            for (i, col) in row.columns().iter().enumerate() {
                                let value = pg_value_to_json(row, i);
                                obj.insert(col.name().to_string(), value);
                            }
                            serde_json::Value::Object(obj)
                        } else {
                            let values: Vec<serde_json::Value> = (0..row.columns().len())
                                .map(|i| pg_value_to_json(row, i))
                                .collect();
                            serde_json::Value::Array(values)
                        }
                    })
                    .collect();

                serde_json::json!({
                    "columns": columns,
                    "rows": json_rows,
                    "row_count": json_rows.len()
                })
            }
        } else {
            // Execute without results
            let affected = client
                .execute(query, &param_refs)
                .await
                .map_err(|e| ToolError::Database(format!("Execute failed: {}", e)))?;

            serde_json::json!({
                "affected_rows": affected
            })
        };

        let duration_ms = start.elapsed().as_millis() as u64;

        Ok(ToolResult::success(result).with_duration(duration_ms))
    }

    /// Parse PostgreSQL config from tool config.
    fn parse_config(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<PostgresConfig, ToolError> {
        let template_ctx = ctx.to_template_context();
        let rendered_config = self.template_engine.render_value(&config.config, &template_ctx)?;

        serde_json::from_value(rendered_config)
            .map_err(|e| ToolError::Configuration(format!("Invalid postgres config: {}", e)))
    }
}

impl Default for PostgresTool {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for PostgresTool {
    fn name(&self) -> &'static str {
        "postgres"
    }

    async fn execute(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let pg_config = self.parse_config(config, ctx)?;
        let connection_string = self.build_connection_string(&pg_config, ctx)?;

        tracing::debug!(
            query = %pg_config.query,
            params_count = pg_config.params.len(),
            schema = ?pg_config.schema,
            "Executing PostgreSQL query"
        );

        self.execute_query(
            &pg_config.query,
            &pg_config.params,
            &connection_string,
            pg_config.schema.as_deref(),
            pg_config.as_objects,
        )
        .await
    }
}

/// Convert JSON value to PostgreSQL parameter.
fn json_to_pg_param(value: &serde_json::Value) -> Box<dyn ToSql + Sync + Send> {
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

/// Convert PostgreSQL row value to JSON.
fn pg_value_to_json(row: &tokio_postgres::Row, idx: usize) -> serde_json::Value {
    // Try different types
    if let Ok(v) = row.try_get::<_, Option<i64>>(idx) {
        return v.map(|n| serde_json::json!(n)).unwrap_or(serde_json::Value::Null);
    }
    if let Ok(v) = row.try_get::<_, Option<i32>>(idx) {
        return v.map(|n| serde_json::json!(n)).unwrap_or(serde_json::Value::Null);
    }
    if let Ok(v) = row.try_get::<_, Option<f64>>(idx) {
        return v.map(|n| serde_json::json!(n)).unwrap_or(serde_json::Value::Null);
    }
    if let Ok(v) = row.try_get::<_, Option<bool>>(idx) {
        return v.map(|b| serde_json::json!(b)).unwrap_or(serde_json::Value::Null);
    }
    if let Ok(v) = row.try_get::<_, Option<String>>(idx) {
        return v.map(|s| serde_json::json!(s)).unwrap_or(serde_json::Value::Null);
    }
    if let Ok(v) = row.try_get::<_, Option<serde_json::Value>>(idx) {
        return v.unwrap_or(serde_json::Value::Null);
    }
    if let Ok(v) = row.try_get::<_, Option<chrono::DateTime<chrono::Utc>>>(idx) {
        return v
            .map(|dt| serde_json::json!(dt.to_rfc3339()))
            .unwrap_or(serde_json::Value::Null);
    }

    serde_json::Value::Null
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_postgres_config_deserialization() {
        let json = serde_json::json!({
            "query": "SELECT * FROM users WHERE id = $1",
            "params": [42],
            "connection_string": "postgresql://user:pass@localhost/db"
        });

        let config: PostgresConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.query, "SELECT * FROM users WHERE id = $1");
        assert_eq!(config.params.len(), 1);
        assert!(config.connection_string.is_some());
    }

    #[test]
    fn test_postgres_config_with_components() {
        let json = serde_json::json!({
            "query": "SELECT 1",
            "host": "db.example.com",
            "port": 5433,
            "database": "mydb",
            "user": "admin",
            "schema": "public"
        });

        let config: PostgresConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.host, Some("db.example.com".to_string()));
        assert_eq!(config.port, Some(5433));
        assert_eq!(config.database, Some("mydb".to_string()));
    }

    #[test]
    fn test_postgres_config_defaults() {
        let json = serde_json::json!({
            "query": "SELECT 1"
        });

        let config: PostgresConfig = serde_json::from_value(json).unwrap();
        assert!(config.params.is_empty());
        assert!(config.connection_string.is_none());
        assert!(config.as_objects);
    }

    #[test]
    fn test_build_connection_string() {
        let tool = PostgresTool::new();
        let ctx = ExecutionContext::default();

        let config = PostgresConfig {
            query: "SELECT 1".to_string(),
            params: vec![],
            connection_string: None,
            host: Some("localhost".to_string()),
            port: Some(5432),
            database: Some("testdb".to_string()),
            user: Some("testuser".to_string()),
            password: Some("testpass".to_string()),
            schema: None,
            as_objects: true,
        };

        let conn_str = tool.build_connection_string(&config, &ctx).unwrap();
        assert!(conn_str.contains("localhost"));
        assert!(conn_str.contains("testdb"));
        assert!(conn_str.contains("testuser"));
    }

    #[tokio::test]
    async fn test_postgres_tool_interface() {
        let tool = PostgresTool::new();
        assert_eq!(tool.name(), "postgres");
    }
}
