use async_graphql::{ID, Json, SimpleObject};
use serde::{Deserialize, Serialize};

/// Represents a NoETL playbook execution instance.
///
/// An execution is created when a playbook is triggered and tracks the lifecycle
/// of the workflow through its various states (pending, running, completed, failed).
/// Each execution has a unique identifier that can be used to query status,
/// retrieve results, and monitor progress through the NoETL event system.
///
/// # Lifecycle
///
/// 1. **Created**: Execution record initialized with "pending" status
/// 2. **Queued**: Job enqueued for worker processing
/// 3. **Running**: Worker actively executing workflow steps
/// 4. **Completed/Failed**: Terminal state with final results
///
/// # Usage
///
/// ```graphql
/// mutation {
///   executePlaybook(name: "my_workflow", variables: {key: "value"}) {
///     id
///     name
///     status
///   }
/// }
/// ```
#[derive(SimpleObject, Clone, Debug)]
pub struct Execution {
    /// Unique execution identifier.
    ///
    /// This ID is used to:
    /// - Query execution status and progress
    /// - Retrieve execution results and outputs
    /// - Access execution events and logs
    /// - Track workflow state in the NoETL event store
    pub id: ID,

    /// Name of the executed playbook.
    ///
    /// Corresponds to the `metadata.name` field in the playbook YAML definition.
    /// Used to identify which workflow template is being executed.
    pub name: String,

    /// Current execution status.
    ///
    /// Common status values:
    /// - `"pending"`: Execution created, awaiting worker assignment
    /// - `"running"`: Worker actively processing workflow steps
    /// - `"completed"`: All workflow steps completed successfully
    /// - `"failed"`: Execution terminated due to error
    /// - `"cancelled"`: Execution manually stopped
    ///
    /// Status is `None` if execution metadata is unavailable.
    pub status: Option<String>,
}
