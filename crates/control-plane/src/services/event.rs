//! Event service for event sourcing operations.
//!
//! SECURITY: All event context, result, and metadata are sanitized before storage
//! to prevent sensitive data (bearer tokens, passwords, API keys) from being persisted.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::db::models::Event;
use crate::db::queries::event as queries;
use crate::db::DbPool;
use crate::error::AppResult;
use crate::sanitize::sanitize_sensitive_data;

/// Request to emit an event.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmitEventRequest {
    pub event_id: i64,
    pub execution_id: i64,
    pub catalog_id: i64,
    pub event_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_event_id: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_execution_id: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_type: Option<String>,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub context: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub meta: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub worker_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub attempt: Option<i32>,
}

/// Response after emitting an event.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmitEventResponse {
    pub id: i64,
    pub event_id: i64,
    pub status: String,
}

/// Execution status derived from events.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionStatus {
    pub execution_id: i64,
    pub status: String,
    pub event_count: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latest_event: Option<Event>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub started_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completed_at: Option<DateTime<Utc>>,
}

/// Step status derived from events.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepStatus {
    pub step_name: String,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    pub events: Vec<Event>,
}

/// Service for event operations.
#[derive(Clone)]
pub struct EventService {
    pool: DbPool,
}

impl EventService {
    /// Create a new event service.
    pub fn new(pool: DbPool) -> Self {
        Self { pool }
    }

    /// Emit a new event.
    ///
    /// SECURITY: Context, meta, and result fields are sanitized to remove sensitive data.
    pub async fn emit(&self, request: EmitEventRequest) -> AppResult<EmitEventResponse> {
        // SECURITY: Sanitize all JSON fields before storage
        let sanitized_context = request.context.as_ref().map(sanitize_sensitive_data);
        let sanitized_meta = request.meta.as_ref().map(sanitize_sensitive_data);
        let sanitized_result = request.result.as_ref().map(sanitize_sensitive_data);

        let id = queries::insert_event(
            &self.pool,
            request.event_id,
            request.execution_id,
            request.catalog_id,
            request.parent_event_id,
            request.parent_execution_id,
            &request.event_type,
            request.node_id.as_deref(),
            request.node_name.as_deref(),
            request.node_type.as_deref(),
            &request.status,
            sanitized_context.as_ref(),
            sanitized_meta.as_ref(),
            sanitized_result.as_ref(),
            request.worker_id.as_deref(),
            request.attempt,
        )
        .await?;

        Ok(EmitEventResponse {
            id,
            event_id: request.event_id,
            status: "emitted".to_string(),
        })
    }

    /// Emit playbook started event.
    ///
    /// SECURITY: Context and meta (including workload) are sanitized to remove sensitive data.
    #[allow(clippy::too_many_arguments)]
    pub async fn emit_playbook_started(
        &self,
        event_id: i64,
        execution_id: i64,
        catalog_id: i64,
        path: &str,
        version: i32,
        workload: &serde_json::Value,
        parent_execution_id: Option<i64>,
        parent_event_id: Option<i64>,
        requestor_info: Option<&serde_json::Value>,
    ) -> AppResult<i64> {
        // Sanitize workload before storing - it may contain sensitive auth configuration
        let sanitized_workload = sanitize_sensitive_data(workload);

        let mut context = serde_json::json!({
            "catalog_id": catalog_id.to_string(),
            "execution_id": execution_id.to_string(),
            "path": path,
            "version": version.to_string(),
            "workload": sanitized_workload,
        });

        if let Some(parent_exec) = parent_execution_id {
            context["parent_execution_id"] = serde_json::json!(parent_exec.to_string());
        }
        if let Some(parent_evt) = parent_event_id {
            context["parent_event_id"] = serde_json::json!(parent_evt.to_string());
        }

        let mut meta = serde_json::json!({
            "emitted_at": Utc::now().to_rfc3339(),
            "emitter": "control_plane",
        });

        if let Some(req_info) = requestor_info {
            // Sanitize requestor info as well
            meta["requestor"] = sanitize_sensitive_data(req_info);
        }

        let id = queries::insert_event(
            &self.pool,
            event_id,
            execution_id,
            catalog_id,
            parent_event_id,
            parent_execution_id,
            "playbook_started",
            Some("playbook"),
            Some(path),
            Some("execution"),
            "STARTED",
            Some(&context),
            Some(&meta),
            None,
            None,
            None,
        )
        .await?;

        Ok(id)
    }

