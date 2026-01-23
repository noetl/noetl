//! Execution management service.
//!
//! Provides operations for managing playbook executions,
//! including listing, status queries, cancellation, and finalization.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::db::DbPool;
use crate::error::{AppError, AppResult};

/// Execution summary for listing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionSummary {
    pub execution_id: i64,
    pub catalog_id: i64,
    pub path: Option<String>,
    pub status: String,
    pub started_at: DateTime<Utc>,
    pub completed_at: Option<DateTime<Utc>>,
    pub event_count: i64,
}

/// Detailed execution information.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionDetail {
    pub execution_id: i64,
    pub catalog_id: i64,
    pub path: Option<String>,
    pub status: String,
    pub started_at: DateTime<Utc>,
    pub completed_at: Option<DateTime<Utc>>,
    pub parent_execution_id: Option<i64>,
    pub workload: Option<serde_json::Value>,
    pub events: Vec<ExecutionEvent>,
}

/// Event in an execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionEvent {
    pub event_id: i64,
    pub event_type: String,
    pub node_name: Option<String>,
    pub status: String,
    pub created_at: DateTime<Utc>,
    pub result: Option<serde_json::Value>,
    pub error: Option<String>,
}

/// Execution status response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionStatus {
    pub execution_id: i64,
    pub status: String,
    pub current_step: Option<String>,
    pub progress: ExecutionProgress,
    pub is_cancelled: bool,
}

/// Execution progress information.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionProgress {
    pub total_steps: i32,
    pub completed_steps: i32,
    pub running_steps: i32,
    pub failed_steps: i32,
}

/// Filter for listing executions.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ExecutionFilter {
    pub catalog_id: Option<i64>,
    pub path: Option<String>,
    pub status: Option<String>,
    pub limit: Option<i32>,
    pub offset: Option<i32>,
}

/// Execution management service.
#[derive(Clone)]
pub struct ExecutionService {
    db: DbPool,
}

impl ExecutionService {
    /// Create a new execution service.
    pub fn new(db: DbPool) -> Self {
        Self { db }
    }

    /// List executions with optional filters.
    #[allow(clippy::type_complexity)]
    pub async fn list(&self, filter: &ExecutionFilter) -> AppResult<Vec<ExecutionSummary>> {
        let limit = filter.limit.unwrap_or(50).min(100);
        let offset = filter.offset.unwrap_or(0);

        let rows: Vec<(i64, i64, Option<String>, String, DateTime<Utc>, Option<DateTime<Utc>>, i64)> =
            sqlx::query_as(
                r#"
                WITH execution_stats AS (
                    SELECT
                        execution_id,
                        catalog_id,
                        MIN(created_at) as started_at,
                        MAX(CASE WHEN status IN ('COMPLETED', 'FAILED', 'CANCELLED') THEN created_at END) as completed_at,
                        COUNT(*) as event_count,
                        MAX(CASE
                            WHEN event_type = 'playbook_completed' THEN 'COMPLETED'
                            WHEN event_type = 'playbook_failed' THEN 'FAILED'
                            WHEN event_type = 'playbook_cancelled' THEN 'CANCELLED'
                            WHEN status = 'FAILED' THEN 'FAILED'
                            ELSE 'RUNNING'
                        END) as status
                    FROM noetl.event
                    WHERE ($1::BIGINT IS NULL OR catalog_id = $1)
                    GROUP BY execution_id, catalog_id
                )
                SELECT
                    e.execution_id,
                    e.catalog_id,
                    c.path,
                    e.status,
                    e.started_at,
                    e.completed_at,
                    e.event_count
                FROM execution_stats e
                LEFT JOIN noetl.catalog c ON e.catalog_id = c.catalog_id
                WHERE ($2::TEXT IS NULL OR c.path LIKE $2)
                  AND ($3::TEXT IS NULL OR e.status = $3)
                ORDER BY e.started_at DESC
                LIMIT $4 OFFSET $5
                "#,
            )
            .bind(filter.catalog_id)
            .bind(filter.path.as_ref().map(|p| format!("%{}%", p)))
            .bind(&filter.status)
            .bind(limit)
            .bind(offset)
            .fetch_all(&self.db)
            .await?;

        Ok(rows
            .into_iter()
            .map(
                |(
                    execution_id,
                    catalog_id,
                    path,
                    status,
                    started_at,
                    completed_at,
                    event_count,
                )| {
                    ExecutionSummary {
                        execution_id,
                        catalog_id,
                        path,
                        status,
                        started_at,
                        completed_at,
                        event_count,
                    }
                },
            )
            .collect())
    }

