//! Dashboard API handlers.
//!
//! Provides endpoints for dashboard statistics and widget configuration.

use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};

use crate::db::DbPool;
use crate::error::AppError;

/// Dashboard statistics.
#[derive(Debug, Clone, Serialize)]
pub struct DashboardStats {
    /// Total number of executions.
    pub total_executions: i64,

    /// Number of successful executions.
    pub successful_executions: i64,

    /// Number of failed executions.
    pub failed_executions: i64,

    /// Number of cancelled executions.
    pub cancelled_executions: i64,

    /// Number of running executions.
    pub running_executions: i64,

    /// Total registered playbooks in catalog.
    pub total_playbooks: i64,

    /// Number of registered workers.
    pub total_workers: i64,
}

/// Response for dashboard statistics.
#[derive(Debug, Clone, Serialize)]
pub struct DashboardStatsResponse {
    /// Response status.
    pub status: String,

    /// Dashboard statistics.
    pub stats: DashboardStats,
}

/// Dashboard widget configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Widget {
    /// Unique widget identifier.
    pub id: String,

    /// Widget type (chart, table, metric, etc.).
    #[serde(rename = "type")]
    pub widget_type: String,

    /// Widget title.
    pub title: String,

    /// Widget configuration.
    pub config: serde_json::Value,

    /// Widget data.
    pub data: serde_json::Value,
}

/// Response for dashboard widgets.
#[derive(Debug, Clone, Serialize)]
pub struct DashboardWidgetsResponse {
    /// List of configured widgets.
    pub widgets: Vec<Widget>,
}

/// Get dashboard statistics.
///
/// GET /api/dashboard/stats
///
/// Returns aggregate statistics for the dashboard.
pub async fn get_stats(State(db): State<DbPool>) -> Result<Json<DashboardStatsResponse>, AppError> {
    let schema = std::env::var("NOETL_SCHEMA").unwrap_or_else(|_| "noetl".to_string());

    // Count total executions by status from event table
    let total_executions: i64 = sqlx::query_scalar(&format!(
        "SELECT COUNT(DISTINCT payload->>'execution_id')
         FROM {}.event
         WHERE event_type = 'execution.started'",
        schema
    ))
    .fetch_one(&db)
    .await
    .unwrap_or(0);

    let successful_executions: i64 = sqlx::query_scalar(&format!(
        "SELECT COUNT(DISTINCT payload->>'execution_id')
         FROM {}.event
         WHERE event_type = 'execution.completed'
         AND payload->>'status' = 'COMPLETED'",
        schema
    ))
    .fetch_one(&db)
    .await
    .unwrap_or(0);

    let failed_executions: i64 = sqlx::query_scalar(&format!(
        "SELECT COUNT(DISTINCT payload->>'execution_id')
         FROM {}.event
         WHERE event_type = 'execution.completed'
         AND payload->>'status' = 'FAILED'",
        schema
    ))
    .fetch_one(&db)
    .await
    .unwrap_or(0);

    let cancelled_executions: i64 = sqlx::query_scalar(&format!(
        "SELECT COUNT(DISTINCT payload->>'execution_id')
         FROM {}.event
         WHERE event_type = 'execution.completed'
         AND payload->>'status' = 'CANCELLED'",
        schema
    ))
    .fetch_one(&db)
    .await
    .unwrap_or(0);

    // Running executions = started but not completed
    let running_executions: i64 = sqlx::query_scalar(&format!(
        "SELECT COUNT(*) FROM (
            SELECT DISTINCT payload->>'execution_id' as exec_id
            FROM {schema}.event
            WHERE event_type = 'execution.started'
            EXCEPT
            SELECT DISTINCT payload->>'execution_id' as exec_id
            FROM {schema}.event
            WHERE event_type = 'execution.completed'
        ) as running",
        schema = schema
    ))
    .fetch_one(&db)
    .await
    .unwrap_or(0);

    // Count playbooks in catalog
    let total_playbooks: i64 = sqlx::query_scalar(&format!(
        "SELECT COUNT(*) FROM {}.catalog WHERE kind = 'playbook'",
        schema
    ))
    .fetch_one(&db)
    .await
    .unwrap_or(0);

    // Count active workers
    let total_workers: i64 = sqlx::query_scalar(&format!(
        "SELECT COUNT(*) FROM {}.runtime WHERE kind = 'worker_pool' AND status = 'active'",
        schema
    ))
    .fetch_one(&db)
    .await
    .unwrap_or(0);

    let stats = DashboardStats {
        total_executions,
        successful_executions,
        failed_executions,
        cancelled_executions,
        running_executions,
        total_playbooks,
        total_workers,
    };

    Ok(Json(DashboardStatsResponse {
        status: "ok".to_string(),
        stats,
    }))
}

