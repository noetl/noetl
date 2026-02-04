//! NoETL DSL v2 Types
//!
//! Complete type definitions for NoETL playbooks:
//! - tool.kind pattern for tool configuration
//! - Step-level case/when/then for event-driven control flow
//! - Step-level loop for iteration
//! - Event-driven architecture

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Supported tool kinds.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ToolKind {
    Http,
    Postgres,
    Duckdb,
    Ducklake,
    Python,
    Workbook,
    Playbook,
    Playbooks,
    Secrets,
    Iterator,
    Container,
    Script,
    Snowflake,
    Transfer,
    SnowflakeTransfer,
    Gcs,
}

impl std::fmt::Display for ToolKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            ToolKind::Http => "http",
            ToolKind::Postgres => "postgres",
            ToolKind::Duckdb => "duckdb",
            ToolKind::Ducklake => "ducklake",
            ToolKind::Python => "python",
            ToolKind::Workbook => "workbook",
            ToolKind::Playbook => "playbook",
            ToolKind::Playbooks => "playbooks",
            ToolKind::Secrets => "secrets",
            ToolKind::Iterator => "iterator",
            ToolKind::Container => "container",
            ToolKind::Script => "script",
            ToolKind::Snowflake => "snowflake",
            ToolKind::Transfer => "transfer",
            ToolKind::SnowflakeTransfer => "snowflake_transfer",
            ToolKind::Gcs => "gcs",
        };
        write!(f, "{}", s)
    }
}

/// Tool specification with tool.kind pattern.
/// All execution-specific fields live under tool.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolSpec {
    /// Tool type.
    pub kind: ToolKind,

    /// Authentication configuration.
    #[serde(default)]
    pub auth: Option<serde_json::Value>,

    /// Libraries/dependencies.
    #[serde(default)]
    pub libs: Option<serde_json::Value>,

    /// Default arguments.
    #[serde(default)]
    pub args: Option<serde_json::Value>,

    /// Python code (for python tool).
    #[serde(default)]
    pub code: Option<String>,

    /// URL (for http tool).
    #[serde(default)]
    pub url: Option<String>,

    /// HTTP method (for http tool).
    #[serde(default)]
    pub method: Option<String>,

    /// Query/SQL (for database tools).
    #[serde(default)]
    pub query: Option<String>,

    /// Connection string or credential reference.
    #[serde(default)]
    pub connection: Option<String>,

    /// Additional tool-specific configuration.
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Loop execution mode.
#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LoopMode {
    #[default]
    Sequential,
    Parallel,
    Async,
}

/// Step-level loop configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Loop {
    /// Jinja expression for collection to iterate over.
    #[serde(rename = "in")]
    pub in_expr: String,

    /// Variable name for each item.
    pub iterator: String,

    /// Execution mode.
    #[serde(default)]
    pub mode: LoopMode,
}

/// Target for next transition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NextTarget {
    /// Target step name.
    pub step: String,

    /// Arguments to pass to target step.
    #[serde(default)]
    pub args: Option<HashMap<String, serde_json::Value>>,
}

/// Conditional behavior rule.
/// Evaluated against event context with Jinja2.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaseEntry {
    /// Jinja2 condition expression.
    pub when: String,

    /// Actions to execute when condition is true.
    /// Can be a list of actions or a single action dict (backwards compatible).
    pub then: serde_json::Value,
}

/// Next step specification - can be string, list of strings, or list of targets.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum NextSpec {
    /// Single step name.
    Single(String),

    /// List of step names.
    List(Vec<String>),

    /// List of step targets with optional args.
    Targets(Vec<NextTarget>),
}

/// Workflow step with event-driven control flow.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Step {
    /// Step name (unique identifier).
    pub step: String,

    /// Step description.
    #[serde(default)]
    pub desc: Option<String>,

    /// Input arguments for this step (from previous steps or templates).
    #[serde(default)]
    pub args: Option<HashMap<String, serde_json::Value>>,

    /// Variables to extract from step result.
    #[serde(default)]
    pub vars: Option<HashMap<String, serde_json::Value>>,

    /// Loop configuration.
    #[serde(default)]
    pub r#loop: Option<Loop>,

    /// Tool configuration with tool.kind.
    pub tool: ToolSpec,

    /// Event-driven conditional rules.
    #[serde(default)]
    pub case: Option<Vec<CaseEntry>>,

    /// Structural default next step(s) - unconditional.
    #[serde(default)]
    pub next: Option<NextSpec>,
}

