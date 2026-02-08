//! Command generation for workers.
//!
//! Generates command payloads that workers pick up and execute.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::error::AppResult;
use crate::playbook::types::{Step, ToolCall, ToolDefinition, ToolSpec};
use crate::template::TemplateRenderer;

/// Command to be executed by a worker.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Command {
    /// Unique command ID (event_id).
    pub command_id: i64,
    /// Execution ID this command belongs to.
    pub execution_id: i64,
    /// Catalog ID for the playbook.
    pub catalog_id: i64,
    /// Parent event ID that triggered this command.
    pub parent_event_id: i64,
    /// Step name.
    pub step_name: String,
    /// Tool specification.
    pub tool: ToolCommand,
    /// Rendered context for the command.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub context: Option<HashMap<String, serde_json::Value>>,
    /// Additional metadata.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<serde_json::Value>,
    /// Iterator metadata if this is part of a loop.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub iterator: Option<IteratorMetadata>,
}

/// Tool command specification.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCommand {
    /// Tool kind.
    pub kind: String,
    /// Tool configuration/arguments.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub config: Option<serde_json::Value>,
    /// Timeout in seconds.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timeout: Option<i64>,
}

/// Iterator metadata for loop iterations.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IteratorMetadata {
    /// Parent execution ID for the loop.
    pub parent_execution_id: i64,
    /// Iterator step name.
    pub iterator_step: String,
    /// Current iteration index.
    pub index: usize,
    /// Total number of iterations.
    pub total: usize,
    /// Current iteration item.
    pub item: serde_json::Value,
    /// Variable name for the item.
    pub item_var: String,
}

/// Builder for creating commands.
pub struct CommandBuilder {
    renderer: TemplateRenderer,
}

impl Default for CommandBuilder {
    fn default() -> Self {
        Self::new()
    }
}

impl CommandBuilder {
    /// Create a new command builder.
    pub fn new() -> Self {
        Self {
            renderer: TemplateRenderer::new(),
        }
    }

    /// Build a command from a step definition.
    #[allow(clippy::too_many_arguments)]
    pub fn build_command(
        &self,
        command_id: i64,
        execution_id: i64,
        catalog_id: i64,
        parent_event_id: i64,
        step: &Step,
        context: &HashMap<String, serde_json::Value>,
        metadata: Option<&serde_json::Value>,
    ) -> AppResult<Command> {
        // Build tool command based on definition type
        let tool_command = self.build_tool_from_definition(&step.tool, context)?;

        Ok(Command {
            command_id,
            execution_id,
            catalog_id,
            parent_event_id,
            step_name: step.step.clone(),
            tool: tool_command,
            context: Some(context.clone()),
            metadata: metadata.cloned(),
            iterator: None,
        })
    }

    /// Build a command for a loop iteration.
    #[allow(clippy::too_many_arguments)]
    pub fn build_iteration_command(
        &self,
        command_id: i64,
        execution_id: i64,
        catalog_id: i64,
        parent_event_id: i64,
        step: &Step,
        context: &HashMap<String, serde_json::Value>,
        iterator: IteratorMetadata,
    ) -> AppResult<Command> {
        // Build context with iterator variables
        let mut iter_context = context.clone();
        iter_context.insert(iterator.item_var.clone(), iterator.item.clone());
        iter_context.insert("_index".to_string(), serde_json::json!(iterator.index));
        iter_context.insert("_total".to_string(), serde_json::json!(iterator.total));

        // Build tool command from definition with iterator context
        let tool_command = self.build_tool_from_definition(&step.tool, &iter_context)?;

        Ok(Command {
            command_id,
            execution_id,
            catalog_id,
            parent_event_id,
            step_name: step.step.clone(),
            tool: tool_command,
            context: Some(iter_context),
            metadata: None,
            iterator: Some(iterator),
        })
    }

