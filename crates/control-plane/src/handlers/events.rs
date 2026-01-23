//! Event handling API handlers.
//!
//! Handles worker events and command retrieval endpoints.
//!
//! SECURITY: All event payloads are sanitized before storage to prevent
//! sensitive data (bearer tokens, passwords, API keys) from being persisted.

use axum::{
    extract::{Path, State},
    Json,
};
use serde::{Deserialize, Serialize};
use tracing::{debug, info, warn};

use crate::error::{AppError, AppResult};
use crate::sanitize::sanitize_sensitive_data;
use crate::state::AppState;

/// Worker event request.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventRequest {
    /// Execution ID.
    pub execution_id: String,
    /// Step name.
    pub step: String,
    /// Event name (step.enter, call.done, step.exit, etc.).
    pub name: String,
    /// Event payload/result data.
    #[serde(default)]
    pub payload: serde_json::Value,
    /// Additional metadata.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub meta: Option<serde_json::Value>,
    /// Worker ID.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub worker_id: Option<String>,
    /// Result kind: "data", "ref", or "refs".
    #[serde(default = "default_result_kind")]
    pub result_kind: String,
    /// Result URI for ref kind.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result_uri: Option<String>,
    /// Event IDs for refs kind.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub event_ids: Option<Vec<i64>>,
    /// If true, server should take action.
    #[serde(default = "default_true")]
    pub actionable: bool,
    /// If true, event is for logging/observability.
    #[serde(default = "default_true")]
    pub informative: bool,
}

fn default_result_kind() -> String {
    "data".to_string()
}

fn default_true() -> bool {
    true
}

/// Response for event handling.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventResponse {
    /// Status of the operation.
    pub status: String,
    /// Event ID that was created.
    pub event_id: i64,
    /// Number of commands generated.
    pub commands_generated: i32,
}

/// Command details response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandResponse {
    /// Execution ID.
    pub execution_id: i64,
    /// Node/step ID.
    pub node_id: String,
    /// Node/step name.
    pub node_name: String,
    /// Action/tool kind.
    pub action: String,
    /// Command context (tool config, args, etc.).
    pub context: serde_json::Value,
    /// Command metadata.
    pub meta: serde_json::Value,
}

