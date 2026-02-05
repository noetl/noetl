use anyhow::{Context, Result};
use duckdb::{params, Connection};
use rhai::{Engine, Scope, Dynamic, Map, Array};
use serde::{Deserialize, Serialize};
use serde_yaml;
use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::Command;
use std::sync::{Arc, Mutex};

/// Runtime capability set - defines what features a runtime supports
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeCapabilities {
    pub runtime: String,  // "local" or "distributed"
    pub version: String,  // "noetl-runtime/1"
    pub tools: Vec<String>,
    pub features: Vec<String>,
}

impl RuntimeCapabilities {
    /// Local runtime capabilities
    pub fn local() -> Self {
        Self {
            runtime: "local".to_string(),
            version: "noetl-runtime/1".to_string(),
            tools: vec![
                "shell".to_string(),
                "http".to_string(),
                "duckdb".to_string(),
                "rhai".to_string(),
                "playbook".to_string(),
                "auth".to_string(),
                "sink".to_string(),
            ],
            features: vec![
                "case_v1".to_string(),
                "case_v2".to_string(),  // Rhai conditions
                "loop_v1".to_string(),
                "vars_v1".to_string(),
                "jinja2".to_string(),
            ],
        }
    }
    
    /// Distributed runtime capabilities
    #[allow(dead_code)]
    pub fn distributed() -> Self {
        Self {
            runtime: "distributed".to_string(),
            version: "noetl-runtime/1".to_string(),
            tools: vec![
                "shell".to_string(),
                "http".to_string(),
                "postgres".to_string(),
                "duckdb".to_string(),
                "python".to_string(),
                "playbook".to_string(),
                "iterator".to_string(),
            ],
            features: vec![
                "case_v1".to_string(),
                "case_v2".to_string(),
                "loop_v1".to_string(),
                "loop_v2".to_string(),  // Pagination
                "vars_v1".to_string(),
                "vars_v2".to_string(),  // Cross-step results
                "sink_v1".to_string(),
                "jinja2".to_string(),
                "event_sourcing".to_string(),
            ],
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct Playbook {
    #[serde(rename = "apiVersion")]
    api_version: String,
    #[allow(dead_code)]
    kind: String,
    metadata: Metadata,
    /// Runtime requirements and capabilities (8-char root key)
    #[serde(default)]
    executor: Option<Executor>,
    workload: Option<HashMap<String, serde_yaml::Value>>,
    workflow: Vec<Step>,
}

/// Executor specification - runtime requirements and capabilities
#[derive(Debug, Deserialize, Default)]
pub struct Executor {
    /// Runtime profile: local, distributed, or auto
    #[serde(default = "default_profile")]
    pub profile: String,
    /// Semantic contract version: noetl-runtime/1
    #[serde(default = "default_version")]
    pub version: String,
    /// Required capabilities
    #[serde(default)]
    pub requires: Option<ExecutorRequires>,
    /// Executor spec for entry/final step configuration
    #[serde(default)]
    pub spec: Option<ExecutorSpec>,
}

/// Executor spec for workflow entry and termination control
#[derive(Debug, Deserialize, Default, Clone)]
pub struct ExecutorSpec {
    /// Override entry step (default: workflow[0])
    #[serde(default)]
    pub entry_step: Option<String>,
    /// Optional finalization step run after quiescence
    #[serde(default)]
    pub final_step: Option<String>,
    /// Treat "no next match" as error (default: false = branch terminates)
    #[serde(default)]
    pub no_next_is_error: Option<bool>,
}

fn default_profile() -> String { "auto".to_string() }
fn default_version() -> String { "noetl-runtime/1".to_string() }

/// Executor requirements
#[derive(Debug, Deserialize, Default)]
pub struct ExecutorRequires {
    /// Required tool kinds
    #[serde(default)]
    pub tools: Vec<String>,
    /// Required features
    #[serde(default)]
    pub features: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct Metadata {
    name: String,
    #[allow(dead_code)]
    path: Option<String>,
}

#[derive(Debug, Deserialize)]
struct Step {
    step: String,
    desc: Option<String>,
    /// Step enablement guard - evaluated before step runs (canonical v2)
    #[serde(rename = "when")]
    when_guard: Option<String>,
    tool: Option<Tool>,
    next: Option<Vec<NextStep>>,
    #[serde(rename = "case")]
    case: Option<Vec<CaseCondition>>,
    #[serde(rename = "loop")]
    #[allow(dead_code)]
    loop_config: Option<LoopConfig>,
    vars: Option<HashMap<String, String>>,
    /// Step spec for routing mode
    #[serde(default)]
    spec: Option<StepSpec>,
}

/// Step specification for routing control
#[derive(Debug, Deserialize, Default, Clone)]
struct StepSpec {
    /// Routing mode: exclusive (default, first match) or inclusive (all matches)
    #[serde(default)]
    pub next_mode: Option<NextMode>,
}

/// Next routing mode
#[derive(Debug, Deserialize, Clone, Default)]
#[serde(rename_all = "lowercase")]
enum NextMode {
    #[default]
    Exclusive,
    Inclusive,
}

/// Then block can be either a list of actions or a single action dict.
#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum ThenBlock {
    /// Single action object (backwards compatible)
    Single(serde_yaml::Value),
    /// List of action objects
    List(Vec<NextStep>),
}

#[derive(Debug, Deserialize)]
struct CaseCondition {
    #[serde(flatten)]
    when: WhenCondition,
    then: ThenBlock,
    #[serde(rename = "else")]
    else_steps: Option<Vec<NextStep>>,
}

/// Condition that can be either a simple template string or Rhai code
#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum WhenCondition {
    /// Rhai expression for complex conditions
    Rhai {
        #[serde(alias = "when_rhai")]
        rhai: String,
    },
    /// Simple template string condition (Jinja2-style)
    Simple {
        when: String,
    },
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
enum Tool {
    Shell {
        #[serde(default)]
        cmds: CmdsList,
    },
    Http {
        #[serde(default = "default_method")]
        method: String,
        url: String,
        #[serde(default)]
        headers: HashMap<String, String>,
        #[serde(default)]
        params: HashMap<String, String>,
        body: Option<String>,
        #[serde(default)]
        auth: Option<AuthConfig>,
    },
    Playbook {
        path: String,
        #[serde(default)]
        args: HashMap<String, String>,
    },
    #[serde(rename = "duckdb")]
    DuckDb {
        #[serde(default = "default_duckdb_path")]
        db: String,
        query: Option<String>,
        #[serde(default)]
        params: Vec<String>,
    },
    Auth {
        provider: String,
        #[serde(default)]
        scopes: Vec<String>,
        #[serde(default)]
        project: Option<String>,
    },
    Sink {
        target: SinkTarget,
        #[serde(default)]
        format: SinkFormat,
    },
    Rhai {
        code: String,
        #[serde(default)]
        args: HashMap<String, String>,
    },
    #[serde(other)]
    Unsupported,
}

fn default_method() -> String {
    "GET".to_string()
}

fn default_duckdb_path() -> String {
    ".noetl/state.duckdb".to_string()
}

#[derive(Debug, Deserialize, Clone)]
struct AuthConfig {
    /// Auth provider type: adc (Application Default Credentials), token, basic
    #[serde(alias = "source")]
    provider: String,
    #[serde(default)]
    scopes: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
enum SinkTarget {
    File { path: String },
    #[serde(rename = "duckdb")]
    DuckDb { db: String, table: String },
    Gcs { bucket: String, path: String },
}

#[derive(Debug, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
enum SinkFormat {
    #[default]
    Json,
    Yaml,
    Csv,
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum CmdsList {
    Single(String),
    Multiple(Vec<String>),
}

impl Default for CmdsList {
    fn default() -> Self {
        CmdsList::Multiple(vec![])
    }
}

/// Next step definition - supports canonical v2 format
#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum NextStep {
    /// Canonical v2 format: { step: "name", when: "condition", args: {...} }
    Canonical {
        step: String,
        #[serde(rename = "when")]
        when_condition: Option<String>,
        #[serde(default)]
        args: Option<HashMap<String, serde_yaml::Value>>,
    },
    /// Legacy conditional: { when: "condition", then: [...] }
    Conditional { when: Option<String>, then: Vec<NextStep> },
    /// Legacy next action: { next: [...] }
    NextAction { next: Vec<NextStep> },
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct LoopConfig {
    #[serde(rename = "in")]
    in_collection: String,
    iterator: String,
    mode: Option<String>,
}

pub struct PlaybookRunner {
    playbook_path: PathBuf,
    variables: HashMap<String, String>,
    verbose: bool,
    target: Option<String>,
    merge: bool,
}

impl PlaybookRunner {
    pub fn new(playbook_path: PathBuf) -> Self {
        Self {
            playbook_path,
            variables: HashMap::new(),
            verbose: false,
            target: None,
            merge: false,
        }
    }

    pub fn with_variables(mut self, vars: HashMap<String, String>) -> Self {
        self.variables = vars;
        self
    }

    pub fn with_merge(mut self, merge: bool) -> Self {
        self.merge = merge;
        self
    }

    pub fn with_verbose(mut self, verbose: bool) -> Self {
        self.verbose = verbose;
        self
    }

    pub fn with_target(mut self, target: Option<String>) -> Self {
        self.target = target;
        self
    }
    
    /// Validate playbook requirements against local runtime capabilities
    fn validate_capabilities(&self, playbook: &Playbook) -> Result<()> {
        let local_caps = RuntimeCapabilities::local();
        
        // Check executor profile
        if let Some(executor) = &playbook.executor {
            // Check if profile is compatible
            match executor.profile.as_str() {
                "distributed" => {
                    anyhow::bail!(
                        "Playbook '{}' requires distributed runtime (executor.profile: distributed)\n\
                         Use: noetl exec {} --runtime distributed",
                        playbook.metadata.name,
                        self.playbook_path.display()
                    );
                }
                "local" | "auto" | "" => {
                    // Compatible with local runtime
                }
                other => {
                    eprintln!("Warning: Unknown executor profile '{}', proceeding with local runtime", other);
                }
            }
            
            // Check version compatibility
            if executor.version != local_caps.version && !executor.version.is_empty() {
                eprintln!(
                    "Warning: Playbook requires '{}', local runtime provides '{}'. \
                     Some features may not work as expected.",
                    executor.version, local_caps.version
                );
            }
            
            // Check required tools
            if let Some(requires) = &executor.requires {
                for tool in &requires.tools {
                    if !local_caps.tools.contains(tool) {
                        anyhow::bail!(
                            "Playbook '{}' requires tool '{}' which is not supported by local runtime.\n\
                             Supported tools: {:?}\n\
                             Consider using: noetl exec {} --runtime distributed",
                            playbook.metadata.name,
                            tool,
                            local_caps.tools,
                            self.playbook_path.display()
                        );
                    }
                }
                
                // Check required features
                for feature in &requires.features {
                    if !local_caps.features.contains(feature) {
                        anyhow::bail!(
                            "Playbook '{}' requires feature '{}' which is not supported by local runtime.\n\
                             Supported features: {:?}\n\
                             Consider using: noetl exec {} --runtime distributed",
                            playbook.metadata.name,
                            feature,
                            local_caps.features,
                            self.playbook_path.display()
                        );
                    }
                }
            }
        }
        
        Ok(())
    }

    pub fn run(&self) -> Result<()> {
        // Load and parse playbook
        let content = fs::read_to_string(&self.playbook_path).context("Failed to read playbook file")?;

        let playbook: Playbook = serde_yaml::from_str(&content).context("Failed to parse playbook YAML")?;

        // Validate playbook against local runtime capabilities
        self.validate_capabilities(&playbook)?;

        println!("📋 Running playbook: {}", playbook.metadata.name);
        println!("   API Version: {}", playbook.api_version);
        
        if let Some(executor) = &playbook.executor {
            if self.verbose {
                println!("   Executor Profile: {}", executor.profile);
                println!("   Executor Version: {}", executor.version);
            }
        }

        // Initialize execution context with workload variables
        let mut context = ExecutionContext::new();
        if let Some(workload) = &playbook.workload {
            for (key, value) in workload {
                // Convert YAML value to plain string (not YAML formatted)
                let value_str = match value {
                    serde_yaml::Value::String(s) => s.clone(),
                    serde_yaml::Value::Number(n) => n.to_string(),
                    serde_yaml::Value::Bool(b) => b.to_string(),
                    other => serde_yaml::to_string(other)?.trim().to_string(),
                };
                context.set_variable(format!("workload.{}", key), value_str);
            }
        }

        // Add user-provided variables
        // By default (merge=false), user variables override workload variables (shallow merge)
        // With merge=true, we would do deep merge (but for now, we only support shallow)
        for (key, value) in &self.variables {
            // If key doesn't have workload prefix, add it for consistency with API
            let var_key = if key.starts_with("workload.") {
                key.clone()
            } else {
                // Set both with and without workload prefix for compatibility
                context.set_variable(key.clone(), value.clone());
                format!("workload.{}", key)
            };
            context.set_variable(var_key, value.clone());
        }

        // Determine starting step using canonical rules:
        // 1. Command-line target overrides everything
        // 2. executor.spec.entry_step if configured
        // 3. Default: workflow[0].step (first step in workflow array)
        let starting_step = if let Some(target) = &self.target {
            target.clone()
        } else if let Some(executor) = &playbook.executor {
            if let Some(spec) = &executor.spec {
                if let Some(entry) = &spec.entry_step {
                    entry.clone()
                } else {
                    // Default to first workflow step
                    playbook.workflow.first()
                        .map(|s| s.step.clone())
                        .unwrap_or_else(|| "start".to_string())
                }
            } else {
                // Default to first workflow step
                playbook.workflow.first()
                    .map(|s| s.step.clone())
                    .unwrap_or_else(|| "start".to_string())
            }
        } else {
            // Default to first workflow step
            playbook.workflow.first()
                .map(|s| s.step.clone())
                .unwrap_or_else(|| "start".to_string())
        };

        if self.target.is_some() {
            println!("🎯 Target: {}", starting_step);
        }

        // Track final_step for post-quiescence execution
        let final_step = playbook.executor.as_ref()
            .and_then(|e| e.spec.as_ref())
            .and_then(|s| s.final_step.clone());

        // Execute workflow starting from the entry step
        self.execute_step(&playbook, &starting_step, &mut context)?;

        // Execute final_step if configured and not already executed
        if let Some(final_step_name) = &final_step {
            if final_step_name != &starting_step {
                if self.verbose {
                    println!("\n📍 Running final step: {}", final_step_name);
                }
                self.execute_step(&playbook, final_step_name, &mut context)?;
            }
        }

        if self.verbose {
            println!("✅ Playbook execution completed successfully");
        }

        Ok(())
    }

    fn execute_step(&self, playbook: &Playbook, step_name: &str, context: &mut ExecutionContext) -> Result<()> {
        // Find the step
        let step = playbook
            .workflow
            .iter()
            .find(|s| s.step == step_name)
            .context(format!("Step '{}' not found", step_name))?;

        // Terminal "end" step - no-op for backwards compatibility
        if step_name == "end" {
            return Ok(());
        }

        // Evaluate step.when enablement guard (canonical v2)
        if let Some(when_guard) = &step.when_guard {
            // Render template first, then evaluate
            let rendered_guard = self.render_template(when_guard, context)?;
            let is_enabled = self.evaluate_condition(&rendered_guard, context)?;

            if !is_enabled {
                if self.verbose {
                    println!("\n⏭️  Step '{}' skipped (when guard: {})", step_name, when_guard);
                }
                // Step is disabled - do not execute, branch terminates here
                return Ok(());
            }
        }

        println!("\n🔹 Step: {}", step_name);
        if let Some(desc) = &step.desc {
            println!("   Description: {}", desc);
        }

        // Execute the tool and capture result
        let step_result: Option<String> = if let Some(tool) = &step.tool {
            let result = self.execute_tool(tool, context)?;

            // Store step result for reference in templates
            if let Some(result_json) = &result {
                context.set_step_result(step_name.to_string(), result_json.clone());
            }
            result
        } else {
            None
        };

        // Handle vars extraction - make result available as "result" for JSON path access
        if let Some(vars) = &step.vars {
            // Parse step result as JSON for path access
            let result_json: Option<serde_json::Value> = step_result.as_ref()
                .and_then(|s| serde_json::from_str(s).ok());
            
            for (key, template) in vars {
                // Handle result.* JSON path expressions
                let value = if template.contains("result.") || template.contains("result[") {
                    self.render_template_with_result(template, context, result_json.as_ref())?
                } else {
                    self.render_template(template, context)?
                };
                context.set_variable(format!("vars.{}", key), value);
            }
        }

        // Handle case conditions (evaluate before next)
        let mut case_matched = false;
        if let Some(cases) = &step.case {
            if self.verbose {
                println!("   Evaluating {} case conditions...", cases.len());
            }
            for case in cases {
                let (condition_result, condition_display) = match &case.when {
                    WhenCondition::Rhai { rhai } => {
                        // Evaluate Rhai expression
                        let result = self.evaluate_rhai_condition(rhai, context)?;
                        (result, format!("rhai: {}...", &rhai.chars().take(40).collect::<String>()))
                    }
                    WhenCondition::Simple { when } => {
                        // Render template first, then evaluate condition
                        let rendered_condition = self.render_template(when, context)?;
                        let result = self.evaluate_condition(&rendered_condition, context)?;
                        (result, when.clone())
                    }
                };

                if self.verbose && !condition_result {
                    println!("   ✗ {}", condition_display);
                }

                if condition_result {
                    case_matched = true;
                    if self.verbose {
                        println!("   ✓ Condition matched: {}", condition_display);
                    }

                    // Execute then steps (potentially in parallel if multiple)
                    // Handle both list and single-object formats for then block
                    match &case.then {
                        ThenBlock::List(steps) => {
                            self.execute_next_steps(playbook, steps, context)?;
                        }
                        ThenBlock::Single(value) => {
                            // For single object format, try to extract next steps
                            // This handles the dict format: then: { next: ... }
                            if let Some(next_val) = value.get("next") {
                                if let Ok(steps) = serde_yaml::from_value::<Vec<NextStep>>(next_val.clone()) {
                                    self.execute_next_steps(playbook, &steps, context)?;
                                } else if let Ok(step) = serde_yaml::from_value::<NextStep>(next_val.clone()) {
                                    self.execute_next_steps(playbook, &[step], context)?;
                                }
                            }
                            // Handle pipe: blocks - pass to distributed executor
                            // For local CLI, we skip pipeline execution (requires distributed runtime)
                            if value.get("pipe").is_some() {
                                if self.verbose {
                                    println!("   ⚠ Pipeline blocks require distributed runtime, skipping");
                                }
                            }
                        }
                    }
                    break;
                } else if let Some(else_steps) = &case.else_steps {
                    if self.verbose {
                        println!("   ✗ Condition not matched, executing else branch");
                    }
                    self.execute_next_steps(playbook, else_steps, context)?;
                    break;
                }
            }
        }

        // Execute next steps only if no case matched or no case defined
        if !case_matched {
            if let Some(next_steps) = &step.next {
                // Get next_mode from step spec (default: exclusive)
                let next_mode = step.spec.as_ref()
                    .and_then(|s| s.next_mode.clone())
                    .unwrap_or(NextMode::Exclusive);

                self.execute_next_steps_with_mode(playbook, next_steps, context, &next_mode)?;
            }
            // No next section = branch termination (leaf step)
        }

        Ok(())
    }

    /// Execute next steps with canonical routing semantics
    /// next_mode: exclusive (first match) or inclusive (all matches)
    fn execute_next_steps(
        &self,
        playbook: &Playbook,
        next_steps: &[NextStep],
        context: &mut ExecutionContext,
    ) -> Result<()> {
        self.execute_next_steps_with_mode(playbook, next_steps, context, &NextMode::Exclusive)
    }

    /// Execute next steps with specified routing mode
    fn execute_next_steps_with_mode(
        &self,
        playbook: &Playbook,
        next_steps: &[NextStep],
        context: &mut ExecutionContext,
        next_mode: &NextMode,
    ) -> Result<()> {
        let mut matched_steps: Vec<String> = Vec::new();
        let mut matched_args: Vec<Option<HashMap<String, serde_yaml::Value>>> = Vec::new();

        // Evaluate conditions and collect matching steps
        for next in next_steps {
            match next {
                NextStep::Canonical { step, when_condition, args } => {
                    // Canonical v2 format: evaluate when condition if present
                    let matches = if let Some(condition) = when_condition {
                        let rendered = self.render_template(condition, context)?;
                        self.evaluate_condition(&rendered, context)?
                    } else {
                        // No when condition = always matches (default arc)
                        true
                    };

                    if matches {
                        if self.verbose {
                            if let Some(cond) = when_condition {
                                println!("   ✓ Route matched: {} ({})", step, cond);
                            } else {
                                println!("   ✓ Route: {} (default)", step);
                            }
                        }

                        matched_steps.push(step.clone());
                        matched_args.push(args.clone());

                        // In exclusive mode, stop at first match
                        if matches!(next_mode, NextMode::Exclusive) {
                            break;
                        }
                    } else if self.verbose {
                        if let Some(cond) = when_condition {
                            println!("   ✗ Route skipped: {} ({})", step, cond);
                        }
                    }
                }
                NextStep::Conditional { when, then } => {
                    // Legacy conditional format
                    if let Some(condition) = when {
                        let rendered = self.render_template(condition, context)?;
                        if self.evaluate_condition(&rendered, context)? {
                            self.execute_next_steps_with_mode(playbook, then, context, next_mode)?;
                            if matches!(next_mode, NextMode::Exclusive) {
                                return Ok(());
                            }
                        }
                    }
                }
                NextStep::NextAction { next } => {
                    // Legacy { next: [...] } format
                    self.execute_next_steps_with_mode(playbook, next, context, next_mode)?;
                    return Ok(());
                }
            }
        }

        // Branch termination: no matches = branch ends
        if matched_steps.is_empty() {
            if self.verbose && !next_steps.is_empty() {
                println!("   ⏹️  Branch terminated (no matching routes)");
            }
            return Ok(());
        }

        // Log fan-out in inclusive mode
        if matches!(next_mode, NextMode::Inclusive) && matched_steps.len() > 1 && self.verbose {
            println!("   ⚡ Fan-out to {} steps: {:?}", matched_steps.len(), matched_steps);
        }

        // Execute matched steps
        for (i, step_name) in matched_steps.iter().enumerate() {
            // Apply args to context if present
            if let Some(Some(args)) = matched_args.get(i) {
                for (key, value) in args {
                    let value_str = match value {
                        serde_yaml::Value::String(s) => s.clone(),
                        serde_yaml::Value::Number(n) => n.to_string(),
                        serde_yaml::Value::Bool(b) => b.to_string(),
                        other => serde_yaml::to_string(other)?.trim().to_string(),
                    };
                    context.set_variable(format!("args.{}", key), value_str);
                }
            }

            self.execute_step(playbook, step_name, context)?;
        }

        Ok(())
    }

    fn evaluate_condition(&self, condition: &str, context: &ExecutionContext) -> Result<bool> {
        // Simple condition evaluation
        // Supports: {{ var == "value" }}, {{ var != "value" }}, {{ var }} (truthy check)
        
        // Extract content from {{ ... }} if present
        let expression = if condition.trim().starts_with("{{") && condition.trim().ends_with("}}") {
            condition.trim()
                .strip_prefix("{{").unwrap()
                .strip_suffix("}}").unwrap()
                .trim()
        } else {
            condition.trim()
        };
        
        // Replace variables within the expression
        let mut rendered = expression.to_string();
        for (key, value) in &context.variables {
            // Replace variable references like workload.action with their values
            rendered = rendered.replace(key, value);
        }
        
        // Helper to strip quotes from a value
        fn strip_quotes(s: &str) -> String {
            let s = s.trim();
            if (s.starts_with('"') && s.ends_with('"')) || 
               (s.starts_with('\'') && s.ends_with('\'')) {
                s[1..s.len()-1].to_string()
            } else {
                s.to_string()
            }
        }

        // Check for comparison operators
        if rendered.contains("==") {
            let parts: Vec<&str> = rendered.split("==").map(|s| s.trim()).collect();
            if parts.len() == 2 {
                return Ok(strip_quotes(parts[0]) == strip_quotes(parts[1]));
            }
        }

        if rendered.contains("!=") {
            let parts: Vec<&str> = rendered.split("!=").map(|s| s.trim()).collect();
            if parts.len() == 2 {
                return Ok(strip_quotes(parts[0]) != strip_quotes(parts[1]));
            }
        }
        
        // Check for 'in' operator (e.g., "'value' in var" or "var in list")
        if rendered.contains(" in ") {
            let parts: Vec<&str> = rendered.split(" in ").map(|s| s.trim()).collect();
            if parts.len() == 2 {
                let needle = strip_quotes(parts[0]);
                let haystack = strip_quotes(parts[1]);
                return Ok(haystack.contains(&needle));
            }
        }

        // Truthy check - not empty, not "false", not "0"
        let value = strip_quotes(&rendered);
        Ok(!value.is_empty() && value != "false" && value != "0")
    }
    
    /// Evaluate a Rhai expression as a boolean condition
    /// The Rhai code should return a boolean (true/false)
    fn evaluate_rhai_condition(&self, code: &str, context: &ExecutionContext) -> Result<bool> {
        let mut engine = Engine::new();
        let mut scope = Scope::new();
        
        // Add workload variables to scope
        let mut workload_map = Map::new();
        for (key, value) in &context.variables {
            if key.starts_with("workload.") {
                let short_key = key.strip_prefix("workload.").unwrap_or(key);
                workload_map.insert(short_key.to_string().into(), Dynamic::from(value.clone()));
            }
        }
        scope.push("workload", workload_map);
        
        // Add vars to scope
        let mut vars_map = Map::new();
        for (key, value) in &context.variables {
            if key.starts_with("vars.") {
                let short_key = key.strip_prefix("vars.").unwrap_or(key);
                vars_map.insert(short_key.to_string().into(), Dynamic::from(value.clone()));
            }
        }
        scope.push("vars", vars_map);
        
        // Add step results to scope
        for (key, value) in &context.variables {
            // Add step results directly (e.g., check_existing.status)
            if !key.starts_with("workload.") && !key.starts_with("vars.") && key.contains('.') {
                let parts: Vec<&str> = key.splitn(2, '.').collect();
                if parts.len() == 2 {
                    let step_name = parts[0];
                    let field_name = parts[1];
                    
                    // Create or get the step map
                    if !scope.contains(step_name) {
                        scope.push(step_name.to_string(), Map::new());
                    }
                    
                    // Update the step map with this field
                    if let Some(step_map) = scope.get_mut(step_name) {
                        if let Some(map) = step_map.clone().try_cast::<Map>() {
                            let mut map = map;
                            map.insert(field_name.to_string().into(), Dynamic::from(value.clone()));
                            *step_map = Dynamic::from(map);
                        }
                    }
                }
            }
        }
        
        // Register comparison helpers
        engine.register_fn("eq", |a: &str, b: &str| -> bool { a == b });
        engine.register_fn("ne", |a: &str, b: &str| -> bool { a != b });
        engine.register_fn("contains", |haystack: &str, needle: &str| -> bool {
            haystack.contains(needle)
        });
        
        // Evaluate the condition
        let result = engine.eval_with_scope::<Dynamic>(&mut scope, code)
            .map_err(|e| anyhow::anyhow!("Rhai condition error: {}", e))?;
        
        // Convert result to boolean
        if result.is_bool() {
            Ok(result.as_bool().unwrap_or(false))
        } else if result.is_int() {
            Ok(result.as_int().unwrap_or(0) != 0)
        } else if result.is_string() {
            let s = result.into_string().unwrap_or_default();
            Ok(!s.is_empty() && s != "false" && s != "0")
        } else {
            // Treat non-unit values as truthy
            Ok(!result.is_unit())
        }
    }

    fn execute_tool(&self, tool: &Tool, context: &mut ExecutionContext) -> Result<Option<String>> {
        match tool {
            Tool::Shell { cmds } => {
                let commands = match cmds {
                    CmdsList::Single(cmd) => {
                        // Split multi-line string into individual commands
                        cmd.lines()
                            .map(|s| s.trim())
                            .filter(|s| !s.is_empty())
                            .map(|s| s.to_string())
                            .collect::<Vec<_>>()
                    }
                    CmdsList::Multiple(cmds) => cmds.clone(),
                };

                let mut last_output = String::new();
                for command in commands {
                    let rendered_command = self.render_template(&command, context)?;
                    last_output = self.execute_shell_command(&rendered_command)?;
                }
                Ok(Some(last_output))
            }
            Tool::Http {
                method,
                url,
                headers,
                params,
                body,
                auth,
            } => {
                let rendered_url = self.render_template(url, context)?;

                if self.verbose {
                    println!("   HTTP {} {}", method, rendered_url);
                }

                // Get auth token if auth config is provided
                let auth_token = if let Some(auth_config) = auth {
                    Some(self.get_auth_token(&auth_config.provider, &auth_config.scopes, context)?)
                } else {
                    None
                };

                let result = self.execute_http_request(
                    method,
                    &rendered_url,
                    Some(headers),
                    Some(params),
                    body.as_deref(),
                    auth_token.as_deref(),
                    context,
                )?;

                Ok(Some(result))
            }
            Tool::Playbook { path, args } => {
                let rendered_path = self.render_template(path, context)?;
                let playbook_path = self.resolve_playbook_path(&rendered_path)?;

                if self.verbose {
                    println!("   Executing sub-playbook: {}", playbook_path.display());
                }

                // Merge context variables with args - prefix args with workload.
                let mut sub_vars = context.variables.clone();
                for (key, template) in args {
                    let value = self.render_template(template, context)?;
                    sub_vars.insert(format!("workload.{}", key), value);
                }

                let sub_runner = PlaybookRunner::new(playbook_path)
                    .with_variables(sub_vars)
                    .with_verbose(self.verbose);
                sub_runner.run()?;

                Ok(None)
            }
            Tool::DuckDb { db, query, params } => {
                let rendered_db = self.render_template(db, context)?;
                let db_path = self.resolve_duckdb_path(&rendered_db)?;

                if self.verbose {
                    println!("   DuckDB: {}", db_path.display());
                }

                if let Some(query_str) = query {
                    let rendered_query = self.render_template(query_str, context)?;
                    let rendered_params: Vec<String> = params
                        .iter()
                        .map(|p| self.render_template(p, context))
                        .collect::<Result<Vec<_>>>()?;

                    let result = self.execute_duckdb_query(&db_path, &rendered_query, &rendered_params)?;
                    Ok(Some(result))
                } else {
                    Ok(None)
                }
            }
            Tool::Auth { provider, scopes, project } => {
                if self.verbose {
                    println!("   Auth: provider={}", provider);
                }

                // Set project in context if provided
                if let Some(proj) = project {
                    let rendered_project = self.render_template(proj, context)?;
                    context.set_variable("auth.project".to_string(), rendered_project);
                }

                let token = self.get_auth_token(provider, scopes, context)?;

                // Store token in context for subsequent HTTP calls
                context.set_variable("auth.token".to_string(), token.clone());
                context.set_variable("auth.provider".to_string(), provider.clone());

                Ok(Some(token))
            }
            Tool::Sink { target, format } => {
                // Get the last step result to sink
                let data = context
                    .step_results
                    .values()
                    .last()
                    .cloned()
                    .unwrap_or_default();

                let formatted_data = match format {
                    SinkFormat::Json => data.clone(),
                    SinkFormat::Yaml => {
                        // Convert JSON to YAML if possible
                        if let Ok(json_val) = serde_json::from_str::<serde_json::Value>(&data) {
                            serde_yaml::to_string(&json_val).unwrap_or(data.clone())
                        } else {
                            data.clone()
                        }
                    }
                    SinkFormat::Csv => {
                        // Basic JSON array to CSV conversion
                        self.json_to_csv(&data)?
                    }
                };

                match target {
                    SinkTarget::File { path } => {
                        let rendered_path = self.render_template(path, context)?;
                        let file_path = self.resolve_sink_path(&rendered_path)?;

                        if self.verbose {
                            println!("   Sink to file: {}", file_path.display());
                        }

                        // Create parent directories if needed
                        if let Some(parent) = file_path.parent() {
                            fs::create_dir_all(parent)?;
                        }
                        fs::write(&file_path, &formatted_data)?;
                        Ok(Some(format!("Written to {}", file_path.display())))
                    }
                    SinkTarget::DuckDb { db, table } => {
                        let rendered_db = self.render_template(db, context)?;
                        let rendered_table = self.render_template(table, context)?;
                        let db_path = self.resolve_duckdb_path(&rendered_db)?;

                        if self.verbose {
                            println!("   Sink to DuckDB: {} -> {}", db_path.display(), rendered_table);
                        }

                        self.sink_to_duckdb(&db_path, &rendered_table, &data)?;
                        Ok(Some(format!("Inserted into {}", rendered_table)))
                    }
                    SinkTarget::Gcs { bucket, path } => {
                        let rendered_bucket = self.render_template(bucket, context)?;
                        let rendered_path = self.render_template(path, context)?;
                        let gcs_uri = format!("gs://{}/{}", rendered_bucket, rendered_path);

                        if self.verbose {
                            println!("   Sink to GCS: {}", gcs_uri);
                        }

                        self.sink_to_gcs(&gcs_uri, &formatted_data)?;
                        Ok(Some(format!("Uploaded to {}", gcs_uri)))
                    }
                }
            }
            Tool::Rhai { code, args } => {
                // Render templates in args
                let mut rendered_args: HashMap<String, String> = HashMap::new();
                for (key, template) in args {
                    let value = self.render_template(template, context)?;
                    rendered_args.insert(key.clone(), value);
                }
                
                // Render templates in code
                let rendered_code = self.render_template(code, context)?;
                
                if self.verbose {
                    println!("   🦀 Executing Rhai script");
                }
                
                let result = self.execute_rhai_script(&rendered_code, &rendered_args, context)?;
                Ok(Some(result))
            }
            Tool::Unsupported => {
                println!("   Tool not supported in local execution mode");
                println!("   Supported tools: shell, http, playbook, duckdb, auth, sink");
                println!("   For other tools (postgres, python, iterator, etc.), use distributed execution");
                Ok(None)
            }
        }
    }

    fn execute_shell_command(&self, command: &str) -> Result<String> {
        if self.verbose {
            println!("   🔧 Executing: {}", command);
        }

        let mut binding = Command::new("bash");
        let cmd = binding
            .arg("-c")
            .arg(command)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());

        let cr = std::env::current_dir()?;

        let cmd = cmd.current_dir(cr);

        let mut child = cmd.spawn().context("Failed to spawn shell command")?;

        // Clone the stdout and stderr to read in separate threads
        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();

        let stdout_thread = std::thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                if let Ok(line) = line {
                    println!("{}", line);
                }
            }
        });

        let stderr_thread = std::thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines() {
                if let Ok(line) = line {
                    println!("{}", line);
                }
            }
        });

