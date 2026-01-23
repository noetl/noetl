//! Workflow orchestration engine.
//!
//! Coordinates workflow execution by:
//! - Analyzing events to determine current state
//! - Evaluating transitions to determine next steps
//! - Publishing commands for workers

use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use tracing::{debug, info, warn};

use crate::db::models::Event;
use crate::error::{AppError, AppResult};
use crate::playbook::types::{Playbook, Step};

use super::commands::{Command, CommandBuilder};
use super::evaluator::ConditionEvaluator;
use super::state::{ExecutionState, WorkflowState};

/// Result of orchestration evaluation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestrationResult {
    /// Current execution state.
    pub state: ExecutionState,
    /// Commands to issue.
    pub commands: Vec<Command>,
    /// Whether the execution should complete.
    pub should_complete: bool,
    /// Completion status if should_complete is true.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completion_status: Option<CompletionStatus>,
    /// Events to emit.
    pub events_to_emit: Vec<EventToEmit>,
}

/// Completion status for a workflow.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompletionStatus {
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub failed_steps: Option<Vec<String>>,
}

/// Event to emit during orchestration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventToEmit {
    pub event_type: String,
    pub node_name: Option<String>,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub context: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Workflow orchestrator.
pub struct WorkflowOrchestrator {
    evaluator: ConditionEvaluator,
    command_builder: CommandBuilder,
}

impl Default for WorkflowOrchestrator {
    fn default() -> Self {
        Self::new()
    }
}

impl WorkflowOrchestrator {
    /// Create a new workflow orchestrator.
    pub fn new() -> Self {
        Self {
            evaluator: ConditionEvaluator::new(),
            command_builder: CommandBuilder::new(),
        }
    }

    /// Evaluate an execution and determine next actions.
    ///
    /// This is the main orchestration entry point, called when:
    /// - A new execution starts
    /// - A worker reports a result (via event)
    pub fn evaluate(
        &self,
        events: &[Event],
        playbook: &Playbook,
        trigger_event_type: Option<&str>,
    ) -> AppResult<OrchestrationResult> {
        // Reconstruct workflow state from events
        let state = WorkflowState::from_events(events)
            .ok_or_else(|| AppError::Validation("No events found for execution".to_string()))?;

        debug!(
            "Evaluating execution {}, state: {}, trigger: {:?}",
            state.execution_id, state.state, trigger_event_type
        );

        // Check for terminal states
        if matches!(
            state.state,
            ExecutionState::Completed | ExecutionState::Failed | ExecutionState::Cancelled
        ) {
            return Ok(OrchestrationResult {
                state: state.state,
                commands: vec![],
                should_complete: false,
                completion_status: None,
                events_to_emit: vec![],
            });
        }

        // Skip evaluation for progress marker events
        if let Some(event_type) = trigger_event_type {
            if matches!(event_type, "step_started" | "step_running") {
                debug!("Skipping orchestration for progress marker event");
                return Ok(OrchestrationResult {
                    state: state.state,
                    commands: vec![],
                    should_complete: false,
                    completion_status: None,
                    events_to_emit: vec![],
                });
            }
        }

        // Build context for evaluation (convert Value to HashMap)
        let context = value_to_hashmap(&state.build_context());

        // Build step lookup
        let steps: HashMap<&str, &Step> = playbook
            .workflow
            .iter()
            .map(|s| (s.step.as_str(), s))
            .collect();

        // Determine what to do based on state
        match state.state {
            ExecutionState::Initial => {
                // Start first step(s) - always start with "start" step
                self.dispatch_initial_steps(&state, playbook, &context)
            }
            ExecutionState::InProgress => {
                // Check if we need to dispatch the initial step
                // (playbook_started but no steps entered yet)
                if state.steps.is_empty() {
                    return self.dispatch_initial_steps(&state, playbook, &context);
                }
                // Process completed steps and determine next steps
                self.process_in_progress(&state, &steps, &context, trigger_event_type)
            }
            _ => Ok(OrchestrationResult {
                state: state.state,
                commands: vec![],
                should_complete: false,
                completion_status: None,
                events_to_emit: vec![],
            }),
        }
    }