/// Handle worker event.
///
/// POST /api/events
///
/// Worker reports completion with result (inline or ref).
/// Engine evaluates case/when/then and generates next commands.
pub async fn handle_event(
    State(state): State<AppState>,
    Json(request): Json<EventRequest>,
) -> Result<Json<EventResponse>, AppError> {
    debug!(
        "Event received: execution_id={}, step={}, name={}",
        request.execution_id, request.step, request.name
    );

    let execution_id: i64 = request
        .execution_id
        .parse()
        .map_err(|_| AppError::Validation("Invalid execution_id".to_string()))?;

    // Events that should NOT trigger engine processing
    let skip_engine_events = [
        "command.claimed",
        "command.started",
        "command.completed",
        "command.failed",
        "step.enter",
    ];

    // For command.claimed, check if already claimed
    if request.name == "command.claimed" {
        if let Some(command_id) = get_command_id(&request) {
            if check_already_claimed(&state, execution_id, &command_id, &request.worker_id).await? {
                // Already claimed by same worker - idempotent success
                return Ok(Json(EventResponse {
                    status: "ok".to_string(),
                    event_id: 0,
                    commands_generated: 0,
                }));
            }
        }
    }

    // Build result object based on kind
    let result_obj_raw = build_result_object(&request);
    // SECURITY: Sanitize result data to remove sensitive information (tokens, passwords, etc.)
    let result_obj = sanitize_sensitive_data(&result_obj_raw);

    // Generate event ID
    let event_id = generate_snowflake_id(&state).await?;

    // Get catalog_id from existing events
    let catalog_id = get_catalog_id(&state, execution_id).await?;

    // Build meta object with control flags
    let mut meta_obj = request.meta.clone().unwrap_or(serde_json::json!({}));
    if let serde_json::Value::Object(ref mut map) = meta_obj {
        map.insert(
            "actionable".to_string(),
            serde_json::json!(request.actionable),
        );
        map.insert(
            "informative".to_string(),
            serde_json::json!(request.informative),
        );
        if let Some(ref worker_id) = request.worker_id {
            map.insert("worker_id".to_string(), serde_json::json!(worker_id));
        }
    }
    // SECURITY: Sanitize meta data to remove sensitive information
    let meta_obj = sanitize_sensitive_data(&meta_obj);

    // Determine status based on event name
    let status = if request.name.contains("done") || request.name.contains("exit") {
        "COMPLETED"
    } else if request.name.contains("error") || request.name.contains("failed") {
        "FAILED"
    } else {
        "RUNNING"
    };

    // Persist the event
    sqlx::query(
        r#"
        INSERT INTO noetl.event (
            event_id, execution_id, catalog_id, event_type,
            node_id, node_name, status, result, meta, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        "#,
    )
    .bind(event_id)
    .bind(execution_id)
    .bind(catalog_id)
    .bind(&request.name)
    .bind(&request.step)
    .bind(&request.step)
    .bind(status)
    .bind(&result_obj)
    .bind(&meta_obj)
    .bind(chrono::Utc::now())
    .execute(&state.db)
    .await?;

    info!(
        "Event persisted: event_id={}, execution_id={}, name={}",
        event_id, execution_id, request.name
    );

    // Process through engine if applicable
    let commands_generated = if !skip_engine_events.contains(&request.name.as_str()) {
        // TODO: Implement engine event handling
        // This would call the orchestrator to evaluate next steps
        debug!("Would process through engine: event_type={}", request.name);
        0
    } else {
        debug!("Skipped engine for administrative event: {}", request.name);
        0
    };

    // Trigger orchestrator for workflow progression on command.completed
    if request.name == "command.completed" && request.step.to_lowercase() != "end" {
        match trigger_orchestrator(&state, execution_id, event_id).await {
            Ok(cmds) => {
                info!(
                    "Orchestrator generated {} commands for execution {}",
                    cmds, execution_id
                );
            }
            Err(e) => {
                warn!("Orchestrator error: {}", e);
            }
        }
    }

    Ok(Json(EventResponse {
        status: "ok".to_string(),
        event_id,
        commands_generated,
    }))
}

/// Get command details from command.issued event.
///
/// GET /api/commands/{event_id}
///
/// Workers call this to fetch command config after NATS notification.
pub async fn get_command(
    State(state): State<AppState>,
    Path(event_id): Path<i64>,
) -> Result<Json<CommandResponse>, AppError> {
    debug!("Getting command for event_id={}", event_id);

    let row: Option<(i64, String, String, serde_json::Value, serde_json::Value)> =
        sqlx::query_as::<_, (i64, String, String, serde_json::Value, serde_json::Value)>(
            r#"
            SELECT execution_id, node_name, node_type, context, meta
            FROM noetl.event
            WHERE event_id = $1 AND event_type = 'command.issued'
            "#,
        )
        .bind(event_id)
        .fetch_optional(&state.db)
        .await?;

    match row {
        Some((execution_id, node_name, node_type, context, meta)) => Ok(Json(CommandResponse {
            execution_id,
            node_id: node_name.clone(),
            node_name,
            action: node_type,
            context,
            meta,
        })),
        None => Err(AppError::NotFound(format!(
            "command.issued event not found: {}",
            event_id
        ))),
    }
}

/// Extract command_id from request.
fn get_command_id(request: &EventRequest) -> Option<String> {
    // Try payload first
    if let Some(id) = request.payload.get("command_id").and_then(|v| v.as_str()) {
        return Some(id.to_string());
    }
    // Try meta
    if let Some(meta) = &request.meta {
        if let Some(id) = meta.get("command_id").and_then(|v| v.as_str()) {
            return Some(id.to_string());
        }
    }
    None
}

/// Check if command is already claimed.
async fn check_already_claimed(
    state: &AppState,
    execution_id: i64,
    command_id: &str,
    worker_id: &Option<String>,
) -> AppResult<bool> {
    let row: Option<(Option<String>, Option<serde_json::Value>)> =
        sqlx::query_as::<_, (Option<String>, Option<serde_json::Value>)>(
            r#"
            SELECT worker_id, meta FROM noetl.event
            WHERE execution_id = $1
              AND event_type = 'command.claimed'
              AND (meta->>'command_id' = $2 OR result->'data'->>'command_id' = $2)
            LIMIT 1
            "#,
        )
        .bind(execution_id)
        .bind(command_id)
        .fetch_optional(&state.db)
        .await?;

    if let Some((existing_worker, meta)) = row {
        let existing_worker_id = existing_worker.or_else(|| {
            meta.and_then(|m| {
                m.get("worker_id")
                    .and_then(|v| v.as_str())
                    .map(String::from)
            })
        });

        if let (Some(existing), Some(current)) = (&existing_worker_id, worker_id) {
            if existing != current {
                // Different worker - reject
                return Err(AppError::Conflict(format!(
                    "Command already claimed by {}",
                    existing
                )));
            }
            // Same worker - idempotent
            return Ok(true);
        }
    }

    Ok(false)
}

/// Build result object based on result_kind.
fn build_result_object(request: &EventRequest) -> serde_json::Value {
    match request.result_kind.as_str() {
        "ref" if request.result_uri.is_some() => {
            let uri = request.result_uri.as_ref().unwrap();
            let store_tier = if uri.starts_with("gs://") {
                "gcs"
            } else if uri.starts_with("s3://") {
                "s3"
            } else {
                "artifact"
            };
            serde_json::json!({
                "kind": "ref",
                "store_tier": store_tier,
                "logical_uri": uri,
            })
        }
        "refs" if request.event_ids.is_some() => {
            let event_ids = request.event_ids.as_ref().unwrap();
            serde_json::json!({
                "kind": "refs",
                "event_ids": event_ids,
                "total_parts": event_ids.len(),
            })
        }
        _ => {
            serde_json::json!({
                "kind": "data",
                "data": request.payload,
            })
        }
    }
}

/// Get catalog_id from existing events.
async fn get_catalog_id(state: &AppState, execution_id: i64) -> AppResult<Option<i64>> {
    let row: Option<(i64,)> = sqlx::query_as::<_, (i64,)>(
        "SELECT catalog_id FROM noetl.event WHERE execution_id = $1 LIMIT 1",
    )
    .bind(execution_id)
    .fetch_optional(&state.db)
    .await?;

    Ok(row.map(|(id,)| id))
}

/// Generate a snowflake ID.
async fn generate_snowflake_id(state: &AppState) -> AppResult<i64> {
    let row: (i64,) = sqlx::query_as::<_, (i64,)>("SELECT noetl.snowflake_id()")
        .fetch_one(&state.db)
        .await?;

    Ok(row.0)
}

/// Trigger orchestrator for workflow progression.
async fn trigger_orchestrator(
    _state: &AppState,
    execution_id: i64,
    trigger_event_id: i64,
) -> AppResult<i32> {
    // This would be a full orchestrator implementation
    // For now, just log and return 0
    debug!(
        "Would trigger orchestrator for execution={}, trigger_event={}",
        execution_id, trigger_event_id
    );

    // TODO: Load playbook, reconstruct state from events, evaluate next steps
    Ok(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_event_request_defaults() {
        let json = r#"{"execution_id": "123", "step": "step1", "name": "step.enter"}"#;
        let request: EventRequest = serde_json::from_str(json).unwrap();

        assert_eq!(request.result_kind, "data");
        assert!(request.actionable);
        assert!(request.informative);
    }

    #[test]
    fn test_build_result_object_data() {
        let request = EventRequest {
            execution_id: "123".to_string(),
            step: "step1".to_string(),
            name: "step.exit".to_string(),
            payload: serde_json::json!({"output": "success"}),
            meta: None,
            worker_id: None,
            result_kind: "data".to_string(),
            result_uri: None,
            event_ids: None,
            actionable: true,
            informative: true,
        };

        let result = build_result_object(&request);
        assert_eq!(result["kind"], "data");
        assert_eq!(result["data"]["output"], "success");
    }

    #[test]
    fn test_build_result_object_ref() {
        let request = EventRequest {
            execution_id: "123".to_string(),
            step: "step1".to_string(),
            name: "step.exit".to_string(),
            payload: serde_json::json!({}),
            meta: None,
            worker_id: None,
            result_kind: "ref".to_string(),
            result_uri: Some("gs://bucket/path/to/result".to_string()),
            event_ids: None,
            actionable: true,
            informative: true,
        };

        let result = build_result_object(&request);
        assert_eq!(result["kind"], "ref");
        assert_eq!(result["store_tier"], "gcs");
        assert_eq!(result["logical_uri"], "gs://bucket/path/to/result");
    }

    #[test]
    fn test_event_response_serialization() {
        let response = EventResponse {
            status: "ok".to_string(),
            event_id: 12345,
            commands_generated: 2,
        };

        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("ok"));
        assert!(json.contains("12345"));
    }

    #[test]
    fn test_command_response_serialization() {
        let response = CommandResponse {
            execution_id: 12345,
            node_id: "step1".to_string(),
            node_name: "step1".to_string(),
            action: "python".to_string(),
            context: serde_json::json!({"tool_config": {}}),
            meta: serde_json::json!({"attempt": 1}),
        };

        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("step1"));
        assert!(json.contains("python"));
    }
}