    /// Build a tool command from a tool definition (single or pipeline).
    fn build_tool_from_definition(
        &self,
        tool: &ToolDefinition,
        context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<ToolCommand> {
        match tool {
            ToolDefinition::Single(spec) => self.build_tool_command(spec, context),
            ToolDefinition::Pipeline(tasks) => {
                // For pipelines, create a task_sequence tool command
                // The worker will execute each task in sequence
                let pipeline_config = serde_json::to_value(tasks).ok();
                let config = if let Some(cfg) = pipeline_config {
                    Some(self.renderer.render_value(&cfg, context)?)
                } else {
                    None
                };

                Ok(ToolCommand {
                    kind: "task_sequence".to_string(),
                    config,
                    timeout: None,
                })
            }
        }
    }

    /// Build a tool command from a single tool spec.
    fn build_tool_command(
        &self,
        tool: &ToolSpec,
        context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<ToolCommand> {
        // Get kind as string
        let kind = tool.kind.to_string();

        // Build config from tool spec using ToolCall
        let tool_call = ToolCall::from_spec(tool);
        let config_value = serde_json::to_value(&tool_call.config).ok();

        // Render any templates in the config
        let config = if let Some(cfg) = config_value {
            Some(self.renderer.render_value(&cfg, context)?)
        } else {
            None
        };

        Ok(ToolCommand {
            kind,
            config,
            timeout: None,
        })
    }

    /// Build a command for a playbook call (nested execution).
    #[allow(clippy::too_many_arguments)]
    pub fn build_playbook_call(
        &self,
        command_id: i64,
        execution_id: i64,
        catalog_id: i64,
        parent_event_id: i64,
        step_name: &str,
        playbook_path: &str,
        playbook_version: Option<&str>,
        args: Option<&serde_json::Value>,
        context: &HashMap<String, serde_json::Value>,
    ) -> Command {
        let config = serde_json::json!({
            "path": playbook_path,
            "version": playbook_version.unwrap_or("latest"),
            "args": args.cloned().unwrap_or(serde_json::Value::Null),
        });

        Command {
            command_id,
            execution_id,
            catalog_id,
            parent_event_id,
            step_name: step_name.to_string(),
            tool: ToolCommand {
                kind: "playbook".to_string(),
                config: Some(config),
                timeout: None,
            },
            context: Some(context.clone()),
            metadata: None,
            iterator: None,
        }
    }

    /// Build a noop command (for steps without tools).
    pub fn build_noop_command(
        &self,
        command_id: i64,
        execution_id: i64,
        catalog_id: i64,
        parent_event_id: i64,
        step_name: &str,
        context: &HashMap<String, serde_json::Value>,
    ) -> Command {
        Command {
            command_id,
            execution_id,
            catalog_id,
            parent_event_id,
            step_name: step_name.to_string(),
            tool: ToolCommand {
                kind: "noop".to_string(),
                config: None,
                timeout: None,
            },
            context: Some(context.clone()),
            metadata: None,
            iterator: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::playbook::types::ToolKind;

    #[test]
    fn test_command_serialization() {
        let mut context = HashMap::new();
        context.insert("key".to_string(), serde_json::json!("value"));

        let command = Command {
            command_id: 12345,
            execution_id: 67890,
            catalog_id: 11111,
            parent_event_id: 22222,
            step_name: "test_step".to_string(),
            tool: ToolCommand {
                kind: "http".to_string(),
                config: Some(serde_json::json!({
                    "url": "https://example.com",
                    "method": "GET"
                })),
                timeout: Some(30),
            },
            context: Some(context),
            metadata: None,
            iterator: None,
        };

        let json = serde_json::to_string(&command).unwrap();
        assert!(json.contains("test_step"));
        assert!(json.contains("http"));
        assert!(json.contains("example.com"));
    }

    #[test]
    fn test_build_command() {
        let builder = CommandBuilder::new();
        let step = Step {
            step: "test_step".to_string(),
            desc: None,
            spec: None,
            when: None,
            args: None,
            vars: None,
            r#loop: None,
            tool: ToolDefinition::Single(ToolSpec {
                kind: ToolKind::Http,
                auth: None,
                libs: None,
                args: None,
                code: None,
                url: Some("https://{{ host }}/api".to_string()),
                method: Some("GET".to_string()),
                query: None,
                command: None,
                connection: None,
                params: None,
                headers: None,
                eval: None,
                output_select: None,
                extra: HashMap::new(),
            }),
            next: None,
        };

        let mut context = HashMap::new();
        context.insert("host".to_string(), serde_json::json!("example.com"));

        let command = builder
            .build_command(1, 2, 3, 4, &step, &context, None)
            .unwrap();

        assert_eq!(command.step_name, "test_step");
        assert_eq!(command.tool.kind, "http");

        // Check that template was rendered
        let config = command.tool.config.unwrap();
        assert_eq!(
            config.get("url").and_then(|v| v.as_str()),
            Some("https://example.com/api")
        );
    }

    #[test]
    fn test_build_iteration_command() {
        let builder = CommandBuilder::new();
        let step = Step {
            step: "process_item".to_string(),
            desc: None,
            spec: None,
            when: None,
            args: None,
            vars: None,
            r#loop: None,
            tool: ToolDefinition::Single(ToolSpec {
                kind: ToolKind::Python,
                auth: None,
                libs: None,
                args: None,
                code: Some("return {'item': '{{ item }}'}".to_string()),
                url: None,
                method: None,
                query: None,
                command: None,
                connection: None,
                params: None,
                headers: None,
                eval: None,
                output_select: None,
                extra: HashMap::new(),
            }),
            next: None,
        };

        let context = HashMap::new();
        let iterator = IteratorMetadata {
            parent_execution_id: 100,
            iterator_step: "loop_step".to_string(),
            index: 2,
            total: 5,
            item: serde_json::json!("test_value"),
            item_var: "item".to_string(),
        };

        let command = builder
            .build_iteration_command(1, 2, 3, 4, &step, &context, iterator)
            .unwrap();

        assert!(command.iterator.is_some());
        let iter = command.iterator.unwrap();
        assert_eq!(iter.index, 2);
        assert_eq!(iter.total, 5);
    }

    #[test]
    fn test_build_noop_command() {
        let builder = CommandBuilder::new();
        let mut context = HashMap::new();
        context.insert("key".to_string(), serde_json::json!("value"));

        let command = builder.build_noop_command(1, 2, 3, 4, "noop_step", &context);

        assert_eq!(command.tool.kind, "noop");
        assert!(command.tool.config.is_none());
    }

    #[test]
    fn test_build_pipeline_command() {
        let builder = CommandBuilder::new();

        // Create a pipeline with multiple tasks
        let mut fetch_task = HashMap::new();
        fetch_task.insert(
            "fetch".to_string(),
            ToolSpec {
                kind: ToolKind::Http,
                auth: None,
                libs: None,
                args: None,
                code: None,
                url: Some("https://api.example.com".to_string()),
                method: Some("GET".to_string()),
                query: None,
                command: None,
                connection: None,
                params: None,
                headers: None,
                eval: None,
                output_select: None,
                extra: HashMap::new(),
            },
        );

        let mut transform_task = HashMap::new();
        transform_task.insert(
            "transform".to_string(),
            ToolSpec {
                kind: ToolKind::Python,
                auth: None,
                libs: None,
                args: None,
                code: Some("result = {'processed': True}".to_string()),
                url: None,
                method: None,
                query: None,
                command: None,
                connection: None,
                params: None,
                headers: None,
                eval: None,
                output_select: None,
                extra: HashMap::new(),
            },
        );

        let step = Step {
            step: "pipeline_step".to_string(),
            desc: None,
            spec: None,
            when: None,
            args: None,
            vars: None,
            r#loop: None,
            tool: ToolDefinition::Pipeline(vec![fetch_task, transform_task]),
            next: None,
        };

        let context = HashMap::new();

        let command = builder
            .build_command(1, 2, 3, 4, &step, &context, None)
            .unwrap();

        assert_eq!(command.step_name, "pipeline_step");
        assert_eq!(command.tool.kind, "task_sequence");
        assert!(command.tool.config.is_some());
    }
}
