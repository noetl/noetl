//! Execution state reconstruction from events.
//!
//! Provides state reconstruction for event-sourced workflow execution.

use std::collections::HashMap;
use std::time::Instant;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::db::models::Event;

/// High-level execution state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionState {
    /// Execution has not started yet.
    Initial,
    /// Execution is in progress.
    InProgress,
    /// Execution completed successfully.
    Completed,
    /// Execution failed.
    Failed,
    /// Execution was cancelled.
    Cancelled,
}

impl std::fmt::Display for ExecutionState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Initial => write!(f, "initial"),
            Self::InProgress => write!(f, "in_progress"),
            Self::Completed => write!(f, "completed"),
            Self::Failed => write!(f, "failed"),
            Self::Cancelled => write!(f, "cancelled"),
        }
    }
}

impl From<&str> for ExecutionState {
    fn from(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "initial" | "pending" => Self::Initial,
            "in_progress" | "running" => Self::InProgress,
            "completed" | "success" => Self::Completed,
            "failed" | "error" => Self::Failed,
            "cancelled" | "canceled" => Self::Cancelled,
            _ => Self::Initial,
        }
    }
}

/// State of a single workflow step.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StepState {
    /// Step has not been entered yet.
    Pending,
    /// Step has been entered (step.enter).
    Entered,
    /// Command has been issued.
    CommandIssued,
    /// Command has been claimed by a worker.
    CommandClaimed,
    /// Command execution has started.
    CommandStarted,
    /// Step completed successfully.
    Completed,
    /// Step failed.
    Failed,
    /// Step was skipped.
    Skipped,
}

impl std::fmt::Display for StepState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Pending => write!(f, "pending"),
            Self::Entered => write!(f, "entered"),
            Self::CommandIssued => write!(f, "command_issued"),
            Self::CommandClaimed => write!(f, "command_claimed"),
            Self::CommandStarted => write!(f, "command_started"),
            Self::Completed => write!(f, "completed"),
            Self::Failed => write!(f, "failed"),
            Self::Skipped => write!(f, "skipped"),
        }
    }
}

/// Step information including state and result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepInfo {
    pub name: String,
    pub state: StepState,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub entered_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completed_at: Option<DateTime<Utc>>,
    pub attempt: i32,
}

impl StepInfo {
    /// Create a new step info in pending state.
    pub fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
            state: StepState::Pending,
            result: None,
            error: None,
            entered_at: None,
            completed_at: None,
            attempt: 0,
        }
    }
}

/// Complete workflow state reconstructed from events.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowState {
    pub execution_id: i64,
    pub catalog_id: i64,
    pub state: ExecutionState,
    pub steps: HashMap<String, StepInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub workload: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub started_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completed_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_execution_id: Option<i64>,
}

impl WorkflowState {
    /// Create a new workflow state.
    pub fn new(execution_id: i64, catalog_id: i64) -> Self {
        Self {
            execution_id,
            catalog_id,
            state: ExecutionState::Initial,
            steps: HashMap::new(),
            workload: None,
            path: None,
            version: None,
            started_at: None,
            completed_at: None,
            parent_execution_id: None,
        }
    }

    /// Reconstruct workflow state from a list of events.
    pub fn from_events(events: &[Event]) -> Option<Self> {
        let start = Instant::now();

        if events.is_empty() {
            return None;
        }

        // Get execution_id and catalog_id from first event
        let first = &events[0];
        let mut state = Self::new(first.execution_id, first.catalog_id);

        // Process events in order
        for event in events {
            state.apply_event(event);
        }

        let duration = start.elapsed();
        let event_count = events.len();

        // Log performance metrics for state reconstruction
        tracing::info!(
            target: "noetl.performance",
            execution_id = %first.execution_id,
            phase = "state_reconstruction",
            event_count = %event_count,
            step_count = %state.steps.len(),
            duration_ms = %duration.as_millis(),
            "State reconstructed from events"
        );

        // Warn if reconstruction is slow (potential bottleneck)
        if duration.as_millis() > 100 || event_count > 50 {
            tracing::warn!(
                target: "noetl.performance",
                execution_id = %first.execution_id,
                event_count = %event_count,
                duration_ms = %duration.as_millis(),
                "Slow state reconstruction detected - consider optimizing event loading"
            );
        }

        Some(state)
    }

