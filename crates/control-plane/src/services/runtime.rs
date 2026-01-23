//! Runtime management service.
//!
//! Provides operations for managing worker pools, API servers,
//! and brokers in the NoETL runtime.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::db::DbPool;
use crate::error::{AppError, AppResult};

/// Runtime kind.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeKind {
    WorkerPool,
    ServerApi,
    Broker,
}

impl RuntimeKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            RuntimeKind::WorkerPool => "worker_pool",
            RuntimeKind::ServerApi => "server_api",
            RuntimeKind::Broker => "broker",
        }
    }
}

impl std::str::FromStr for RuntimeKind {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "worker_pool" => Ok(RuntimeKind::WorkerPool),
            "server_api" => Ok(RuntimeKind::ServerApi),
            "broker" => Ok(RuntimeKind::Broker),
            _ => Err(format!("Unknown runtime kind: {}", s)),
        }
    }
}

/// Runtime entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Runtime {
    pub runtime_id: i64,
    pub name: String,
    pub kind: String,
    pub uri: Option<String>,
    pub status: String,
    pub labels: Option<serde_json::Value>,
    pub capabilities: Option<serde_json::Value>,
    pub capacity: Option<i32>,
    pub runtime: Option<serde_json::Value>,
    pub heartbeat: DateTime<Utc>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

/// Request to register a runtime.
#[derive(Debug, Clone, Deserialize)]
pub struct RegisterRuntimeRequest {
    pub name: String,
    pub kind: String,
    pub uri: Option<String>,
    #[serde(default = "default_status")]
    pub status: String,
    pub labels: Option<serde_json::Value>,
    pub capabilities: Option<serde_json::Value>,
    pub capacity: Option<i32>,
    pub runtime: Option<serde_json::Value>,
}

fn default_status() -> String {
    "active".to_string()
}

/// Filter for listing runtimes.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RuntimeFilter {
    pub kind: Option<String>,
    pub status: Option<String>,
    pub name: Option<String>,
}

/// Runtime management service.
#[derive(Clone)]
pub struct RuntimeService {
    db: DbPool,
}

impl RuntimeService {
    /// Create a new runtime service.
    pub fn new(db: DbPool) -> Self {
        Self { db }
    }

    /// Register a new runtime (worker pool, server, or broker).
    pub async fn register(&self, request: &RegisterRuntimeRequest) -> AppResult<Runtime> {
        // Validate kind
        let kind = match request.kind.as_str() {
            "worker_pool" | "server_api" | "broker" => request.kind.as_str(),
            _ => {
                return Err(AppError::Validation(format!(
                    "Invalid runtime kind: {}",
                    request.kind
                )))
            }
        };

        // Generate runtime_id
        let runtime_id: (i64,) = sqlx::query_as("SELECT noetl.snowflake_id()")
            .fetch_one(&self.db)
            .await?;

        let now = Utc::now();

        // Check if runtime with same kind and name exists
        let existing: Option<(i64,)> =
            sqlx::query_as("SELECT runtime_id FROM noetl.runtime WHERE kind = $1 AND name = $2")
                .bind(kind)
                .bind(&request.name)
                .fetch_optional(&self.db)
                .await?;

        if let Some((existing_id,)) = existing {
            // Update existing runtime
            sqlx::query(
                r#"
                UPDATE noetl.runtime SET
                    uri = $1,
                    status = $2,
                    labels = $3,
                    capabilities = $4,
                    capacity = $5,
                    runtime = $6,
                    heartbeat = $7,
                    updated_at = $7
                WHERE runtime_id = $8
                "#,
            )
            .bind(&request.uri)
            .bind(&request.status)
            .bind(&request.labels)
            .bind(&request.capabilities)
            .bind(request.capacity)
            .bind(&request.runtime)
            .bind(now)
            .bind(existing_id)
            .execute(&self.db)
            .await?;

            return self.get(existing_id).await;
        }

        // Insert new runtime
        sqlx::query(
            r#"
            INSERT INTO noetl.runtime (
                runtime_id, name, kind, uri, status,
                labels, capabilities, capacity, runtime,
                heartbeat, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10, $10)
            "#,
        )
        .bind(runtime_id.0)
        .bind(&request.name)
        .bind(kind)
        .bind(&request.uri)
        .bind(&request.status)
        .bind(&request.labels)
        .bind(&request.capabilities)
        .bind(request.capacity)
        .bind(&request.runtime)
        .bind(now)
        .execute(&self.db)
        .await?;

        self.get(runtime_id.0).await
    }