    /// Emit workflow initialized event.
    pub async fn emit_workflow_initialized(
        &self,
        event_id: i64,
        execution_id: i64,
        catalog_id: i64,
        parent_event_id: i64,
        step_count: i32,
        transition_count: i32,
    ) -> AppResult<i64> {
        let context = serde_json::json!({
            "step_count": step_count,
            "transition_count": transition_count,
        });

        let meta = serde_json::json!({
            "emitted_at": Utc::now().to_rfc3339(),
            "emitter": "control_plane",
        });

        let id = queries::insert_event(
            &self.pool,
            event_id,
            execution_id,
            catalog_id,
            Some(parent_event_id),
            None,
            "workflow.initialized",
            Some("workflow"),
            Some("workflow"),
            Some("workflow"),
            "COMPLETED",
            Some(&context),
            Some(&meta),
            None,
            None,
            None,
        )
        .await?;

        Ok(id)
    }

    /// Emit step enter event.
    ///
    /// SECURITY: Context is sanitized to remove sensitive data.
    #[allow(clippy::too_many_arguments)]
    pub async fn emit_step_enter(
        &self,
        event_id: i64,
        execution_id: i64,
        catalog_id: i64,
        parent_event_id: i64,
        step_id: &str,
        step_name: &str,
        step_type: &str,
        context: Option<&serde_json::Value>,
    ) -> AppResult<i64> {
        let meta = serde_json::json!({
            "emitted_at": Utc::now().to_rfc3339(),
            "emitter": "control_plane",
        });

        // SECURITY: Sanitize context before storing
        let sanitized_context = context.map(sanitize_sensitive_data);

        let id = queries::insert_event(
            &self.pool,
            event_id,
            execution_id,
            catalog_id,
            Some(parent_event_id),
            None,
            "step.enter",
            Some(step_id),
            Some(step_name),
            Some(step_type),
            "ENTERED",
            sanitized_context.as_ref(),
            Some(&meta),
            None,
            None,
            None,
        )
        .await?;

        Ok(id)
    }

    /// Emit command issued event.
    ///
    /// SECURITY: Command context is sanitized to remove sensitive data.
    #[allow(clippy::too_many_arguments)]
    pub async fn emit_command_issued(
        &self,
        event_id: i64,
        execution_id: i64,
        catalog_id: i64,
        parent_event_id: i64,
        step_name: &str,
        command: &serde_json::Value,
    ) -> AppResult<i64> {
        let meta = serde_json::json!({
            "emitted_at": Utc::now().to_rfc3339(),
            "emitter": "control_plane",
        });

        // SECURITY: Sanitize command context before storing - may contain auth configuration
        let sanitized_command = sanitize_sensitive_data(command);

        let id = queries::insert_event(
            &self.pool,
            event_id,
            execution_id,
            catalog_id,
            Some(parent_event_id),
            None,
            "command.issued",
            None,
            Some(step_name),
            Some("command"),
            "PENDING",
            Some(&sanitized_command),
            Some(&meta),
            None,
            None,
            None,
        )
        .await?;

        Ok(id)
    }

    /// Get an event by ID.
    pub async fn get_event(&self, event_id: i64) -> AppResult<Option<Event>> {
        queries::get_event_by_id(&self.pool, event_id).await
    }

    /// Get events for an execution.
    pub async fn get_events(
        &self,
        execution_id: i64,
        event_type: Option<&str>,
        limit: Option<i64>,
    ) -> AppResult<Vec<Event>> {
        queries::get_events_by_execution(&self.pool, execution_id, event_type, limit).await
    }

    /// Get events by multiple types.
    pub async fn get_events_by_types(
        &self,
        execution_id: i64,
        event_types: &[&str],
    ) -> AppResult<Vec<Event>> {
        queries::get_events_by_types(&self.pool, execution_id, event_types).await
    }

    /// Get the latest event for an execution.
    pub async fn get_latest_event(
        &self,
        execution_id: i64,
        event_type: Option<&str>,
    ) -> AppResult<Option<Event>> {
        queries::get_latest_event(&self.pool, execution_id, event_type).await
    }

    /// Get execution status from events.
    pub async fn get_execution_status(&self, execution_id: i64) -> AppResult<ExecutionStatus> {
        let status = queries::get_execution_status(&self.pool, execution_id).await?;
        let event_count = queries::count_events(&self.pool, execution_id, None).await?;
        let latest_event = queries::get_latest_event(&self.pool, execution_id, None).await?;

        // Get started_at from playbook_started event
        let start_event =
            queries::get_latest_event(&self.pool, execution_id, Some("playbook_started")).await?;
        let started_at = start_event.map(|e| e.created_at);

        // Get completed_at from terminal events
        let completed_at = if status == "COMPLETED" || status == "FAILED" || status == "CANCELLED" {
            latest_event.as_ref().map(|e| e.created_at)
        } else {
            None
        };

        Ok(ExecutionStatus {
            execution_id,
            status,
            event_count,
            latest_event,
            started_at,
            completed_at,
        })
    }

