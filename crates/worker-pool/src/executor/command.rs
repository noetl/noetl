//! Command executor.

use anyhow::Result;
use noetl_tools::context::ExecutionContext;
use noetl_tools::registry::{ToolConfig, ToolRegistry};
use noetl_tools::tools::create_default_registry;

use crate::client::{Command, ControlPlaneClient, WorkerEvent};
use crate::executor::case_evaluator::{CaseAction, CaseEvaluator};

/// Command executor that runs tools and evaluates cases.
pub struct CommandExecutor {
    /// Tool registry with all available tools.
    tool_registry: ToolRegistry,

    /// Case evaluator for when/then logic.
    case_evaluator: CaseEvaluator,

    /// Control plane client for event emission.
    client: ControlPlaneClient,

    /// Worker ID.
    worker_id: String,
}

impl CommandExecutor {
    /// Create a new command executor.
    pub fn new(client: ControlPlaneClient, worker_id: String) -> Self {
        Self {
            tool_registry: create_default_registry(),
            case_evaluator: CaseEvaluator::new(),
            client,
            worker_id,
        }
    }

    /// Execute a command.
    pub async fn execute(&self, command: &Command) -> Result<()> {
        // Build execution context
        let mut ctx = ExecutionContext::new(
            command.execution_id,
            &command.step,
            "", // Server URL not needed in context for now
        )
        .with_worker_id(&self.worker_id)
        .with_command_id(&command.command_id);

        // Add variables and secrets
        ctx.variables = command.variables.clone();
        ctx.secrets = command.secrets.clone();

        // Emit command.started event
        self.emit_event("command.started", command.execution_id, serde_json::json!({
            "command_id": command.command_id,
            "worker_id": self.worker_id,
            "step": command.step,
        }))
        .await?;

        // Parse tool configuration
        let tool_config: ToolConfig = serde_json::from_value(command.tool.clone())?;

        tracing::debug!(
            execution_id = command.execution_id,
            step = %command.step,
            tool = %tool_config.kind,
            "Executing tool"
        );

        // Execute the tool
        let tool_result = match self.tool_registry.execute_from_config(&tool_config, &ctx).await {
            Ok(result) => {
                // Emit call.done event
                self.emit_event("call.done", command.execution_id, serde_json::json!({
                    "command_id": command.command_id,
                    "call_index": ctx.call_index,
                    "result": result,
                }))
                .await?;

                result
            }
            Err(e) => {
                // Emit call.error event
                self.emit_event("call.error", command.execution_id, serde_json::json!({
                    "command_id": command.command_id,
                    "call_index": ctx.call_index,
                    "error": e.to_string(),
                }))
                .await?;

                // Emit command.failed event
                self.emit_event("command.failed", command.execution_id, serde_json::json!({
                    "command_id": command.command_id,
                    "error": e.to_string(),
                }))
                .await?;

                return Err(e.into());
            }
        };

        // Parse cases from command
        let cases: Vec<crate::executor::case_evaluator::Case> =
            command.cases.iter().filter_map(|c| serde_json::from_value(c.clone()).ok()).collect();

        // Evaluate cases
        if !cases.is_empty() {
            if let Some(case_result) = self.case_evaluator.evaluate(&cases, &ctx, tool_result.data.as_ref())? {
                match case_result.action {
                    CaseAction::Exit { status, data } => {
                        // Emit step.exit event
                        self.emit_event("step.exit", command.execution_id, serde_json::json!({
                            "step": command.step,
                            "status": status,
                            "data": data,
                        }))
                        .await?;
                    }
                    CaseAction::SetVar { name, value } => {
                        // Set variable via API
                        self.client.set_variable(command.execution_id, &name, value).await?;
                    }
                    CaseAction::Fail { message } => {
                        // Emit command.failed event
                        self.emit_event("command.failed", command.execution_id, serde_json::json!({
                            "command_id": command.command_id,
                            "error": message,
                        }))
                        .await?;

                        return Err(anyhow::anyhow!("Case evaluation failed: {}", message));
                    }
                    CaseAction::Continue | CaseAction::Goto { .. } | CaseAction::Retry { .. } => {
                        // These are handled by the orchestrator
                    }
                }
            }
        }

        // Emit command.completed event
        self.emit_event("command.completed", command.execution_id, serde_json::json!({
            "command_id": command.command_id,
            "status": tool_result.status.to_string(),
        }))
        .await?;

        Ok(())
    }

    /// Emit an event to the control plane.
    async fn emit_event(
        &self,
        event_type: &str,
        execution_id: i64,
        payload: serde_json::Value,
    ) -> Result<()> {
        let event = WorkerEvent {
            event_type: event_type.to_string(),
            execution_id,
            payload,
        };

        self.client.emit_event_with_retry(event, 3).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_command_executor_creation() {
        let client = ControlPlaneClient::new("http://localhost:8082");
        let executor = CommandExecutor::new(client, "worker-1".to_string());

        // Verify tools are registered
        assert!(executor.tool_registry.has("shell"));
        assert!(executor.tool_registry.has("http"));
        assert!(executor.tool_registry.has("rhai"));
    }
}