    /// Dispatch initial workflow steps.
    fn dispatch_initial_steps(
        &self,
        state: &WorkflowState,
        playbook: &Playbook,
        context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<OrchestrationResult> {
        let mut commands = Vec::new();
        let mut events_to_emit = Vec::new();

        // Find start step (always named "start")
        let start_step = playbook
            .get_step("start")
            .ok_or_else(|| AppError::Validation("Start step 'start' not found".to_string()))?;

        info!("Dispatching initial step: {}", start_step.step);

        // Create step.enter event
        events_to_emit.push(EventToEmit {
            event_type: "step.enter".to_string(),
            node_name: Some(start_step.step.clone()),
            status: "ENTERED".to_string(),
            context: None,
            result: None,
            error: None,
        });

        // Build command for the step
        // Note: In a real implementation, command_id would come from get_snowflake_id()
        let command = self.command_builder.build_command(
            0, // Placeholder - real implementation would use snowflake ID
            state.execution_id,
            state.catalog_id,
            0, // Placeholder - would be parent event ID
            start_step,
            context,
            None,
        )?;

        commands.push(command);

        Ok(OrchestrationResult {
            state: ExecutionState::InProgress,
            commands,
            should_complete: false,
            completion_status: None,
            events_to_emit,
        })
    }

    /// Process an in-progress execution.
    fn process_in_progress(
        &self,
        state: &WorkflowState,
        steps: &HashMap<&str, &Step>,
        context: &HashMap<String, serde_json::Value>,
        trigger_event_type: Option<&str>,
    ) -> AppResult<OrchestrationResult> {
        let mut commands = Vec::new();
        let mut events_to_emit = Vec::new();

        // Only process transitions on completion events
        if !matches!(
            trigger_event_type,
            Some("command.completed")
                | Some("action_completed")
                | Some("step.exit")
                | Some("step_completed")
                | Some("iterator_completed")
        ) {
            return Ok(OrchestrationResult {
                state: ExecutionState::InProgress,
                commands,
                should_complete: false,
                completion_status: None,
                events_to_emit,
            });
        }

        // Find completed steps that need transition evaluation
        for step_name in state.steps.keys() {
            if !state.is_step_completed(step_name) {
                continue;
            }

            // Get step definition
            let step = match steps.get(step_name.as_str()) {
                Some(s) => *s,
                None => continue,
            };

            // Evaluate next transitions
            let eval_results = self.evaluator.evaluate_next(step, context)?;

            for result in eval_results {
                if !result.matched {
                    continue;
                }

                if let Some(next_step_name) = &result.next_step {
                    // Check for 'end' step
                    if next_step_name == "end" {
                        info!("Reached 'end' step, workflow completing");
                        return Ok(OrchestrationResult {
                            state: ExecutionState::InProgress,
                            commands: vec![],
                            should_complete: true,
                            completion_status: Some(CompletionStatus {
                                status: "COMPLETED".to_string(),
                                error: None,
                                failed_steps: None,
                            }),
                            events_to_emit,
                        });
                    }

                    // Get next step definition
                    let next_step = match steps.get(next_step_name.as_str()) {
                        Some(s) => *s,
                        None => {
                            warn!("Next step '{}' not found in workflow", next_step_name);
                            continue;
                        }
                    };

                    // Skip if already completed or running
                    if state.is_step_done(next_step_name) {
                        debug!("Step '{}' already done, skipping", next_step_name);
                        continue;
                    }

                    if state.running_steps().contains(&next_step_name.as_str()) {
                        debug!("Step '{}' already running, skipping", next_step_name);
                        continue;
                    }

                    // Build context for next step with additional params
                    let mut step_context = context.clone();
                    if let Some(serde_json::Value::Object(params)) = &result.with_params {
                        for (k, v) in params {
                            step_context.insert(k.clone(), v.clone());
                        }
                    }

                    info!("Transitioning to step: {}", next_step_name);

                    // Create step.enter event
                    events_to_emit.push(EventToEmit {
                        event_type: "step.enter".to_string(),
                        node_name: Some(next_step_name.clone()),
                        status: "ENTERED".to_string(),
                        context: result.with_params.clone(),
                        result: None,
                        error: None,
                    });

                    // Build command
                    let command = self.command_builder.build_command(
                        0,
                        state.execution_id,
                        state.catalog_id,
                        0,
                        next_step,
                        &step_context,
                        None,
                    )?;

                    commands.push(command);
                }
            }
        }

        // Check for completion conditions
        let should_complete = self.check_completion(state, steps)?;

        let completion_status = if should_complete {
            // Check for failures
            let failed_steps: Vec<String> = state
                .steps
                .iter()
                .filter(|(_, info)| info.error.is_some())
                .map(|(name, _)| name.clone())
                .collect();

            if failed_steps.is_empty() {
                Some(CompletionStatus {
                    status: "COMPLETED".to_string(),
                    error: None,
                    failed_steps: None,
                })
            } else {
                Some(CompletionStatus {
                    status: "FAILED".to_string(),
                    error: Some(format!("Failed steps: {}", failed_steps.join(", "))),
                    failed_steps: Some(failed_steps),
                })
            }
        } else {
            None
        };

        Ok(OrchestrationResult {
            state: ExecutionState::InProgress,
            commands,
            should_complete,
            completion_status,
            events_to_emit,
        })
    }

    /// Check if the execution should complete.
    fn check_completion(
        &self,
        state: &WorkflowState,
        steps: &HashMap<&str, &Step>,
    ) -> AppResult<bool> {
        // Check if there are any running steps
        if state.has_running_steps() {
            return Ok(false);
        }

        // Check if 'end' step is completed
        if state.is_step_completed("end") {
            return Ok(true);
        }

        // Check if all steps with no successors are completed
        for (name, step) in steps {
            if step.next.is_none() && state.is_step_completed(name) {
                // Found a terminal step that's completed
                return Ok(true);
            }
        }

        Ok(false)
    }

    /// Handle a failed step.
    pub fn handle_failure(
        &self,
        _state: &WorkflowState,
        step_name: &str,
        error: &str,
    ) -> AppResult<OrchestrationResult> {
        info!("Handling failure for step '{}': {}", step_name, error);

        let events_to_emit = vec![EventToEmit {
            event_type: "step_failed".to_string(),
            node_name: Some(step_name.to_string()),
            status: "FAILED".to_string(),
            context: None,
            result: None,
            error: Some(error.to_string()),
        }];

        Ok(OrchestrationResult {
            state: ExecutionState::Failed,
            commands: vec![],
            should_complete: true,
            completion_status: Some(CompletionStatus {
                status: "FAILED".to_string(),
                error: Some(error.to_string()),
                failed_steps: Some(vec![step_name.to_string()]),
            }),
            events_to_emit,
        })
    }
}

/// Convert a serde_json::Value to HashMap (extracts top-level object keys).
fn value_to_hashmap(value: &serde_json::Value) -> HashMap<String, serde_json::Value> {
    match value {
        serde_json::Value::Object(map) => map.iter().map(|(k, v)| (k.clone(), v.clone())).collect(),
        _ => HashMap::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::playbook::types::{Metadata, NextSpec, ToolKind, ToolSpec};
    use chrono::Utc;

    fn make_step(name: &str, next: Option<&str>) -> Step {
        Step {
            step: name.to_string(),
            desc: None,
            args: None,
            vars: None,
            r#loop: None,
            tool: ToolSpec {
                kind: ToolKind::Python,
                auth: None,
                libs: None,
                args: None,
                code: Some("return {}".to_string()),
                url: None,
                method: None,
                query: None,
                connection: None,
                extra: HashMap::new(),
            },
            case: None,
            next: next.map(|n| NextSpec::Single(n.to_string())),
        }
    }

    fn make_event(event_type: &str, node_name: Option<&str>) -> Event {
        Event {
            id: 1,
            execution_id: 12345,
            catalog_id: 67890,
            event_id: 1,
            parent_event_id: None,
            parent_execution_id: None,
            event_type: event_type.to_string(),
            node_id: None,
            node_name: node_name.map(|s| s.to_string()),
            node_type: None,
            status: "".to_string(),
            context: None,
            meta: None,
            result: None,
            worker_id: None,
            attempt: None,
            created_at: Utc::now(),
        }
    }

    #[test]
    fn test_evaluate_initial_state() {
        let orchestrator = WorkflowOrchestrator::new();

        let events = vec![{
            let mut e = make_event("playbook_started", None);
            e.context = Some(serde_json::json!({
                "workload": {},
                "path": "test",
                "version": "1"
            }));
            e
        }];

        let playbook = Playbook {
            api_version: "noetl.io/v2".to_string(),
            kind: "Playbook".to_string(),
            metadata: Metadata {
                name: "test_playbook".to_string(),
                path: Some("test/path".to_string()),
                description: None,
                labels: None,
                extra: HashMap::new(),
            },
            workload: None,
            keychain: None,
            workbook: None,
            workflow: vec![
                make_step("start", Some("step2")),
                make_step("step2", Some("end")),
                make_step("end", None),
            ],
        };

        let result = orchestrator.evaluate(&events, &playbook, None).unwrap();

        assert_eq!(result.state, ExecutionState::InProgress);
        assert!(!result.commands.is_empty());
        assert!(!result.events_to_emit.is_empty());
    }

    #[test]
    fn test_handle_failure() {
        let orchestrator = WorkflowOrchestrator::new();
        let state = WorkflowState::new(12345, 67890);

        let result = orchestrator
            .handle_failure(&state, "failed_step", "Something went wrong")
            .unwrap();

        assert_eq!(result.state, ExecutionState::Failed);
        assert!(result.should_complete);
        assert!(result.completion_status.is_some());
        let status = result.completion_status.unwrap();
        assert_eq!(status.status, "FAILED");
        assert!(status.error.is_some());
    }

    #[test]
    fn test_orchestration_result_serialization() {
        let result = OrchestrationResult {
            state: ExecutionState::InProgress,
            commands: vec![],
            should_complete: false,
            completion_status: None,
            events_to_emit: vec![],
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("in_progress"));
    }
}