        // Wait for both threads to finish
        stdout_thread.join().unwrap();
        stderr_thread.join().unwrap();

        let status = child.wait()?;

        if !status.success() {
            anyhow::bail!("Command failed with exit code: {:?}", status.code());
        }

        Ok("".to_string())
    }

    /// Execute a Rhai script with access to HTTP, sleep, and utility functions
    fn execute_rhai_script(
        &self,
        code: &str,
        args: &HashMap<String, String>,
        context: &ExecutionContext,
    ) -> Result<String> {
        let mut engine = Engine::new();
        
        // Create shared output buffer for logging
        let output_buffer = Arc::new(Mutex::new(Vec::<String>::new()));
        let output_clone = output_buffer.clone();
        
        // Register log/print function
        engine.register_fn("log", move |msg: &str| {
            println!("{}", msg);
            if let Ok(mut buf) = output_clone.lock() {
                buf.push(msg.to_string());
            }
        });
        
        engine.register_fn("print", |msg: &str| {
            println!("{}", msg);
        });
        
        // Register timestamp function
        engine.register_fn("timestamp", || -> String {
            chrono::Local::now().format("%H:%M:%S").to_string()
        });
        
        // Register sleep function (seconds)
        engine.register_fn("sleep", |seconds: i64| {
            std::thread::sleep(std::time::Duration::from_secs(seconds as u64));
        });
        
        // Register sleep_ms function (milliseconds)
        engine.register_fn("sleep_ms", |ms: i64| {
            std::thread::sleep(std::time::Duration::from_millis(ms as u64));
        });
        
        // Register HTTP GET function
        engine.register_fn("http_get", |url: &str| -> Dynamic {
            Self::rhai_http_request("GET", url, "", None)
        });
        
        engine.register_fn("http_get_auth", |url: &str, token: &str| -> Dynamic {
            Self::rhai_http_request("GET", url, "", Some(token))
        });
        
        // Register HTTP POST function
        engine.register_fn("http_post", |url: &str, body: &str| -> Dynamic {
            Self::rhai_http_request("POST", url, body, None)
        });
        
        engine.register_fn("http_post_auth", |url: &str, body: &str, token: &str| -> Dynamic {
            Self::rhai_http_request("POST", url, body, Some(token))
        });
        
        // Register HTTP DELETE function
        engine.register_fn("http_delete", |url: &str| -> Dynamic {
            Self::rhai_http_request("DELETE", url, "", None)
        });
        
        engine.register_fn("http_delete_auth", |url: &str, token: &str| -> Dynamic {
            Self::rhai_http_request("DELETE", url, "", Some(token))
        });
        
        // Register JSON parse function
        engine.register_fn("parse_json", |json_str: &str| -> Dynamic {
            match serde_json::from_str::<serde_json::Value>(json_str) {
                Ok(value) => Self::json_to_rhai(&value),
                Err(_) => Dynamic::UNIT,
            }
        });
        
        // Register JSON stringify function
        engine.register_fn("to_json", |value: Dynamic| -> String {
            Self::rhai_to_json_string(&value)
        });
        
        // Register get_token function for GCP auth
        engine.register_fn("get_gcp_token", || -> String {
            let output = Command::new("gcloud")
                .args(["auth", "print-access-token"])
                .output();
            
            match output {
                Ok(out) if out.status.success() => {
                    String::from_utf8_lossy(&out.stdout).trim().to_string()
                }
                _ => String::new(),
            }
        });
        
        // Register string contains check
        engine.register_fn("contains", |haystack: &str, needle: &str| -> bool {
            haystack.contains(needle)
        });
        
        engine.register_fn("contains_any", |haystack: &str, needles: Array| -> bool {
            for needle in needles {
                if let Some(s) = needle.into_string().ok() {
                    if haystack.to_lowercase().contains(&s.to_lowercase()) {
                        return true;
                    }
                }
            }
            false
        });
        
        // Create scope with args and context variables
        let mut scope = Scope::new();
        
        // Add args to scope
        let mut args_map = Map::new();
        for (key, value) in args {
            args_map.insert(key.clone().into(), Dynamic::from(value.clone()));
        }
        scope.push("args", args_map);
        
        // Add workload variables to scope
        let mut workload_map = Map::new();
        for (key, value) in &context.variables {
            if key.starts_with("workload.") {
                let short_key = key.strip_prefix("workload.").unwrap_or(key);
                workload_map.insert(short_key.to_string().into(), Dynamic::from(value.clone()));
            }
        }
        scope.push("workload", workload_map);
        
        // Add vars to scope
        let mut vars_map = Map::new();
        for (key, value) in &context.variables {
            if key.starts_with("vars.") {
                let short_key = key.strip_prefix("vars.").unwrap_or(key);
                vars_map.insert(short_key.to_string().into(), Dynamic::from(value.clone()));
            }
        }
        scope.push("vars", vars_map);
        
        // Run the script
        let result = engine.eval_with_scope::<Dynamic>(&mut scope, code)
            .map_err(|e| anyhow::anyhow!("Rhai script error: {}", e))?;
        
        // Convert result to string
        let result_str = if result.is_unit() {
            "".to_string()
        } else if result.is_string() {
            result.into_string().unwrap_or_default()
        } else {
            Self::rhai_to_json_string(&result)
        };
        
        Ok(result_str)
    }
    
    /// Helper: Execute HTTP request and return Rhai-compatible result
    fn rhai_http_request(method: &str, url: &str, body: &str, token: Option<&str>) -> Dynamic {
        let mut curl_args = vec![
            "-s".to_string(),
            "-w".to_string(),
            "\n%{http_code}".to_string(),
            "-X".to_string(),
            method.to_string(),
        ];
        
        if let Some(t) = token {
            curl_args.push("-H".to_string());
            curl_args.push(format!("Authorization: Bearer {}", t));
        }
        
        if !body.is_empty() {
            curl_args.push("-H".to_string());
            curl_args.push("Content-Type: application/json".to_string());
            curl_args.push("-d".to_string());
            curl_args.push(body.to_string());
        }
        
        curl_args.push(url.to_string());
        
        let output = Command::new("curl")
            .args(&curl_args)
            .output();
        
        match output {
            Ok(out) => {
                let full_output = String::from_utf8_lossy(&out.stdout).to_string();
                
                // Parse output - body before last newline, status after
                let (body_part, status_str) = if let Some(pos) = full_output.rfind('\n') {
                    (full_output[..pos].to_string(), full_output[pos+1..].trim().to_string())
                } else {
                    (full_output.clone(), "0".to_string())
                };
                
                let status: i64 = status_str.parse().unwrap_or(0);
                
                // Create result map
                let mut result = Map::new();
                result.insert("status".into(), Dynamic::from(status));
                result.insert("status_str".into(), Dynamic::from(status_str));
                result.insert("body_raw".into(), Dynamic::from(body_part.clone()));
                
                // Try to parse body as JSON
                if let Ok(json_val) = serde_json::from_str::<serde_json::Value>(&body_part) {
                    result.insert("body".into(), Self::json_to_rhai(&json_val));
                    result.insert("ok".into(), Dynamic::from(status >= 200 && status < 300));
                } else {
                    result.insert("body".into(), Dynamic::from(body_part));
                    result.insert("ok".into(), Dynamic::from(status >= 200 && status < 300));
                }
                
                Dynamic::from(result)
            }
            Err(e) => {
                let mut result = Map::new();
                result.insert("status".into(), Dynamic::from(0_i64));
                result.insert("ok".into(), Dynamic::from(false));
                result.insert("error".into(), Dynamic::from(e.to_string()));
                Dynamic::from(result)
            }
        }
    }
    
    /// Convert serde_json::Value to Rhai Dynamic
    fn json_to_rhai(value: &serde_json::Value) -> Dynamic {
        match value {
            serde_json::Value::Null => Dynamic::UNIT,
            serde_json::Value::Bool(b) => Dynamic::from(*b),
            serde_json::Value::Number(n) => {
                if let Some(i) = n.as_i64() {
                    Dynamic::from(i)
                } else if let Some(f) = n.as_f64() {
                    Dynamic::from(f)
                } else {
                    Dynamic::from(n.to_string())
                }
            }
            serde_json::Value::String(s) => Dynamic::from(s.clone()),
            serde_json::Value::Array(arr) => {
                let rhai_arr: Array = arr.iter().map(Self::json_to_rhai).collect();
                Dynamic::from(rhai_arr)
            }
            serde_json::Value::Object(obj) => {
                let mut map = Map::new();
                for (k, v) in obj {
                    map.insert(k.clone().into(), Self::json_to_rhai(v));
                }
                Dynamic::from(map)
            }
        }
    }
    
    /// Convert Rhai Dynamic to JSON string
    fn rhai_to_json_string(value: &Dynamic) -> String {
        if value.is_unit() {
            "null".to_string()
        } else if value.is_bool() {
            value.as_bool().map(|b| b.to_string()).unwrap_or_default()
        } else if value.is_int() {
            value.as_int().map(|i| i.to_string()).unwrap_or_default()
        } else if value.is_float() {
            value.as_float().map(|f| f.to_string()).unwrap_or_default()
        } else if value.is_string() {
            format!("\"{}\"", value.clone().into_string().unwrap_or_default())
        } else if value.is_array() {
            let arr = value.clone().into_array().unwrap_or_default();
            let items: Vec<String> = arr.iter().map(Self::rhai_to_json_string).collect();
            format!("[{}]", items.join(","))
        } else if value.is_map() {
            let map = value.clone().cast::<Map>();
            let items: Vec<String> = map.iter()
                .map(|(k, v)| format!("\"{}\":{}", k, Self::rhai_to_json_string(v)))
                .collect();
            format!("{{{}}}", items.join(","))
        } else {
            format!("\"{}\"", value)
        }
    }

    fn execute_http_request(
        &self,
        method: &str,
        url: &str,
        headers: Option<&HashMap<String, String>>,
        params: Option<&HashMap<String, String>>,
        body: Option<&str>,
        auth_token: Option<&str>,
        context: &ExecutionContext,
    ) -> Result<String> {
        // Build curl command with status code output
        let mut curl_args = vec![
            "-s".to_string(),     // Silent mode
            "-w".to_string(),     // Write format
            "\n%{http_code}".to_string(),  // Append HTTP status code
        ];

        // Add method
        curl_args.push("-X".to_string());
        curl_args.push(method.to_string());

        // Add Authorization header if token provided
        if let Some(token) = auth_token {
            curl_args.push("-H".to_string());
            curl_args.push(format!("Authorization: Bearer {}", token));
        }

        // Add headers
        if let Some(hdrs) = headers {
            for (key, value) in hdrs {
                let rendered_value = self.render_template(value, context)?;
                curl_args.push("-H".to_string());
                curl_args.push(format!("{}: {}", key, rendered_value));
            }
        }

        // Add body
        if let Some(body_str) = body {
            let rendered_body = self.render_template(body_str, context)?;
            curl_args.push("-d".to_string());
            curl_args.push(rendered_body);
        }

        // Build URL with params
        let mut final_url = url.to_string();
        if let Some(prms) = params {
            let mut query_parts = vec![];
            for (key, value) in prms {
                let rendered_value = self.render_template(value, context)?;
                query_parts.push(format!("{}={}", key, rendered_value));
            }
            if !query_parts.is_empty() {
                final_url = format!("{}?{}", url, query_parts.join("&"));
            }
        }

        curl_args.push(final_url);

        if self.verbose {
            // Redact bearer tokens in output for security
            let redacted_args: Vec<String> = curl_args.iter().map(|arg| {
                if arg.starts_with("Authorization: Bearer ") {
                    "Authorization: Bearer [REDACTED]".to_string()
                } else {
                    arg.clone()
                }
            }).collect();
            println!("   curl {}", redacted_args.join(" "));
        }

        let output = Command::new("curl")
            .args(&curl_args)
            .output()
            .context("Failed to execute HTTP request (curl not available?)")?;

        if !output.status.success() {
            anyhow::bail!("HTTP request failed with exit code: {:?}", output.status.code());
        }

        let full_output = String::from_utf8_lossy(&output.stdout).to_string();
        
        // Parse the output - body is everything before the last newline, status code is after
        let (body_part, status_code) = if let Some(pos) = full_output.rfind('\n') {
            let body = full_output[..pos].to_string();
            let status = full_output[pos+1..].trim().to_string();
            (body, status)
        } else {
            (full_output.clone(), "0".to_string())
        };

        // Wrap response with status for playbook access
        let response = serde_json::json!({
            "status": status_code.parse::<i32>().unwrap_or(0),
            "body": serde_json::from_str::<serde_json::Value>(&body_part).unwrap_or(serde_json::Value::String(body_part.clone()))
        }).to_string();

        if self.verbose {
            println!(
                "   Response: {}",
                if response.len() > 200 {
                    format!("{}... ({} bytes)", &response[..200], response.len())
                } else {
                    response.clone()
                }
            );
        }

        Ok(response)
    }

    /// Get authentication token from the specified provider
    fn get_auth_token(&self, provider: &str, scopes: &[String], _context: &ExecutionContext) -> Result<String> {
        match provider {
            "gcp" | "google" | "adc" => {
                // Use gcloud to get access token
                let mut args = vec!["auth", "print-access-token"];

                // Add scopes if specified
                let scopes_str = if !scopes.is_empty() {
                    scopes.join(",")
                } else {
                    String::new()
                };

                if !scopes_str.is_empty() {
                    args.push("--scopes");
                    // Need to keep scopes_str alive
                }

                let output = Command::new("gcloud")
                    .args(&args)
                    .output()
                    .context("Failed to get GCP access token (gcloud CLI not available?)")?;

                if !output.status.success() {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    anyhow::bail!("Failed to get GCP access token: {}", stderr);
                }

                let token = String::from_utf8_lossy(&output.stdout).trim().to_string();
                Ok(token)
            }
            _ => anyhow::bail!("Unsupported auth provider: {}. Supported: gcp, google, adc", provider),
        }
    }

    /// Execute a DuckDB query and return results as JSON
    fn execute_duckdb_query(&self, db_path: &PathBuf, query: &str, _params: &[String]) -> Result<String> {
        // Ensure parent directory exists
        if let Some(parent) = db_path.parent() {
            fs::create_dir_all(parent)?;
        }

        let conn = Connection::open(db_path).context("Failed to open DuckDB database")?;

        if self.verbose {
            println!("   Query: {}", query);
        }

        // Check if it's a SELECT query or a modification query
        let query_upper = query.trim().to_uppercase();
        if query_upper.starts_with("SELECT") || query_upper.starts_with("WITH") {
            let mut stmt = conn.prepare(query).context("Failed to prepare query")?;
            let column_count = stmt.column_count();
            let column_names: Vec<String> = (0..column_count)
                .map(|i| stmt.column_name(i).map_or("?".to_string(), |v| v.to_string()))
                .collect();

            let rows = stmt.query_map(params![], |row| {
                let mut row_map = serde_json::Map::new();
                for (i, col_name) in column_names.iter().enumerate() {
                    let value: duckdb::types::Value = row.get(i)?;
                    let json_value = match value {
                        duckdb::types::Value::Null => serde_json::Value::Null,
                        duckdb::types::Value::Boolean(b) => serde_json::Value::Bool(b),
                        duckdb::types::Value::TinyInt(n) => serde_json::Value::Number(n.into()),
                        duckdb::types::Value::SmallInt(n) => serde_json::Value::Number(n.into()),
                        duckdb::types::Value::Int(n) => serde_json::Value::Number(n.into()),
                        duckdb::types::Value::BigInt(n) => serde_json::Value::Number(n.into()),
                        duckdb::types::Value::Float(f) => {
                            serde_json::Number::from_f64(f as f64)
                                .map(serde_json::Value::Number)
                                .unwrap_or(serde_json::Value::Null)
                        }
                        duckdb::types::Value::Double(f) => {
                            serde_json::Number::from_f64(f)
                                .map(serde_json::Value::Number)
                                .unwrap_or(serde_json::Value::Null)
                        }
                        duckdb::types::Value::Text(s) => serde_json::Value::String(s),
                        _ => serde_json::Value::String(format!("{:?}", value)),
                    };
                    row_map.insert(col_name.clone(), json_value);
                }
                Ok(serde_json::Value::Object(row_map))
            })?;

            let results: Vec<serde_json::Value> = rows.filter_map(|r| r.ok()).collect();
            let json = serde_json::to_string_pretty(&results)?;
            Ok(json)
        } else {
            // Execute non-SELECT query (CREATE, INSERT, UPDATE, DELETE)
            conn.execute(query, params![]).context("Failed to execute query")?;
            Ok(r#"{"status": "ok"}"#.to_string())
        }
    }

    /// Resolve DuckDB path relative to playbook or as absolute
    fn resolve_duckdb_path(&self, db_path: &str) -> Result<PathBuf> {
        if db_path.starts_with('/') || db_path.starts_with('~') {
            // Absolute path
            let expanded = shellexpand::tilde(db_path);
            Ok(PathBuf::from(expanded.as_ref()))
        } else {
            // Relative to playbook directory
            let base_dir = self
                .playbook_path
                .parent()
                .context("Failed to get playbook directory")?;
            Ok(base_dir.join(db_path))
        }
    }

    /// Resolve sink file path relative to playbook or as absolute
    fn resolve_sink_path(&self, file_path: &str) -> Result<PathBuf> {
        if file_path.starts_with('/') || file_path.starts_with('~') {
            let expanded = shellexpand::tilde(file_path);
            Ok(PathBuf::from(expanded.as_ref()))
        } else {
            let base_dir = self
                .playbook_path
                .parent()
                .context("Failed to get playbook directory")?;
            Ok(base_dir.join(file_path))
        }
    }

    /// Convert JSON array to CSV format
    fn json_to_csv(&self, json_str: &str) -> Result<String> {
        let value: serde_json::Value = serde_json::from_str(json_str)
            .unwrap_or(serde_json::Value::String(json_str.to_string()));

        match value {
            serde_json::Value::Array(arr) if !arr.is_empty() => {
                // Get headers from first object
                let headers: Vec<String> = if let Some(serde_json::Value::Object(obj)) = arr.first() {
                    obj.keys().cloned().collect()
                } else {
                    return Ok(json_str.to_string());
                };

                let mut csv = headers.join(",") + "\n";

                for item in &arr {
                    if let serde_json::Value::Object(obj) = item {
                        let row: Vec<String> = headers
                            .iter()
                            .map(|h| {
                                obj.get(h)
                                    .map(|v| match v {
                                        serde_json::Value::String(s) => {
                                            if s.contains(',') || s.contains('"') {
                                                format!("\"{}\"", s.replace('"', "\"\""))
                                            } else {
                                                s.clone()
                                            }
                                        }
                                        _ => v.to_string(),
                                    })
                                    .unwrap_or_default()
                            })
                            .collect();
                        csv.push_str(&row.join(","));
                        csv.push('\n');
                    }
                }
                Ok(csv)
            }
            _ => Ok(json_str.to_string()),
        }
    }

    /// Sink data to DuckDB table
    fn sink_to_duckdb(&self, db_path: &PathBuf, table: &str, json_data: &str) -> Result<()> {
        // Ensure parent directory exists
        if let Some(parent) = db_path.parent() {
            fs::create_dir_all(parent)?;
        }

        let conn = Connection::open(db_path).context("Failed to open DuckDB database")?;

        // Parse JSON data
        let value: serde_json::Value = serde_json::from_str(json_data)?;

        // Use DuckDB's JSON extension to insert data
        let json_escaped = json_data.replace('\'', "''");
        let insert_query = format!(
            "INSERT INTO {} SELECT * FROM read_json_auto('{}', format='array')",
            table, json_escaped
        );

        // If that fails, try a simpler approach for single objects
        match conn.execute(&insert_query, params![]) {
            Ok(_) => Ok(()),
            Err(_) => {
                // Try inserting as a single JSON object
                if let serde_json::Value::Object(obj) = &value {
                    let columns: Vec<&String> = obj.keys().collect();
                    let values: Vec<String> = obj
                        .values()
                        .map(|v| match v {
                            serde_json::Value::String(s) => format!("'{}'", s.replace('\'', "''")),
                            serde_json::Value::Null => "NULL".to_string(),
                            _ => v.to_string(),
                        })
                        .collect();

                    let query = format!(
                        "INSERT INTO {} ({}) VALUES ({})",
                        table,
                        columns.iter().map(|c| c.as_str()).collect::<Vec<_>>().join(", "),
                        values.join(", ")
                    );
                    conn.execute(&query, params![])?;
                }
                Ok(())
            }
        }
    }

    /// Sink data to GCS using gsutil
    fn sink_to_gcs(&self, gcs_uri: &str, data: &str) -> Result<()> {
        // Write to temp file first
        let temp_file = tempfile::NamedTempFile::new()?;
        fs::write(temp_file.path(), data)?;

        // Use gsutil to copy
        let output = Command::new("gsutil")
            .args(["cp", temp_file.path().to_str().unwrap(), gcs_uri])
            .output()
            .context("Failed to upload to GCS (gsutil not available?)")?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            anyhow::bail!("Failed to upload to GCS: {}", stderr);
        }

        Ok(())
    }

    fn render_template(&self, template: &str, context: &ExecutionContext) -> Result<String> {
        // Basic template rendering - replace {{ workload.var }}, {{ vars.var }}, {{ step_name.result }}
        let mut result = template.to_string();

        // First, handle templates with filters (e.g., {{ workload.var | lower }})
        let filter_regex = regex::Regex::new(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\|\s*([a-zA-Z_]+)\s*\}\}").unwrap();
        result = filter_regex.replace_all(&result, |caps: &regex::Captures| {
            let var_name = &caps[1];
            let filter_name = &caps[2];
            
            // Try to find the variable value
            let value = context.variables.get(var_name)
                .or_else(|| context.variables.get(&format!("workload.{}", var_name)))
                .map(|s| s.as_str())
                .unwrap_or("");
            
            // Apply the filter
            match filter_name {
                "lower" => value.to_lowercase(),
                "upper" => value.to_uppercase(),
                "trim" => value.trim().to_string(),
                "default" => if value.is_empty() { "".to_string() } else { value.to_string() },
                _ => value.to_string(),
            }
        }).to_string();

        // Handle workload.* variables
        for (key, value) in &context.variables {
            if key.starts_with("workload.") {
                let placeholder = format!("{{{{ {} }}}}", key);
                result = result.replace(&placeholder, value);
            }
        }

        // Handle vars.* variables
        for (key, value) in &context.variables {
            if key.starts_with("vars.") {
                let placeholder = format!("{{{{ {} }}}}", key);
                result = result.replace(&placeholder, value);
            }
        }

        // Handle step_name.result variables
        for (step_name, value) in &context.step_results {
            let placeholder = format!("{{{{ {}.result }}}}", step_name);
            result = result.replace(&placeholder, value);
        }

        // Also support direct {{ variable }} lookups
        for (key, value) in &context.variables {
            let placeholder = format!("{{{{ {} }}}}", key);
            result = result.replace(&placeholder, value);
        }

        Ok(result.trim().to_string())
    }

    /// Render template with access to JSON result via result.path notation
    fn render_template_with_result(&self, template: &str, context: &ExecutionContext, result_json: Option<&serde_json::Value>) -> Result<String> {
        let mut output = template.to_string();
        
        // Handle result.path expressions like {{ result.status }}, {{ result.body.name }}
        let result_regex = regex::Regex::new(r"\{\{\s*result\.([a-zA-Z0-9_.\[\]]+)\s*(?:\|\s*([a-zA-Z_]+(?:\([^)]*\))?))?\s*\}\}").unwrap();
        
        output = result_regex.replace_all(&output, |caps: &regex::Captures| {
            let path = &caps[1];
            let filter = caps.get(2).map(|m| m.as_str());
            
            if let Some(json) = result_json {
                // Navigate the JSON path
                let value = self.get_json_path(json, path);
                let value_str = match &value {
                    serde_json::Value::String(s) => s.clone(),
                    serde_json::Value::Number(n) => n.to_string(),
                    serde_json::Value::Bool(b) => b.to_string(),
                    serde_json::Value::Null => "".to_string(),
                    other => other.to_string(),
                };
                
                // Apply filter if present
                if let Some(f) = filter {
                    if f == "default" || f.starts_with("default(") {
                        if value_str.is_empty() || value_str == "null" {
                            // Extract default value from default('value') or default("")
                            if let Some(start) = f.find('(') {
                                let inner = &f[start+1..f.len()-1];
                                inner.trim_matches(|c| c == '\'' || c == '"').to_string()
                            } else {
                                "".to_string()
                            }
                        } else {
                            value_str
                        }
                    } else {
                        value_str
                    }
                } else {
                    value_str
                }
            } else {
                "".to_string()
            }
        }).to_string();
        
        // Then apply normal template rendering for other variables
        self.render_template(&output, context)
    }
    
    /// Get a value from JSON using a path like "status", "body.name", "items[0].id"
    fn get_json_path(&self, json: &serde_json::Value, path: &str) -> serde_json::Value {
        let parts: Vec<&str> = path.split('.').collect();
        let mut current = json.clone();
        
        for part in parts {
            // Handle array index notation like items[0]
            if part.contains('[') {
                if let Some(bracket_pos) = part.find('[') {
                    let key = &part[..bracket_pos];
                    let idx_str = &part[bracket_pos+1..part.len()-1];
                    
                    if !key.is_empty() {
                        current = current.get(key).cloned().unwrap_or(serde_json::Value::Null);
                    }
                    
                    if let Ok(idx) = idx_str.parse::<usize>() {
                        current = current.get(idx).cloned().unwrap_or(serde_json::Value::Null);
                    }
                }
            } else {
                current = current.get(part).cloned().unwrap_or(serde_json::Value::Null);
            }
        }
        
        current
    }

    fn resolve_playbook_path(&self, relative_path: &str) -> Result<PathBuf> {
        let base_dir = self
            .playbook_path
            .parent()
            .context("Failed to get playbook directory")?;
        Ok(base_dir.join(relative_path))
    }
}