    /// Get step status from events.
    pub async fn get_step_status(
        &self,
        execution_id: i64,
        step_name: &str,
    ) -> AppResult<StepStatus> {
        let events = queries::get_events_by_step(&self.pool, execution_id, step_name).await?;
        let result = queries::get_step_result(&self.pool, execution_id, step_name).await?;

        // Determine status from events
        let status = if events.is_empty() {
            "PENDING".to_string()
        } else {
            let last_event = events.last().unwrap();
            match last_event.event_type.as_str() {
                "step.enter" => "ENTERED".to_string(),
                "action_completed" | "command.completed" => "COMPLETED".to_string(),
                "action_failed" | "command.failed" => "FAILED".to_string(),
                _ => last_event.status.clone(),
            }
        };

        Ok(StepStatus {
            step_name: step_name.to_string(),
            status,
            result,
            events,
        })
    }

    /// Get all step results for an execution.
    pub async fn get_all_step_results(
        &self,
        execution_id: i64,
    ) -> AppResult<Vec<(String, serde_json::Value)>> {
        queries::get_all_step_results(&self.pool, execution_id).await
    }

    /// Check if workflow is initialized.
    pub async fn is_workflow_initialized(&self, execution_id: i64) -> AppResult<bool> {
        queries::is_workflow_initialized(&self.pool, execution_id).await
    }

    /// Check if playbook is completed.
    pub async fn is_playbook_completed(&self, execution_id: i64) -> AppResult<bool> {
        queries::is_playbook_completed(&self.pool, execution_id).await
    }

    /// Check if playbook has failed.
    pub async fn is_playbook_failed(&self, execution_id: i64) -> AppResult<bool> {
        queries::is_playbook_failed(&self.pool, execution_id).await
    }

    /// Get events since a timestamp.
    pub async fn get_events_since(
        &self,
        execution_id: i64,
        since: DateTime<Utc>,
    ) -> AppResult<Vec<Event>> {
        queries::get_events_since(&self.pool, execution_id, since).await
    }

    /// Get playbook start event.
    pub async fn get_playbook_start_event(&self, execution_id: i64) -> AppResult<Option<Event>> {
        queries::get_playbook_start_event(&self.pool, execution_id).await
    }

    /// Count events for an execution.
    pub async fn count_events(
        &self,
        execution_id: i64,
        event_type: Option<&str>,
    ) -> AppResult<i64> {
        queries::count_events(&self.pool, execution_id, event_type).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_emit_event_request_serialization() {
        let request = EmitEventRequest {
            event_id: 12345,
            execution_id: 67890,
            catalog_id: 11111,
            event_type: "playbook_started".to_string(),
            parent_event_id: None,
            parent_execution_id: None,
            node_id: Some("playbook".to_string()),
            node_name: Some("test-playbook".to_string()),
            node_type: Some("execution".to_string()),
            status: "STARTED".to_string(),
            context: Some(serde_json::json!({"key": "value"})),
            meta: None,
            result: None,
            worker_id: None,
            attempt: None,
        };

        let json = serde_json::to_string(&request).unwrap();
        assert!(json.contains("playbook_started"));
        assert!(json.contains("12345"));

        // Verify optional fields are skipped when None
        assert!(!json.contains("parent_event_id"));
        assert!(!json.contains("meta"));
    }

    #[test]
    fn test_execution_status_serialization() {
        let status = ExecutionStatus {
            execution_id: 12345,
            status: "RUNNING".to_string(),
            event_count: 5,
            latest_event: None,
            started_at: Some(Utc::now()),
            completed_at: None,
        };

        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("RUNNING"));
        assert!(json.contains("12345"));
        assert!(json.contains("started_at"));
        // completed_at should be skipped when None
        assert!(!json.contains("completed_at"));
    }

    #[test]
    fn test_step_status_serialization() {
        let status = StepStatus {
            step_name: "step1".to_string(),
            status: "COMPLETED".to_string(),
            result: Some(serde_json::json!({"output": "success"})),
            events: vec![],
        };

        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("step1"));
        assert!(json.contains("COMPLETED"));
        assert!(json.contains("output"));
    }
}
