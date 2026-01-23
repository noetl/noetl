//! Execution API handlers.
//!
//! Handles playbook execution start and status endpoints.

use std::collections::HashMap;

use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};
use tracing::{debug, info};

use crate::error::{AppError, AppResult};
use crate::state::AppState;

/// Request to start playbook execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecuteRequest {
    /// Playbook catalog path.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    /// Catalog ID (alternative to path).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub catalog_id: Option<i64>,
    /// Input payload/workload.
    #[serde(default)]
    pub payload: HashMap<String, serde_json::Value>,
    /// Parent execution ID (for nested executions).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_execution_id: Option<i64>,
}

impl ExecuteRequest {
    /// Validate the request.
    pub fn validate(&self) -> Result<(), String> {
        if self.path.is_none() && self.catalog_id.is_none() {
            return Err("Either 'path' or 'catalog_id' must be provided".to_string());
        }
        Ok(())
    }
}

/// Response for starting execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecuteResponse {
    /// Execution ID.
    pub execution_id: String,
    /// Execution status.
    pub status: String,
    /// Number of commands generated.
    pub commands_generated: i32,
}

/// Start playbook execution.
///
/// POST /api/execute
///
/// Creates playbook_started event and emits command.issued events.
/// All state is derived from events - no separate workflow/transition tables.
pub async fn execute(
    State(state): State<AppState>,
    Json(request): Json<ExecuteRequest>,
) -> Result<Json<ExecuteResponse>, AppError> {
    // Validate request
    request.validate().map_err(AppError::Validation)?;

    debug!(
        "Execute request: path={:?}, catalog_id={:?}",
        request.path, request.catalog_id
    );

    // Resolve catalog entry
    let (catalog_id, path) = resolve_catalog(&state, &request).await?;

    info!(
        "Starting execution for path={}, catalog_id={}",
        path, catalog_id
    );

    // Get playbook from catalog
    let playbook_yaml = get_playbook_yaml(&state, catalog_id).await?;

    // Parse playbook
    let playbook = crate::playbook::parser::parse_playbook(&playbook_yaml)?;

    // Generate execution_id
    let execution_id = generate_snowflake_id(&state).await?;

    // Build workload from payload
    let workload = serde_json::to_value(&request.payload)
        .map_err(|e| AppError::Internal(format!("Failed to serialize payload: {}", e)))?;

    // Emit playbook_started event
    let start_event_id = emit_playbook_started_event(
        &state,
        execution_id,
        catalog_id,
        &path,
        &workload,
        request.parent_execution_id,
    )
    .await?;

    // Generate initial commands for the start step
    let commands_generated = generate_initial_commands(
        &state,
        execution_id,
        catalog_id,
        start_event_id,
        &playbook,
        &request.payload,
    )
    .await?;

    info!(
        "Execution started: execution_id={}, commands_generated={}",
        execution_id, commands_generated
    );

    Ok(Json(ExecuteResponse {
        execution_id: execution_id.to_string(),
        status: "started".to_string(),
        commands_generated,
    }))
}

/// Resolve catalog entry from path or catalog_id.
async fn resolve_catalog(state: &AppState, request: &ExecuteRequest) -> AppResult<(i64, String)> {
    if let Some(catalog_id) = request.catalog_id {
        // Lookup by catalog_id
        let entry = sqlx::query_as::<_, (i64, String)>(
            "SELECT catalog_id, path FROM noetl.catalog WHERE catalog_id = $1",
        )
        .bind(catalog_id)
        .fetch_optional(&state.db)
        .await?
        .ok_or_else(|| AppError::NotFound(format!("Catalog entry not found: {}", catalog_id)))?;

        Ok(entry)
    } else if let Some(path) = &request.path {
        // Lookup by path (latest version)
        let entry = sqlx::query_as::<_, (i64, String)>(
            "SELECT catalog_id, path FROM noetl.catalog WHERE path = $1 ORDER BY version DESC LIMIT 1",
        )
        .bind(path)
        .fetch_optional(&state.db)
        .await?
        .ok_or_else(|| AppError::NotFound(format!("Playbook not found: {}", path)))?;

        Ok(entry)
    } else {
        Err(AppError::Validation(
            "Either path or catalog_id must be provided".to_string(),
        ))
    }
}

/// Get playbook YAML from catalog.
async fn get_playbook_yaml(state: &AppState, catalog_id: i64) -> AppResult<String> {
    // Try to get content first (raw YAML), fall back to payload (JSON)
    let row: (Option<String>, Option<serde_json::Value>) =
        sqlx::query_as::<_, (Option<String>, Option<serde_json::Value>)>(
            "SELECT content, payload FROM noetl.catalog WHERE catalog_id = $1",
        )
        .bind(catalog_id)
        .fetch_optional(&state.db)
        .await?
        .ok_or_else(|| AppError::NotFound(format!("Catalog entry not found: {}", catalog_id)))?;

    match row {
        (Some(content), _) if !content.is_empty() => Ok(content),
        (_, Some(payload)) => {
            // Convert JSON payload to YAML string
            serde_yaml::to_string(&payload).map_err(|e| {
                AppError::Internal(format!("Failed to convert payload to YAML: {}", e))
            })
        }
        _ => Err(AppError::NotFound(format!(
            "No playbook content found for catalog_id: {}",
            catalog_id
        ))),
    }
}