    /// Get detailed execution information.
    #[allow(clippy::type_complexity)]
    pub async fn get(&self, execution_id: i64) -> AppResult<ExecutionDetail> {
        // Get basic execution info from first event
        let info: Option<(i64, Option<i64>, Option<serde_json::Value>, DateTime<Utc>)> =
            sqlx::query_as(
                r#"
                SELECT
                    catalog_id,
                    parent_execution_id,
                    context->'workload' as workload,
                    created_at
                FROM noetl.event
                WHERE execution_id = $1 AND event_type = 'playbook_started'
                LIMIT 1
                "#,
            )
            .bind(execution_id)
            .fetch_optional(&self.db)
            .await?;

        let (catalog_id, parent_execution_id, workload, started_at) = info
            .ok_or_else(|| AppError::NotFound(format!("Execution not found: {}", execution_id)))?;

        // Get catalog path
        let path: Option<(String,)> =
            sqlx::query_as("SELECT path FROM noetl.catalog WHERE catalog_id = $1")
                .bind(catalog_id)
                .fetch_optional(&self.db)
                .await?;

        // Get all events for this execution
        let event_rows: Vec<(
            i64,
            String,
            Option<String>,
            String,
            DateTime<Utc>,
            Option<serde_json::Value>,
            Option<String>,
        )> = sqlx::query_as(
            r#"
                SELECT
                    event_id,
                    event_type,
                    node_name,
                    COALESCE(status, 'UNKNOWN') as status,
                    created_at,
                    result,
                    error
                FROM noetl.event
                WHERE execution_id = $1
                ORDER BY created_at ASC
                "#,
        )
        .bind(execution_id)
        .fetch_all(&self.db)
        .await?;

        let events: Vec<ExecutionEvent> = event_rows
            .into_iter()
            .map(
                |(event_id, event_type, node_name, status, created_at, result, error)| {
                    ExecutionEvent {
                        event_id,
                        event_type,
                        node_name,
                        status,
                        created_at,
                        result,
                        error,
                    }
                },
            )
            .collect();

        // Determine overall status
        let status = self.determine_status(&events);

        // Get completion time
        let completed_at = events
            .iter()
            .filter(|e| {
                e.event_type == "playbook_completed"
                    || e.event_type == "playbook_failed"
                    || e.event_type == "playbook_cancelled"
            })
            .map(|e| e.created_at)
            .max();

        Ok(ExecutionDetail {
            execution_id,
            catalog_id,
            path: path.map(|(p,)| p),
            status,
            started_at,
            completed_at,
            parent_execution_id,
            workload,
            events,
        })
    }

    /// Get execution status.
    pub async fn get_status(&self, execution_id: i64) -> AppResult<ExecutionStatus> {
        // Check if execution exists
        let exists: Option<(i64,)> =
            sqlx::query_as("SELECT execution_id FROM noetl.event WHERE execution_id = $1 LIMIT 1")
                .bind(execution_id)
                .fetch_optional(&self.db)
                .await?;

        if exists.is_none() {
            return Err(AppError::NotFound(format!(
                "Execution not found: {}",
                execution_id
            )));
        }

        // Get step statistics
        let stats: (i64, i64, i64, i64) = sqlx::query_as(
            r#"
            SELECT
                COUNT(DISTINCT CASE WHEN event_type = 'step.enter' THEN node_name END) as total_steps,
                COUNT(DISTINCT CASE WHEN event_type IN ('step.exit', 'command.completed') AND status = 'COMPLETED' THEN node_name END) as completed_steps,
                COUNT(DISTINCT CASE WHEN event_type IN ('step.enter', 'command.started') AND status = 'RUNNING' THEN node_name END) as running_steps,
                COUNT(DISTINCT CASE WHEN status = 'FAILED' THEN node_name END) as failed_steps
            FROM noetl.event
            WHERE execution_id = $1
            "#,
        )
        .bind(execution_id)
        .fetch_one(&self.db)
        .await?;

        // Get current step
        let current_step: Option<(String,)> = sqlx::query_as(
            r#"
            SELECT node_name
            FROM noetl.event
            WHERE execution_id = $1
              AND event_type IN ('step.enter', 'command.started')
              AND node_name IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            "#,
        )
        .bind(execution_id)
        .fetch_optional(&self.db)
        .await?;

        // Check for cancellation
        let is_cancelled: bool = sqlx::query_scalar(
            r#"
            SELECT EXISTS(
                SELECT 1 FROM noetl.event
                WHERE execution_id = $1
                  AND event_type = 'playbook_cancelled'
            )
            "#,
        )
        .bind(execution_id)
        .fetch_one(&self.db)
        .await?;

        // Determine overall status
        let status = if is_cancelled {
            "CANCELLED".to_string()
        } else if stats.3 > 0 {
            "FAILED".to_string()
        } else if stats.1 == stats.0 && stats.0 > 0 {
            "COMPLETED".to_string()
        } else {
            "RUNNING".to_string()
        };

        Ok(ExecutionStatus {
            execution_id,
            status,
            current_step: current_step.map(|(s,)| s),
            progress: ExecutionProgress {
                total_steps: stats.0 as i32,
                completed_steps: stats.1 as i32,
                running_steps: stats.2 as i32,
                failed_steps: stats.3 as i32,
            },
            is_cancelled,
        })
    }

