use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json;
use serde_yaml;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

#[derive(Debug, Deserialize)]
pub struct Playbook {
    #[serde(rename = "apiVersion")]
    api_version: String,
    kind: String,
    metadata: Metadata,
    workload: Option<HashMap<String, serde_yaml::Value>>,
    workflow: Vec<Step>,
}

#[derive(Debug, Deserialize)]
struct Metadata {
    name: String,
    path: Option<String>,
}

#[derive(Debug, Deserialize)]
struct Step {
    step: String,
    desc: Option<String>,
    tool: Option<Tool>,
    next: Option<Vec<NextStep>>,
    #[serde(rename = "case")]
    case: Option<Vec<CaseCondition>>,
    #[serde(rename = "loop")]
    loop_config: Option<LoopConfig>,
    vars: Option<HashMap<String, String>>,
}

#[derive(Debug, Deserialize)]
struct CaseCondition {
    when: String,
    then: Vec<NextStep>,
    #[serde(rename = "else")]
    else_steps: Option<Vec<NextStep>>,
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
    },
    Playbook {
        path: String,
        #[serde(default)]
        args: HashMap<String, String>,
    },
    #[serde(other)]
    Unsupported,
}

fn default_method() -> String {
    "GET".to_string()
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

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum NextStep {
    Simple { step: String },
    Conditional {
        when: Option<String>,
        then: Vec<NextStep>,
    },
}

#[derive(Debug, Deserialize)]
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
}

impl PlaybookRunner {
    pub fn new(playbook_path: PathBuf) -> Self {
        Self {
            playbook_path,
            variables: HashMap::new(),
            verbose: false,
            target: None,
        }
    }