/// Generate a snowflake ID.
async fn generate_snowflake_id(state: &AppState) -> AppResult<i64> {
    let row: (i64,) = sqlx::query_as::<_, (i64,)>("SELECT noetl.snowflake_id()")
        .fetch_one(&state.db)
        .await?;

    Ok(row.0)
}

/// Emit playbook_started event.
async fn emit_playbook_started_event(
    state: &AppState,
    execution_id: i64,
    catalog_id: i64,
    path: &str,
    workload: &serde_json::Value,
    parent_execution_id: Option<i64>,
) -> AppResult<i64> {
    let event_id = generate_snowflake_id(state).await?;

    let context = serde_json::json!({
        "catalog_id": catalog_id.to_string(),
        "execution_id": execution_id.to_string(),
        "path": path,
        "workload": workload,
    });

    let meta = serde_json::json!({
        "emitted_at": chrono::Utc::now().to_rfc3339(),
        "emitter": "control_plane",
    });

    sqlx::query(
        r#"
        INSERT INTO noetl.event (
            execution_id, catalog_id, event_id, parent_execution_id,
            event_type, node_id, node_name, node_type, status,
            context, meta, created_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
        )
        "#,
    )
    .bind(execution_id)
    .bind(catalog_id)
    .bind(event_id)
    .bind(parent_execution_id)
    .bind("playbook_started")
    .bind("playbook")
    .bind(path)
    .bind("execution")
    .bind("STARTED")
    .bind(&context)
    .bind(&meta)
    .bind(chrono::Utc::now())
    .execute(&state.db)
    .await?;

    Ok(event_id)
}

/// Generate initial commands for the start step.
#[allow(clippy::too_many_arguments)]
async fn generate_initial_commands(
    state: &AppState,
    execution_id: i64,
    catalog_id: i64,
    parent_event_id: i64,
    playbook: &crate::playbook::types::Playbook,
    payload: &HashMap<String, serde_json::Value>,
) -> AppResult<i32> {
    // Find start step
    let start_step = playbook
        .get_step("start")
        .ok_or_else(|| AppError::Validation("Start step 'start' not found".to_string()))?;

    // Build command
    let command_builder = crate::engine::commands::CommandBuilder::new();
    let context = payload.clone();

    let command = command_builder.build_command(
        0, // Will be replaced with actual event_id
        execution_id,
        catalog_id,
        parent_event_id,
        start_step,
        &context,
        None,
    )?;

    // Generate event_id for command.issued
    let event_id = generate_snowflake_id(state).await?;
    let command_id = format!("{}:{}:{}", execution_id, start_step.step, event_id);

    // Build context for command execution
    let cmd_context = serde_json::json!({
        "tool_config": command.tool.config,
        "args": start_step.args,
        "render_context": context,
    });

    let cmd_meta = serde_json::json!({
        "command_id": command_id,
        "step": start_step.step,
        "tool_kind": command.tool.kind,
        "max_attempts": 3,
        "attempt": 1,
        "execution_id": execution_id.to_string(),
        "catalog_id": catalog_id.to_string(),
        "actionable": true,
    });

    // Insert command.issued event
    sqlx::query(
        r#"
        INSERT INTO noetl.event (
            event_id, execution_id, catalog_id, event_type,
            node_id, node_name, node_type, status,
            context, meta, parent_event_id, created_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
        )
        "#,
    )
    .bind(event_id)
    .bind(execution_id)
    .bind(catalog_id)
    .bind("command.issued")
    .bind(&start_step.step)
    .bind(&start_step.step)
    .bind(command.tool.kind.as_str())
    .bind("PENDING")
    .bind(&cmd_context)
    .bind(&cmd_meta)
    .bind(parent_event_id)
    .bind(chrono::Utc::now())
    .execute(&state.db)
    .await?;

    // TODO: Publish to NATS for worker notification
    // This would be implemented when NATS module is added

    Ok(1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_execute_request_validation() {
        let request = ExecuteRequest {
            path: None,
            catalog_id: None,
            payload: HashMap::new(),
            parent_execution_id: None,
        };
        assert!(request.validate().is_err());

        let request = ExecuteRequest {
            path: Some("test/playbook".to_string()),
            catalog_id: None,
            payload: HashMap::new(),
            parent_execution_id: None,
        };
        assert!(request.validate().is_ok());

        let request = ExecuteRequest {
            path: None,
            catalog_id: Some(12345),
            payload: HashMap::new(),
            parent_execution_id: None,
        };
        assert!(request.validate().is_ok());
    }

    #[test]
    fn test_execute_response_serialization() {
        let response = ExecuteResponse {
            execution_id: "12345".to_string(),
            status: "started".to_string(),
            commands_generated: 1,
        };

        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("12345"));
        assert!(json.contains("started"));
    }
}