struct ExecutionContext {
    variables: HashMap<String, String>,
    step_results: HashMap<String, String>,
}

impl ExecutionContext {
    fn new() -> Self {
        Self {
            variables: HashMap::new(),
            step_results: HashMap::new(),
        }
    }

    fn set_variable(&mut self, key: String, value: String) {
        self.variables.insert(key, value);
    }

    fn set_step_result(&mut self, step_name: String, result: String) {
        self.step_results.insert(step_name.clone(), result.clone());
        // Also set as variable for easy access
        self.variables.insert(format!("{}.result", step_name), result);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_template_rendering() {
        let mut context = ExecutionContext::new();
        context.set_variable("workload.cluster".to_string(), "noetl".to_string());

        let runner = PlaybookRunner::new(PathBuf::from("test.yaml"));
        let result = runner
            .render_template(
                "kind load docker-image noetl:latest --name {{ workload.cluster }}",
                &context,
            )
            .unwrap();

        assert_eq!(result, "kind load docker-image noetl:latest --name noetl");
    }

    #[test]
    fn test_condition_evaluation_equality() {
        let context = ExecutionContext::new();
        let runner = PlaybookRunner::new(PathBuf::from("test.yaml"));

        // Test equality
        assert!(runner.evaluate_condition("'test' == 'test'", &context).unwrap());
        assert!(!runner.evaluate_condition("'test' == 'other'", &context).unwrap());
    }

    #[test]
    fn test_condition_evaluation_inequality() {
        let context = ExecutionContext::new();
        let runner = PlaybookRunner::new(PathBuf::from("test.yaml"));

        // Test inequality
        assert!(runner.evaluate_condition("'test' != 'other'", &context).unwrap());
        assert!(!runner.evaluate_condition("'test' != 'test'", &context).unwrap());
    }

    #[test]
    fn test_condition_evaluation_with_variables() {
        let mut context = ExecutionContext::new();
        context.set_variable("workload.action".to_string(), "build".to_string());

        let runner = PlaybookRunner::new(PathBuf::from("test.yaml"));

        // Test condition with variable substitution
        assert!(runner.evaluate_condition("{{ workload.action == 'build' }}", &context).unwrap());
        assert!(!runner.evaluate_condition("{{ workload.action == 'deploy' }}", &context).unwrap());
    }

    #[test]
    fn test_condition_evaluation_truthy() {
        let context = ExecutionContext::new();
        let runner = PlaybookRunner::new(PathBuf::from("test.yaml"));

        // Test truthy values
        assert!(runner.evaluate_condition("true", &context).unwrap());
        assert!(runner.evaluate_condition("1", &context).unwrap());
        assert!(runner.evaluate_condition("non-empty", &context).unwrap());

        // Test falsy values
        assert!(!runner.evaluate_condition("false", &context).unwrap());
        assert!(!runner.evaluate_condition("0", &context).unwrap());
        assert!(!runner.evaluate_condition("", &context).unwrap());
    }

    #[test]
    fn test_next_mode_default() {
        // NextMode should default to Exclusive
        let mode = NextMode::default();
        assert!(matches!(mode, NextMode::Exclusive));
    }

    #[test]
    fn test_executor_spec_parsing() {
        let yaml = r#"
            entry_step: "custom_start"
            final_step: "cleanup"
            no_next_is_error: true
        "#;

        let spec: ExecutorSpec = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(spec.entry_step, Some("custom_start".to_string()));
        assert_eq!(spec.final_step, Some("cleanup".to_string()));
        assert_eq!(spec.no_next_is_error, Some(true));
    }

    #[test]
    fn test_step_spec_parsing() {
        let yaml = r#"
            next_mode: inclusive
        "#;

        let spec: StepSpec = serde_yaml::from_str(yaml).unwrap();
        assert!(matches!(spec.next_mode, Some(NextMode::Inclusive)));
    }

    #[test]
    fn test_canonical_next_step_parsing() {
        let yaml = r#"
            step: process_data
            when: "{{ workload.enabled }}"
        "#;

        let next: NextStep = serde_yaml::from_str(yaml).unwrap();
        match next {
            NextStep::Canonical { step, when_condition, .. } => {
                assert_eq!(step, "process_data");
                assert_eq!(when_condition, Some("{{ workload.enabled }}".to_string()));
            }
            _ => panic!("Expected Canonical variant"),
        }
    }

    #[test]
    fn test_canonical_next_step_with_args() {
        let yaml = r#"
            step: transform
            when: "{{ vars.ready }}"
            args:
              source: input.json
              target: output.json
        "#;

        let next: NextStep = serde_yaml::from_str(yaml).unwrap();
        match next {
            NextStep::Canonical { step, when_condition, args } => {
                assert_eq!(step, "transform");
                assert_eq!(when_condition, Some("{{ vars.ready }}".to_string()));
                assert!(args.is_some());
                let args = args.unwrap();
                assert!(args.contains_key("source"));
                assert!(args.contains_key("target"));
            }
            _ => panic!("Expected Canonical variant"),
        }
    }

    #[test]
    fn test_step_with_when_guard_parsing() {
        let yaml = r#"
            step: conditional_step
            when: "{{ workload.enabled == 'true' }}"
            desc: A step that only runs when enabled
            tool:
              kind: shell
              cmds:
                - echo "running"
        "#;

        let step: Step = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(step.step, "conditional_step");
        assert_eq!(step.when_guard, Some("{{ workload.enabled == 'true' }}".to_string()));
        assert!(step.desc.is_some());
    }

    #[test]
    fn test_playbook_entry_step_resolution() {
        let yaml = r#"
            apiVersion: noetl.io/v2
            kind: Playbook
            metadata:
              name: test_entry
            workflow:
              - step: first_step
                desc: First step in workflow
                tool:
                  kind: shell
                  cmds:
                    - echo "first"
              - step: second_step
                desc: Second step
                tool:
                  kind: shell
                  cmds:
                    - echo "second"
        "#;

        let playbook: Playbook = serde_yaml::from_str(yaml).unwrap();

        // Default entry should be workflow[0]
        let entry = playbook.workflow.first().map(|s| s.step.clone());
        assert_eq!(entry, Some("first_step".to_string()));
    }

    #[test]
    fn test_playbook_with_executor_entry_step() {
        let yaml = r#"
            apiVersion: noetl.io/v2
            kind: Playbook
            metadata:
              name: test_entry_override
            executor:
              profile: local
              spec:
                entry_step: custom_entry
            workflow:
              - step: first_step
                tool:
                  kind: shell
                  cmds:
                    - echo "first"
              - step: custom_entry
                tool:
                  kind: shell
                  cmds:
                    - echo "custom entry"
        "#;

        let playbook: Playbook = serde_yaml::from_str(yaml).unwrap();

        // Entry should be from executor.spec.entry_step
        let entry = playbook.executor.as_ref()
            .and_then(|e| e.spec.as_ref())
            .and_then(|s| s.entry_step.clone());
        assert_eq!(entry, Some("custom_entry".to_string()));
    }
}