    /// Apply a single event to update the workflow state.
    pub fn apply_event(&mut self, event: &Event) {
        match event.event_type.as_str() {
            "playbook_started" => {
                self.state = ExecutionState::InProgress;
                self.started_at = Some(event.created_at);
                self.parent_execution_id = event.parent_execution_id;

                // Extract workload from context
                if let Some(context) = &event.context {
                    if let Some(workload) = context.get("workload") {
                        self.workload = Some(workload.clone());
                    }
                    if let Some(path) = context.get("path").and_then(|v| v.as_str()) {
                        self.path = Some(path.to_string());
                    }
                    if let Some(version) = context.get("version").and_then(|v| v.as_str()) {
                        self.version = Some(version.to_string());
                    }
                }
            }
            "playbook_completed" | "playbook.completed" => {
                self.state = ExecutionState::Completed;
                self.completed_at = Some(event.created_at);
            }
            "playbook_failed" | "playbook.failed" => {
                self.state = ExecutionState::Failed;
                self.completed_at = Some(event.created_at);
            }
            "playbook.cancelled" => {
                self.state = ExecutionState::Cancelled;
                self.completed_at = Some(event.created_at);
            }
            "step.enter" | "step_enter" | "step_started" => {
                if let Some(name) = &event.node_name {
                    let step = self
                        .steps
                        .entry(name.clone())
                        .or_insert_with(|| StepInfo::new(name));
                    step.state = StepState::Entered;
                    step.entered_at = Some(event.created_at);
                }
            }
            "command.issued" => {
                if let Some(name) = &event.node_name {
                    let step = self
                        .steps
                        .entry(name.clone())
                        .or_insert_with(|| StepInfo::new(name));
                    step.state = StepState::CommandIssued;
                }
            }
            "command.claimed" => {
                if let Some(name) = &event.node_name {
                    let step = self
                        .steps
                        .entry(name.clone())
                        .or_insert_with(|| StepInfo::new(name));
                    step.state = StepState::CommandClaimed;
                }
            }
            "command.started" | "action_started" => {
                if let Some(name) = &event.node_name {
                    let step = self
                        .steps
                        .entry(name.clone())
                        .or_insert_with(|| StepInfo::new(name));
                    step.state = StepState::CommandStarted;
                    if let Some(attempt) = event.attempt {
                        step.attempt = attempt;
                    }
                }
            }
            "command.completed" | "action_completed" | "step.exit" | "step_completed" => {
                if let Some(name) = &event.node_name {
                    let step = self
                        .steps
                        .entry(name.clone())
                        .or_insert_with(|| StepInfo::new(name));
                    step.state = StepState::Completed;
                    step.completed_at = Some(event.created_at);
                    step.result = event.result.clone();
                }
            }
            "command.failed" | "action_failed" | "step_failed" => {
                if let Some(name) = &event.node_name {
                    let step = self
                        .steps
                        .entry(name.clone())
                        .or_insert_with(|| StepInfo::new(name));
                    step.state = StepState::Failed;
                    step.completed_at = Some(event.created_at);
                    // Extract error from result or use status
                    if let Some(result) = &event.result {
                        if let Some(error) = result.get("error").and_then(|v| v.as_str()) {
                            step.error = Some(error.to_string());
                        }
                    }
                }
            }
            _ => {}
        }
    }

    /// Get the result for a specific step.
    pub fn get_step_result(&self, step_name: &str) -> Option<&serde_json::Value> {
        self.steps.get(step_name).and_then(|s| s.result.as_ref())
    }

    /// Get all step results as a map.
    pub fn get_all_results(&self) -> HashMap<String, serde_json::Value> {
        self.steps
            .iter()
            .filter_map(|(name, info)| info.result.clone().map(|r| (name.clone(), r)))
            .collect()
    }

    /// Check if a step has completed (successfully or with failure).
    pub fn is_step_done(&self, step_name: &str) -> bool {
        self.steps
            .get(step_name)
            .map(|s| {
                matches!(
                    s.state,
                    StepState::Completed | StepState::Failed | StepState::Skipped
                )
            })
            .unwrap_or(false)
    }

    /// Check if a step completed successfully.
    pub fn is_step_completed(&self, step_name: &str) -> bool {
        self.steps
            .get(step_name)
            .map(|s| matches!(s.state, StepState::Completed))
            .unwrap_or(false)
    }

    /// Check if a step failed.
    pub fn is_step_failed(&self, step_name: &str) -> bool {
        self.steps
            .get(step_name)
            .map(|s| matches!(s.state, StepState::Failed))
            .unwrap_or(false)
    }

    /// Get the names of all completed steps.
    pub fn completed_steps(&self) -> Vec<&str> {
        self.steps
            .iter()
            .filter(|(_, info)| matches!(info.state, StepState::Completed))
            .map(|(name, _)| name.as_str())
            .collect()
    }

