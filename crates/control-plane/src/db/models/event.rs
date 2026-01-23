//! Event model for execution event sourcing.
//!
//! All workflow state is derived from events stored in the event table.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

/// Event types for workflow execution.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EventType {
    /// Playbook execution started
    PlaybookStarted,
    /// Playbook completed successfully
    PlaybookCompleted,
    /// Playbook failed
    PlaybookFailed,
    /// Workflow initialized with steps
    WorkflowInitialized,
    /// Workflow completed
    WorkflowCompleted,
    /// Workflow failed
    WorkflowFailed,
    /// Step entered
    StepEnter,
    /// Step completed
    StepCompleted,
    /// Step failed
    StepFailed,
    /// Action completed (tool execution)
    ActionCompleted,
    /// Command issued to worker
    CommandIssued,
    /// Command claimed by worker
    CommandClaimed,
    /// Command started execution
    CommandStarted,
    /// Command completed
    CommandCompleted,
    /// Command failed
    CommandFailed,
    /// Loop iteration
    LoopItem,
    /// Loop completed
    LoopDone,
    /// Step result stored
    StepResult,
    /// Error occurred
    Error,
    /// Custom event type (for extensibility)
    Custom(String),
}

impl std::fmt::Display for EventType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            EventType::PlaybookStarted => "playbook_started",
            EventType::PlaybookCompleted => "playbook.completed",
            EventType::PlaybookFailed => "playbook.failed",
            EventType::WorkflowInitialized => "workflow.initialized",
            EventType::WorkflowCompleted => "workflow.completed",
            EventType::WorkflowFailed => "workflow.failed",
            EventType::StepEnter => "step.enter",
            EventType::StepCompleted => "step_completed",
            EventType::StepFailed => "step.failed",
            EventType::ActionCompleted => "action_completed",
            EventType::CommandIssued => "command.issued",
            EventType::CommandClaimed => "command.claimed",
            EventType::CommandStarted => "command.started",
            EventType::CommandCompleted => "command.completed",
            EventType::CommandFailed => "command.failed",
            EventType::LoopItem => "loop.item",
            EventType::LoopDone => "loop.done",
            EventType::StepResult => "step_result",
            EventType::Error => "error",
            EventType::Custom(s) => s,
        };
        write!(f, "{}", s)
    }
}

impl From<&str> for EventType {
    fn from(s: &str) -> Self {
        match s {
            "playbook_started" => EventType::PlaybookStarted,
            "playbook.completed" => EventType::PlaybookCompleted,
            "playbook.failed" => EventType::PlaybookFailed,
            "workflow.initialized" | "workflow_initialized" => EventType::WorkflowInitialized,
            "workflow.completed" => EventType::WorkflowCompleted,
            "workflow.failed" => EventType::WorkflowFailed,
            "step.enter" => EventType::StepEnter,
            "step_completed" => EventType::StepCompleted,
            "step.failed" => EventType::StepFailed,
            "action_completed" => EventType::ActionCompleted,
            "command.issued" => EventType::CommandIssued,
            "command.claimed" => EventType::CommandClaimed,
            "command.started" => EventType::CommandStarted,
            "command.completed" => EventType::CommandCompleted,
            "command.failed" => EventType::CommandFailed,
            "loop.item" => EventType::LoopItem,
            "loop.done" => EventType::LoopDone,
            "step_result" => EventType::StepResult,
            "error" => EventType::Error,
            other => EventType::Custom(other.to_string()),
        }
    }
}

/// Event status values.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EventStatus {
    Started,
    Running,
    Completed,
    Failed,
    Cancelled,
    Pending,
    Claimed,
}

impl std::fmt::Display for EventStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            EventStatus::Started => "STARTED",
            EventStatus::Running => "RUNNING",
            EventStatus::Completed => "COMPLETED",
            EventStatus::Failed => "FAILED",
            EventStatus::Cancelled => "CANCELLED",
            EventStatus::Pending => "PENDING",
            EventStatus::Claimed => "CLAIMED",
        };
        write!(f, "{}", s)
    }
}

impl From<&str> for EventStatus {
    fn from(s: &str) -> Self {
        match s.to_uppercase().as_str() {
            "STARTED" => EventStatus::Started,
            "RUNNING" => EventStatus::Running,
            "COMPLETED" => EventStatus::Completed,
            "FAILED" => EventStatus::Failed,
            "CANCELLED" => EventStatus::Cancelled,
            "PENDING" => EventStatus::Pending,
            "CLAIMED" => EventStatus::Claimed,
            _ => EventStatus::Pending,
        }
    }
}

/// Database event record.
#[derive(Debug, Clone, FromRow, Serialize, Deserialize)]
pub struct Event {
    /// Primary key (same as event_id for events).
    pub id: i64,

    /// Execution identifier.
    pub execution_id: i64,

    /// Catalog entry ID.
    pub catalog_id: i64,