/// Get dashboard widgets configuration.
///
/// GET /api/dashboard/widgets
///
/// Returns configured dashboard widgets with their data.
pub async fn get_widgets(
    State(db): State<DbPool>,
) -> Result<Json<DashboardWidgetsResponse>, AppError> {
    let schema = std::env::var("NOETL_SCHEMA").unwrap_or_else(|_| "noetl".to_string());

    // Build execution trend data for the last 7 days
    let trend_data: Vec<(chrono::NaiveDate, i64)> = sqlx::query_as(&format!(
        "SELECT DATE(created_at) as day, COUNT(DISTINCT payload->>'execution_id') as count
         FROM {}.event
         WHERE event_type = 'execution.started'
         AND created_at > NOW() - INTERVAL '7 days'
         GROUP BY DATE(created_at)
         ORDER BY day",
        schema
    ))
    .fetch_all(&db)
    .await
    .unwrap_or_default();

    let trend_widget = Widget {
        id: "execution-trend".to_string(),
        widget_type: "chart".to_string(),
        title: "Execution Trend (7 days)".to_string(),
        config: serde_json::json!({
            "chart_type": "line",
            "time_range": "7d"
        }),
        data: serde_json::json!(trend_data
            .iter()
            .map(|(day, count)| {
                serde_json::json!({
                    "date": day.to_string(),
                    "count": count
                })
            })
            .collect::<Vec<_>>()),
    };

    // Recent executions widget
    let recent_executions: Vec<(i64, String, String)> = sqlx::query_as(&format!(
        "SELECT
            (payload->>'execution_id')::bigint as execution_id,
            payload->>'path' as path,
            payload->>'status' as status
         FROM {}.event
         WHERE event_type IN ('execution.started', 'execution.completed')
         ORDER BY created_at DESC
         LIMIT 10",
        schema
    ))
    .fetch_all(&db)
    .await
    .unwrap_or_default();

    let recent_widget = Widget {
        id: "recent-executions".to_string(),
        widget_type: "table".to_string(),
        title: "Recent Executions".to_string(),
        config: serde_json::json!({
            "columns": ["execution_id", "path", "status"]
        }),
        data: serde_json::json!(recent_executions
            .iter()
            .map(|(id, path, status)| {
                serde_json::json!({
                    "execution_id": id,
                    "path": path,
                    "status": status
                })
            })
            .collect::<Vec<_>>()),
    };

    Ok(Json(DashboardWidgetsResponse {
        widgets: vec![trend_widget, recent_widget],
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dashboard_stats_serialization() {
        let stats = DashboardStats {
            total_executions: 150,
            successful_executions: 135,
            failed_executions: 10,
            cancelled_executions: 5,
            running_executions: 3,
            total_playbooks: 25,
            total_workers: 4,
        };

        let json = serde_json::to_string(&stats).unwrap();
        assert!(json.contains("\"total_executions\":150"));
        assert!(json.contains("\"successful_executions\":135"));
    }

    #[test]
    fn test_widget_serialization() {
        let widget = Widget {
            id: "test-widget".to_string(),
            widget_type: "chart".to_string(),
            title: "Test Widget".to_string(),
            config: serde_json::json!({"key": "value"}),
            data: serde_json::json!([1, 2, 3]),
        };

        let json = serde_json::to_string(&widget).unwrap();
        assert!(json.contains("\"id\":\"test-widget\""));
        assert!(json.contains("\"type\":\"chart\""));
    }

    #[test]
    fn test_dashboard_stats_response_serialization() {
        let response = DashboardStatsResponse {
            status: "ok".to_string(),
            stats: DashboardStats {
                total_executions: 100,
                successful_executions: 90,
                failed_executions: 8,
                cancelled_executions: 2,
                running_executions: 1,
                total_playbooks: 10,
                total_workers: 2,
            },
        };

        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("\"status\":\"ok\""));
        assert!(json.contains("\"stats\""));
    }
}