    /// Get the names of all running steps.
    pub fn running_steps(&self) -> Vec<&str> {
        self.steps
            .iter()
            .filter(|(_, info)| {
                matches!(
                    info.state,
                    StepState::Entered
                        | StepState::CommandIssued
                        | StepState::CommandClaimed
                        | StepState::CommandStarted
                )
            })
            .map(|(name, _)| name.as_str())
            .collect()
    }

    /// Check if there are any running steps.
    pub fn has_running_steps(&self) -> bool {
        !self.running_steps().is_empty()
    }

    /// Build a context map for template rendering.
    pub fn build_context(&self) -> serde_json::Value {
        let mut context = serde_json::Map::new();

        // Add workload variables
        if let Some(serde_json::Value::Object(wl)) = &self.workload {
            for (k, v) in wl {
                context.insert(k.clone(), v.clone());
            }
        }

        // Add step results under 'steps' namespace
        let mut steps = serde_json::Map::new();
        for (name, info) in &self.steps {
            if let Some(result) = &info.result {
                steps.insert(name.clone(), result.clone());
            }
        }
        context.insert("steps".to_string(), serde_json::Value::Object(steps));

        // Add execution metadata
        context.insert(
            "execution_id".to_string(),
            serde_json::json!(self.execution_id.to_string()),
        );
        context.insert(
            "catalog_id".to_string(),
            serde_json::json!(self.catalog_id.to_string()),
        );

        if let Some(path) = &self.path {
            context.insert("path".to_string(), serde_json::json!(path));
        }
        if let Some(version) = &self.version {
            context.insert("version".to_string(), serde_json::json!(version));
        }

        serde_json::Value::Object(context)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn test_execution_state_display() {
        assert_eq!(ExecutionState::Initial.to_string(), "initial");
        assert_eq!(ExecutionState::InProgress.to_string(), "in_progress");
        assert_eq!(ExecutionState::Completed.to_string(), "completed");
    }

    #[test]
    fn test_execution_state_from_str() {
        assert_eq!(ExecutionState::from("initial"), ExecutionState::Initial);
        assert_eq!(ExecutionState::from("RUNNING"), ExecutionState::InProgress);
        assert_eq!(ExecutionState::from("completed"), ExecutionState::Completed);
        assert_eq!(ExecutionState::from("FAILED"), ExecutionState::Failed);
    }

    #[test]
    fn test_workflow_state_from_events() {
        let events = vec![
            {
                let mut e = make_event("playbook_started", None);
                e.context = Some(serde_json::json!({
                    "workload": {"key": "value"},
                    "path": "test/playbook",
                    "version": "1"
                }));
                e
            },
            make_event("step.enter", Some("step1")),
            make_event("command.issued", Some("step1")),
            {
                let mut e = make_event("command.completed", Some("step1"));
                e.result = Some(serde_json::json!({"output": "success"}));
                e
            },
        ];

        let state = WorkflowState::from_events(&events).unwrap();
        assert_eq!(state.execution_id, 12345);
        assert_eq!(state.state, ExecutionState::InProgress);
        assert!(state.is_step_completed("step1"));
        assert_eq!(
            state.get_step_result("step1"),
            Some(&serde_json::json!({"output": "success"}))
        );
    }

    #[test]
    fn test_workflow_state_build_context() {
        let mut state = WorkflowState::new(12345, 67890);
        state.workload = Some(serde_json::json!({"var1": "value1"}));
        state.path = Some("test/path".to_string());

        let mut step_info = StepInfo::new("step1");
        step_info.result = Some(serde_json::json!({"output": "result1"}));
        state.steps.insert("step1".to_string(), step_info);

        let context = state.build_context();
        assert_eq!(context.get("var1").and_then(|v| v.as_str()), Some("value1"));
        assert_eq!(
            context.get("path").and_then(|v| v.as_str()),
            Some("test/path")
        );
        assert!(context.get("steps").is_some());
    }

    #[test]
    fn test_step_state_transitions() {
        let mut state = WorkflowState::new(1, 1);

        state.apply_event(&make_event("step.enter", Some("step1")));
        assert_eq!(state.steps.get("step1").unwrap().state, StepState::Entered);

        state.apply_event(&make_event("command.issued", Some("step1")));
        assert_eq!(
            state.steps.get("step1").unwrap().state,
            StepState::CommandIssued
        );

        state.apply_event(&make_event("command.completed", Some("step1")));
        assert_eq!(
            state.steps.get("step1").unwrap().state,
            StepState::Completed
        );
    }
}