    /// Deregister a runtime.
    pub async fn deregister(&self, kind: &str, name: &str) -> AppResult<()> {
        let result = sqlx::query("DELETE FROM noetl.runtime WHERE kind = $1 AND name = $2")
            .bind(kind)
            .bind(name)
            .execute(&self.db)
            .await?;

        if result.rows_affected() == 0 {
            return Err(AppError::NotFound(format!(
                "Runtime not found: {} {}",
                kind, name
            )));
        }

        Ok(())
    }

    /// Update heartbeat for a runtime.
    pub async fn heartbeat(&self, kind: &str, name: &str) -> AppResult<()> {
        let result = sqlx::query(
            "UPDATE noetl.runtime SET heartbeat = NOW(), updated_at = NOW() WHERE kind = $1 AND name = $2",
        )
        .bind(kind)
        .bind(name)
        .execute(&self.db)
        .await?;

        if result.rows_affected() == 0 {
            return Err(AppError::NotFound(format!(
                "Runtime not found: {} {}",
                kind, name
            )));
        }

        Ok(())
    }

    /// Get a runtime by ID.
    #[allow(clippy::type_complexity)]
    pub async fn get(&self, runtime_id: i64) -> AppResult<Runtime> {
        let row: Option<(
            i64,
            String,
            String,
            Option<String>,
            String,
            Option<serde_json::Value>,
            Option<serde_json::Value>,
            Option<i32>,
            Option<serde_json::Value>,
            DateTime<Utc>,
            DateTime<Utc>,
            DateTime<Utc>,
        )> = sqlx::query_as(
            r#"
            SELECT runtime_id, name, kind, uri, status,
                   labels, capabilities, capacity, runtime,
                   heartbeat, created_at, updated_at
            FROM noetl.runtime
            WHERE runtime_id = $1
            "#,
        )
        .bind(runtime_id)
        .fetch_optional(&self.db)
        .await?;

        match row {
            Some((
                runtime_id,
                name,
                kind,
                uri,
                status,
                labels,
                capabilities,
                capacity,
                runtime,
                heartbeat,
                created_at,
                updated_at,
            )) => Ok(Runtime {
                runtime_id,
                name,
                kind,
                uri,
                status,
                labels,
                capabilities,
                capacity,
                runtime,
                heartbeat,
                created_at,
                updated_at,
            }),
            None => Err(AppError::NotFound(format!(
                "Runtime not found: {}",
                runtime_id
            ))),
        }
    }

    /// List runtimes with optional filters.
    #[allow(clippy::type_complexity)]
    pub async fn list(&self, filter: &RuntimeFilter) -> AppResult<Vec<Runtime>> {
        let rows: Vec<(
            i64,
            String,
            String,
            Option<String>,
            String,
            Option<serde_json::Value>,
            Option<serde_json::Value>,
            Option<i32>,
            Option<serde_json::Value>,
            DateTime<Utc>,
            DateTime<Utc>,
            DateTime<Utc>,
        )> = sqlx::query_as(
            r#"
            SELECT runtime_id, name, kind, uri, status,
                   labels, capabilities, capacity, runtime,
                   heartbeat, created_at, updated_at
            FROM noetl.runtime
            WHERE ($1::TEXT IS NULL OR kind = $1)
              AND ($2::TEXT IS NULL OR status = $2)
              AND ($3::TEXT IS NULL OR name LIKE $3)
            ORDER BY kind, name
            "#,
        )
        .bind(&filter.kind)
        .bind(&filter.status)
        .bind(filter.name.as_ref().map(|n| format!("%{}%", n)))
        .fetch_all(&self.db)
        .await?;

        Ok(rows
            .into_iter()
            .map(
                |(
                    runtime_id,
                    name,
                    kind,
                    uri,
                    status,
                    labels,
                    capabilities,
                    capacity,
                    runtime,
                    heartbeat,
                    created_at,
                    updated_at,
                )| {
                    Runtime {
                        runtime_id,
                        name,
                        kind,
                        uri,
                        status,
                        labels,
                        capabilities,
                        capacity,
                        runtime,
                        heartbeat,
                        created_at,
                        updated_at,
                    }
                },
            )
            .collect())
    }