/// Reusable task definition in workbook.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkbookTask {
    /// Task name.
    pub name: String,

    /// Tool configuration.
    pub tool: ToolSpec,

    /// Optional sink configuration.
    #[serde(default)]
    pub sink: Option<serde_json::Value>,
}

/// Keychain entry for credential/token definitions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeychainDef {
    /// Keychain entry name.
    pub name: String,

    /// Credential reference.
    #[serde(default)]
    pub credential: Option<String>,

    /// Token type.
    #[serde(default)]
    pub token_type: Option<String>,

    /// Scope type.
    #[serde(default)]
    pub scope: Option<String>,

    /// Auto-renew flag.
    #[serde(default)]
    pub auto_renew: bool,

    /// Additional configuration.
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Playbook metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Metadata {
    /// Playbook name (required).
    pub name: String,

    /// Resource path.
    #[serde(default)]
    pub path: Option<String>,

    /// Description.
    #[serde(default)]
    pub description: Option<String>,

    /// Labels for filtering.
    #[serde(default)]
    pub labels: Option<HashMap<String, String>>,

    /// Additional metadata.
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Complete workflow definition (v2).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Playbook {
    /// API version (noetl.io/v2).
    #[serde(rename = "apiVersion")]
    pub api_version: String,

    /// Resource kind (Playbook).
    pub kind: String,

    /// Metadata (name, path, labels).
    pub metadata: Metadata,

    /// Global workflow variables.
    #[serde(default)]
    pub workload: Option<serde_json::Value>,

    /// Keychain definitions for credentials and tokens.
    #[serde(default)]
    pub keychain: Option<Vec<KeychainDef>>,

    /// Reusable tasks.
    #[serde(default)]
    pub workbook: Option<Vec<WorkbookTask>>,

    /// Workflow steps.
    pub workflow: Vec<Step>,
}

impl Playbook {
    /// Check if workflow has a start step.
    pub fn has_start_step(&self) -> bool {
        self.workflow.iter().any(|s| s.step == "start")
    }

    /// Get a step by name.
    pub fn get_step(&self, name: &str) -> Option<&Step> {
        self.workflow.iter().find(|s| s.step == name)
    }

    /// Get all step names.
    pub fn step_names(&self) -> Vec<&str> {
        self.workflow.iter().map(|s| s.step.as_str()).collect()
    }

    /// Get the resource path.
    pub fn path(&self) -> Option<&str> {
        self.metadata.path.as_deref()
    }

    /// Get the playbook name.
    pub fn name(&self) -> &str {
        &self.metadata.name
    }
}

// ============================================================================
// Tool Call and Command Models
// ============================================================================

/// Tool invocation details.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCall {
    /// Tool kind.
    pub kind: ToolKind,

    /// Tool-specific configuration.
    #[serde(default)]
    pub config: HashMap<String, serde_json::Value>,
}

impl ToolCall {
    /// Create from a ToolSpec.
    pub fn from_spec(spec: &ToolSpec) -> Self {
        let mut config = spec.extra.clone();

        if let Some(ref auth) = spec.auth {
            config.insert("auth".to_string(), auth.clone());
        }
        if let Some(ref libs) = spec.libs {
            config.insert("libs".to_string(), libs.clone());
        }
        if let Some(ref args) = spec.args {
            config.insert("args".to_string(), args.clone());
        }
        if let Some(ref code) = spec.code {
            config.insert("code".to_string(), serde_json::Value::String(code.clone()));
        }
        if let Some(ref url) = spec.url {
            config.insert("url".to_string(), serde_json::Value::String(url.clone()));
        }
        if let Some(ref method) = spec.method {
            config.insert(
                "method".to_string(),
                serde_json::Value::String(method.clone()),
            );
        }
        if let Some(ref query) = spec.query {
            config.insert(
                "query".to_string(),
                serde_json::Value::String(query.clone()),
            );
        }
        if let Some(ref connection) = spec.connection {
            config.insert(
                "connection".to_string(),
                serde_json::Value::String(connection.clone()),
            );
        }

        Self {
            kind: spec.kind.clone(),
            config,
        }
    }
}