    pub fn with_variables(mut self, vars: HashMap<String, String>) -> Self {
        self.variables = vars;
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

    pub fn run(&self) -> Result<()> {
        // Load and parse playbook
        let content = fs::read_to_string(&self.playbook_path)
            .context("Failed to read playbook file")?;

        let playbook: Playbook = serde_yaml::from_str(&content)
            .context("Failed to parse playbook YAML")?;

        if self.verbose {
            println!("📋 Running playbook: {}", playbook.metadata.name);
            println!("   API Version: {}", playbook.api_version);
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
        for (key, value) in &self.variables {
            context.set_variable(key.clone(), value.clone());
        }

        // Determine starting step - use target if provided, otherwise "start"
        let starting_step = self.target.as_deref().unwrap_or("start");
        
        if self.verbose && self.target.is_some() {
            println!("🎯 Target: {}", starting_step);
        }

        // Execute workflow starting from the target step
        self.execute_step(&playbook, starting_step, &mut context)?;

        if self.verbose {
            println!("✅ Playbook execution completed successfully");
        }

        Ok(())
    }

    fn execute_step(
        &self,
        playbook: &Playbook,
        step_name: &str,
        context: &mut ExecutionContext,
    ) -> Result<()> {
        // Find the step
        let step = playbook
            .workflow
            .iter()
            .find(|s| s.step == step_name)
            .context(format!("Step '{}' not found", step_name))?;

        if step_name == "end" {
            return Ok(());
        }

        if self.verbose {
            println!("\n🔹 Step: {}", step_name);
            if let Some(desc) = &step.desc {
                println!("   Description: {}", desc);
            }
        }

        // Execute the tool and capture result
        if let Some(tool) = &step.tool {
            let result = self.execute_tool(tool, context)?;
            
            // Store step result for reference in templates
            if let Some(result_json) = result {
                context.set_step_result(step_name.to_string(), result_json);
            }
        }

        // Handle vars extraction
        if let Some(vars) = &step.vars {
            for (key, template) in vars {
                let value = self.render_template(template, context)?;
                context.set_variable(format!("vars.{}", key), value);
            }
        }

        // Handle case conditions (evaluate before next)
        let mut case_matched = false;
        if let Some(cases) = &step.case {
            for case in cases {
                let condition_result = self.evaluate_condition(&case.when, context)?;
                
                if condition_result {
                    case_matched = true;
                    if self.verbose {
                        println!("   ✓ Condition matched: {}", case.when);
                    }
                    
                    // Execute then steps (potentially in parallel if multiple)
                    self.execute_next_steps(playbook, &case.then, context)?;
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
                self.execute_next_steps(playbook, next_steps, context)?;
            }
        }

        Ok(())
    }

    fn execute_next_steps(
        &self,
        playbook: &Playbook,
        next_steps: &[NextStep],
        context: &mut ExecutionContext,
    ) -> Result<()> {
        // If multiple steps, log parallel execution (though we run sequentially for now)
        if next_steps.len() > 1 && self.verbose {
            println!("   ⚡ Executing {} steps in sequence", next_steps.len());
        }

        for next in next_steps {
            match next {
                NextStep::Simple { step } => {
                    self.execute_step(playbook, step, context)?;
                }
                NextStep::Conditional { when, then } => {
                    // Legacy conditional support
                    if let Some(condition) = when {
                        let condition_result = self.evaluate_condition(condition, context)?;
                        if condition_result {
                            self.execute_next_steps(playbook, then, context)?;
                        }
                    }
                }
            }
        }

        Ok(())
    }

    fn evaluate_condition(&self, condition: &str, context: &ExecutionContext) -> Result<bool> {
        // Simple condition evaluation
        // Supports: {{ var }} == "value", {{ var }} != "value", {{ var }} (truthy check)
        let rendered = self.render_template(condition, context)?;
        
        // Check for comparison operators
        if rendered.contains("==") {
            let parts: Vec<&str> = rendered.split("==").map(|s| s.trim()).collect();
            if parts.len() == 2 {
                return Ok(parts[0] == parts[1]);
            }
        }
        
        if rendered.contains("!=") {
            let parts: Vec<&str> = rendered.split("!=").map(|s| s.trim()).collect();
            if parts.len() == 2 {
                return Ok(parts[0] != parts[1]);
            }
        }
        
        // Truthy check - not empty, not "false", not "0"
        Ok(!rendered.is_empty() && rendered != "false" && rendered != "0")
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
            Tool::Http { method, url, headers, params, body } => {
                let rendered_url = self.render_template(url, context)?;
                
                if self.verbose {
                    println!("   🌐 HTTP {} {}", method, rendered_url);
                }
                
                let result = self.execute_http_request(
                    method,
                    &rendered_url,
                    Some(headers),
                    Some(params),
                    body.as_deref(),
                    context,
                )?;
                
                Ok(Some(result))
            }
            Tool::Playbook { path, args } => {
                let rendered_path = self.render_template(path, context)?;
                let playbook_path = self.resolve_playbook_path(&rendered_path)?;
                
                if self.verbose {
                    println!("   📎 Executing sub-playbook: {}", playbook_path.display());
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
            Tool::Unsupported => {
                println!("⚠️  Tool not supported in local execution mode");
                println!("   Supported tools: shell, http, playbook");
                println!("   For other tools (postgres, duckdb, python, iterator, etc.), use distributed execution");
                Ok(None)
            }
        }
    }

    fn execute_shell_command(&self, command: &str) -> Result<String> {
        if self.verbose {
            println!("   🔧 Executing: {}", command);
        }

        let output = Command::new("sh")
            .arg("-c")
            .arg(command)
            .output()
            .context("Failed to execute shell command")?;

        if !output.status.success() {
            anyhow::bail!("Command failed with exit code: {:?}", output.status.code());
        }

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        
        // Print output if verbose
        if self.verbose && !stdout.is_empty() {
            print!("{}", stdout);
        }

        Ok(stdout)
    }

    fn execute_http_request(
        &self,
        method: &str,
        url: &str,
        headers: Option<&HashMap<String, String>>,
        params: Option<&HashMap<String, String>>,
        body: Option<&str>,
        context: &ExecutionContext,
    ) -> Result<String> {
        // Build curl command
        let mut curl_args = vec!["-s".to_string()]; // Silent mode
        
        // Add method
        curl_args.push("-X".to_string());
        curl_args.push(method.to_string());
        
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
            println!("   🔧 curl {}", curl_args.join(" "));
        }
        
        let output = Command::new("curl")
            .args(&curl_args)
            .output()
            .context("Failed to execute HTTP request (curl not available?)")?;
        
        if !output.status.success() {
            anyhow::bail!("HTTP request failed with exit code: {:?}", output.status.code());
        }
        
        let response = String::from_utf8_lossy(&output.stdout).to_string();
        
        if self.verbose {
            println!("   📥 Response: {}", if response.len() > 200 {
                format!("{}... ({} bytes)", &response[..200], response.len())
            } else {
                response.clone()
            });
        }
        
        Ok(response)
    }

    fn render_template(&self, template: &str, context: &ExecutionContext) -> Result<String> {
        // Basic template rendering - replace {{ workload.var }}, {{ vars.var }}, {{ step_name.result }}
        let mut result = template.to_string();
        
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

    fn resolve_playbook_path(&self, relative_path: &str) -> Result<PathBuf> {
        let base_dir = self.playbook_path
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
        let result = runner.render_template(
            "kind load docker-image noetl:latest --name {{ workload.cluster }}",
            &context
        ).unwrap();
        
        assert_eq!(result, "kind load docker-image noetl:latest --name noetl");
    }
}