    /// List worker pools specifically.
    pub async fn list_worker_pools(&self) -> AppResult<Vec<Runtime>> {
        self.list(&RuntimeFilter {
            kind: Some("worker_pool".to_string()),
            ..Default::default()
        })
        .await
    }

    /// Update runtime status.
    pub async fn update_status(&self, runtime_id: i64, status: &str) -> AppResult<()> {
        let result = sqlx::query(
            "UPDATE noetl.runtime SET status = $1, updated_at = NOW() WHERE runtime_id = $2",
        )
        .bind(status)
        .bind(runtime_id)
        .execute(&self.db)
        .await?;

        if result.rows_affected() == 0 {
            return Err(AppError::NotFound(format!(
                "Runtime not found: {}",
                runtime_id
            )));
        }

        Ok(())
    }

    /// Clean up stale runtimes (no heartbeat for given duration).
    pub async fn cleanup_stale(&self, stale_after_seconds: i64) -> AppResult<i64> {
        let result = sqlx::query(
            r#"
            DELETE FROM noetl.runtime
            WHERE heartbeat < NOW() - INTERVAL '1 second' * $1
            "#,
        )
        .bind(stale_after_seconds)
        .execute(&self.db)
        .await?;

        Ok(result.rows_affected() as i64)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_runtime_kind_from_str() {
        assert!(matches!(
            "worker_pool".parse::<RuntimeKind>().unwrap(),
            RuntimeKind::WorkerPool
        ));
        assert!(matches!(
            "server_api".parse::<RuntimeKind>().unwrap(),
            RuntimeKind::ServerApi
        ));
        assert!("invalid".parse::<RuntimeKind>().is_err());
    }

    #[test]
    fn test_runtime_kind_as_str() {
        assert_eq!(RuntimeKind::WorkerPool.as_str(), "worker_pool");
        assert_eq!(RuntimeKind::ServerApi.as_str(), "server_api");
        assert_eq!(RuntimeKind::Broker.as_str(), "broker");
    }

    #[test]
    fn test_runtime_serialization() {
        let runtime = Runtime {
            runtime_id: 12345,
            name: "worker-1".to_string(),
            kind: "worker_pool".to_string(),
            uri: Some("http://localhost:8080".to_string()),
            status: "active".to_string(),
            labels: Some(serde_json::json!({"env": "dev"})),
            capabilities: Some(serde_json::json!(["python", "http"])),
            capacity: Some(10),
            runtime: None,
            heartbeat: Utc::now(),
            created_at: Utc::now(),
            updated_at: Utc::now(),
        };

        let json = serde_json::to_string(&runtime).unwrap();
        assert!(json.contains("worker-1"));
        assert!(json.contains("worker_pool"));
    }

    #[test]
    fn test_register_request_defaults() {
        let json = r#"{"name": "worker-1", "kind": "worker_pool"}"#;
        let request: RegisterRuntimeRequest = serde_json::from_str(json).unwrap();
        assert_eq!(request.status, "active");
    }

    #[test]
    fn test_runtime_filter_default() {
        let filter = RuntimeFilter::default();
        assert!(filter.kind.is_none());
        assert!(filter.status.is_none());
    }
}