/// Command to be executed by worker.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Command {
    /// Execution identifier.
    pub execution_id: String,

    /// Step name.
    pub step: String,

    /// Tool invocation details.
    pub tool: ToolCall,

    /// Step input arguments.
    #[serde(default)]
    pub args: Option<HashMap<String, serde_json::Value>>,

    /// Full render context for Jinja2 templates.
    #[serde(default)]
    pub render_context: HashMap<String, serde_json::Value>,

    /// Case blocks for worker-side conditional execution.
    #[serde(default)]
    pub case: Option<Vec<serde_json::Value>>,

    /// Attempt number for retries.
    #[serde(default = "default_attempt")]
    pub attempt: i32,

    /// Command priority (higher = more urgent).
    #[serde(default)]
    pub priority: i32,

    /// Retry backoff delay in seconds.
    #[serde(default)]
    pub backoff: Option<f64>,

    /// Maximum retry attempts.
    #[serde(default)]
    pub max_attempts: Option<i32>,

    /// Initial retry delay in seconds.
    #[serde(default)]
    pub retry_delay: Option<f64>,

    /// Retry backoff strategy.
    #[serde(default)]
    pub retry_backoff: Option<String>,

    /// Additional metadata.
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

fn default_attempt() -> i32 {
    1
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_simple_playbook() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test_playbook
  path: test/simple
workflow:
  - step: start
    tool:
      kind: python
      code: |
        return {"status": "ok"}
    next:
      - step: end
  - step: end
    tool:
      kind: python
      code: |
        return {"status": "done"}
"#;

        let playbook: Playbook = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(playbook.api_version, "noetl.io/v2");
        assert_eq!(playbook.kind, "Playbook");
        assert_eq!(playbook.name(), "test_playbook");
        assert!(playbook.has_start_step());
        assert_eq!(playbook.workflow.len(), 2);
    }

    #[test]
    fn test_parse_playbook_with_loop() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: loop_test
workload:
  items: [1, 2, 3]
workflow:
  - step: start
    loop:
      in: "{{ workload.items }}"
      iterator: item
      mode: sequential
    tool:
      kind: python
      code: |
        return {"item": input_data.get("item")}
    args:
      item: "{{ item }}"
"#;

        let playbook: Playbook = serde_yaml::from_str(yaml).unwrap();
        let step = playbook.get_step("start").unwrap();
        assert!(step.r#loop.is_some());
        let loop_config = step.r#loop.as_ref().unwrap();
        assert_eq!(loop_config.iterator, "item");
        assert_eq!(loop_config.mode, LoopMode::Sequential);
    }

    #[test]
    fn test_parse_playbook_with_case() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: case_test
workflow:
  - step: start
    tool:
      kind: python
      code: |
        return {"value": 10}
    case:
      - when: "{{ result.value > 5 }}"
        then:
          - next:
              step: high
      - when: "{{ result.value <= 5 }}"
        then:
          - next:
              step: low
  - step: high
    tool:
      kind: python
      code: |
        return {"path": "high"}
  - step: low
    tool:
      kind: python
      code: |
        return {"path": "low"}
"#;

        let playbook: Playbook = serde_yaml::from_str(yaml).unwrap();
        let step = playbook.get_step("start").unwrap();
        assert!(step.case.is_some());
        let cases = step.case.as_ref().unwrap();
        assert_eq!(cases.len(), 2);
        assert_eq!(cases[0].when, "{{ result.value > 5 }}");
    }

    #[test]
    fn test_tool_call_from_spec() {
        let spec = ToolSpec {
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
        };

        let call = ToolCall::from_spec(&spec);
        assert_eq!(call.kind, ToolKind::Python);
        assert!(call.config.contains_key("code"));
    }

    #[test]
    fn test_step_names() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
workflow:
  - step: start
    tool:
      kind: python
      code: ""
  - step: process
    tool:
      kind: python
      code: ""
  - step: end
    tool:
      kind: python
      code: ""
"#;

        let playbook: Playbook = serde_yaml::from_str(yaml).unwrap();
        let names = playbook.step_names();
        assert_eq!(names, vec!["start", "process", "end"]);
    }
}