    /// Cancel an execution.
    pub async fn cancel(&self, execution_id: i64) -> AppResult<()> {
        // Check if execution exists and is running
        let status = self.get_status(execution_id).await?;

        if status.status == "COMPLETED" || status.status == "FAILED" || status.status == "CANCELLED"
        {
            return Err(AppError::Validation(format!(
                "Cannot cancel execution in {} state",
                status.status
            )));
        }

        // Get catalog_id for the event
        let catalog_id: Option<(i64,)> =
            sqlx::query_as("SELECT catalog_id FROM noetl.event WHERE execution_id = $1 LIMIT 1")
                .bind(execution_id)
                .fetch_optional(&self.db)
                .await?;

        let catalog_id = catalog_id
            .ok_or_else(|| AppError::NotFound(format!("Execution not found: {}", execution_id)))?
            .0;

        // Generate event ID
        let event_id: (i64,) = sqlx::query_as("SELECT noetl.snowflake_id()")
            .fetch_one(&self.db)
            .await?;

        // Insert cancellation event
        sqlx::query(
            r#"
            INSERT INTO noetl.event (
                event_id, execution_id, catalog_id, event_type,
                node_id, node_name, status, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            "#,
        )
        .bind(event_id.0)
        .bind(execution_id)
        .bind(catalog_id)
        .bind("playbook_cancelled")
        .bind("playbook")
        .bind("playbook")
        .bind("CANCELLED")
        .bind(Utc::now())
        .execute(&self.db)
        .await?;

        Ok(())
    }

    /// Check if an execution is cancelled.
    pub async fn is_cancelled(&self, execution_id: i64) -> AppResult<bool> {
        let is_cancelled: bool = sqlx::query_scalar(
            r#"
            SELECT EXISTS(
                SELECT 1 FROM noetl.event
                WHERE execution_id = $1
                  AND event_type = 'playbook_cancelled'
            )
            "#,
        )
        .bind(execution_id)
        .fetch_one(&self.db)
        .await?;

        Ok(is_cancelled)
    }

    /// Finalize an execution (mark as completed or failed).
    pub async fn finalize(
        &self,
        execution_id: i64,
        status: &str,
        error: Option<&str>,
    ) -> AppResult<()> {
        // Validate status
        if status != "COMPLETED" && status != "FAILED" {
            return Err(AppError::Validation(format!(
                "Invalid finalization status: {}",
                status
            )));
        }

        // Get catalog_id
        let catalog_id: Option<(i64,)> =
            sqlx::query_as("SELECT catalog_id FROM noetl.event WHERE execution_id = $1 LIMIT 1")
                .bind(execution_id)
                .fetch_optional(&self.db)
                .await?;

        let catalog_id = catalog_id
            .ok_or_else(|| AppError::NotFound(format!("Execution not found: {}", execution_id)))?
            .0;

        // Generate event ID
        let event_id: (i64,) = sqlx::query_as("SELECT noetl.snowflake_id()")
            .fetch_one(&self.db)
            .await?;

        let event_type = if status == "COMPLETED" {
            "playbook_completed"
        } else {
            "playbook_failed"
        };

        // Insert finalization event
        sqlx::query(
            r#"
            INSERT INTO noetl.event (
                event_id, execution_id, catalog_id, event_type,
                node_id, node_name, status, error, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            "#,
        )
        .bind(event_id.0)
        .bind(execution_id)
        .bind(catalog_id)
        .bind(event_type)
        .bind("playbook")
        .bind("playbook")
        .bind(status)
        .bind(error)
        .bind(Utc::now())
        .execute(&self.db)
        .await?;

        Ok(())
    }

    /// Determine execution status from events.
    fn determine_status(&self, events: &[ExecutionEvent]) -> String {
        for event in events.iter().rev() {
            match event.event_type.as_str() {
                "playbook_completed" => return "COMPLETED".to_string(),
                "playbook_failed" => return "FAILED".to_string(),
                "playbook_cancelled" => return "CANCELLED".to_string(),
                _ => {}
            }
            if event.status == "FAILED" {
                return "FAILED".to_string();
            }
        }
        "RUNNING".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_execution_summary_serialization() {
        let summary = ExecutionSummary {
            execution_id: 12345,
            catalog_id: 67890,
            path: Some("test/playbook".to_string()),
            status: "RUNNING".to_string(),
            started_at: Utc::now(),
            completed_at: None,
            event_count: 5,
        };

        let json = serde_json::to_string(&summary).unwrap();
        assert!(json.contains("12345"));
        assert!(json.contains("RUNNING"));
    }

    #[test]
    fn test_execution_status_serialization() {
        let status = ExecutionStatus {
            execution_id: 12345,
            status: "RUNNING".to_string(),
            current_step: Some("process_data".to_string()),
            progress: ExecutionProgress {
                total_steps: 5,
                completed_steps: 2,
                running_steps: 1,
                failed_steps: 0,
            },
            is_cancelled: false,
        };

        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("process_data"));
        assert!(json.contains("total_steps"));
    }

    #[test]
    fn test_execution_filter_default() {
        let filter = ExecutionFilter::default();
        assert!(filter.catalog_id.is_none());
        assert!(filter.limit.is_none());
    }
}