    /// Event identifier (snowflake ID).
    pub event_id: i64,

    /// Parent event ID for ordering/hierarchy.
    pub parent_event_id: Option<i64>,

    /// Parent execution ID (for nested playbooks).
    pub parent_execution_id: Option<i64>,

    /// Event type.
    pub event_type: String,

    /// Node identifier.
    pub node_id: Option<String>,

    /// Node name (step name).
    pub node_name: Option<String>,

    /// Node type (step, workflow, execution, etc.).
    pub node_type: Option<String>,

    /// Event status.
    pub status: String,

    /// Event context (JSON).
    pub context: Option<serde_json::Value>,

    /// Event metadata (JSON).
    pub meta: Option<serde_json::Value>,

    /// Result data (JSON) - for command results.
    pub result: Option<serde_json::Value>,

    /// Worker ID (for command events).
    pub worker_id: Option<String>,

    /// Attempt number (for retries).
    pub attempt: Option<i32>,

    /// When the event was created.
    pub created_at: DateTime<Utc>,
}

/// Request to create a new event.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventCreateRequest {
    /// Execution identifier.
    pub execution_id: i64,

    /// Catalog entry ID.
    pub catalog_id: i64,

    /// Parent event ID.
    pub parent_event_id: Option<i64>,

    /// Parent execution ID.
    pub parent_execution_id: Option<i64>,

    /// Event type.
    pub event_type: String,

    /// Node identifier.
    pub node_id: Option<String>,

    /// Node name (step name).
    pub node_name: Option<String>,

    /// Node type.
    pub node_type: Option<String>,

    /// Event status.
    pub status: String,

    /// Event context (JSON).
    pub context: Option<serde_json::Value>,

    /// Event metadata (JSON).
    pub meta: Option<serde_json::Value>,

    /// Result data (JSON).
    pub result: Option<serde_json::Value>,

    /// Worker ID.
    pub worker_id: Option<String>,

    /// Attempt number.
    pub attempt: Option<i32>,
}

/// Event response for API.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventResponse {
    /// Event ID.
    pub event_id: String,

    /// Execution ID.
    pub execution_id: String,

    /// Event type.
    pub event_type: String,

    /// Node name.
    pub node_name: Option<String>,

    /// Status.
    pub status: String,

    /// Context.
    pub context: Option<serde_json::Value>,

    /// Result.
    pub result: Option<serde_json::Value>,

    /// Created at.
    pub created_at: DateTime<Utc>,
}

impl From<Event> for EventResponse {
    fn from(e: Event) -> Self {
        Self {
            event_id: e.event_id.to_string(),
            execution_id: e.execution_id.to_string(),
            event_type: e.event_type,
            node_name: e.node_name,
            status: e.status,
            context: e.context,
            result: e.result,
            created_at: e.created_at,
        }
    }
}

/// List of events response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventListResponse {
    /// List of events.
    pub events: Vec<EventResponse>,

    /// Total count.
    pub total: i64,
}

/// Worker event payload (from worker completing a command).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkerEventPayload {
    /// Command ID (event_id of command.issued event).
    pub command_id: String,

    /// Worker ID.
    pub worker_id: String,

    /// Event type (command.completed, command.failed, etc.).
    pub event_type: String,

    /// Result data.
    pub result: Option<serde_json::Value>,

    /// Error message (for failed events).
    pub error: Option<String>,

    /// Execution duration in milliseconds.
    pub duration_ms: Option<i64>,

    /// Attempt number.
    pub attempt: Option<i32>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_event_type_display() {
        assert_eq!(EventType::PlaybookStarted.to_string(), "playbook_started");
        assert_eq!(
            EventType::WorkflowInitialized.to_string(),
            "workflow.initialized"
        );
        assert_eq!(EventType::CommandCompleted.to_string(), "command.completed");
    }

    #[test]
    fn test_event_type_from_str() {
        assert_eq!(
            EventType::from("playbook_started"),
            EventType::PlaybookStarted
        );
        assert_eq!(
            EventType::from("workflow.initialized"),
            EventType::WorkflowInitialized
        );
        assert_eq!(
            EventType::from("command.completed"),
            EventType::CommandCompleted
        );
        assert_eq!(
            EventType::from("custom_event"),
            EventType::Custom("custom_event".to_string())
        );
    }

    #[test]
    fn test_event_status_display() {
        assert_eq!(EventStatus::Started.to_string(), "STARTED");
        assert_eq!(EventStatus::Completed.to_string(), "COMPLETED");
        assert_eq!(EventStatus::Failed.to_string(), "FAILED");
    }

    #[test]
    fn test_event_status_from_str() {
        assert_eq!(EventStatus::from("started"), EventStatus::Started);
        assert_eq!(EventStatus::from("COMPLETED"), EventStatus::Completed);
        assert_eq!(EventStatus::from("Failed"), EventStatus::Failed);
    }
}
