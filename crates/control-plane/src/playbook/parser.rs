//! Playbook YAML parser (Canonical Format).
//!
//! Parses YAML playbook definitions into Playbook structures.
//! Validates canonical format:
//! - step.when for transition enable guards
//! - next[].when for conditional routing
//! - loop.spec.mode for iteration configuration
//! - tool.eval for per-task flow control
//! - No case/when/then blocks (deprecated)

use crate::error::{AppError, AppResult};
use crate::playbook::types::{Playbook, ToolDefinition};

/// Parse a YAML string into a Playbook.
pub fn parse_playbook(yaml_content: &str) -> AppResult<Playbook> {
    // First check for deprecated case blocks before full parse
    validate_no_case_blocks(yaml_content)?;

    let playbook: Playbook =
        serde_yaml::from_str(yaml_content).map_err(|e| AppError::Parse(e.to_string()))?;

    // Validate the playbook
    validate_playbook(&playbook)?;

    Ok(playbook)
}

/// Check for deprecated case blocks in YAML content.
fn validate_no_case_blocks(yaml_content: &str) -> AppResult<()> {
    let value: serde_yaml::Value =
        serde_yaml::from_str(yaml_content).map_err(|e| AppError::Parse(e.to_string()))?;

    if let Some(workflow) = value.get("workflow").and_then(|w| w.as_sequence()) {
        for (idx, step) in workflow.iter().enumerate() {
            if step.get("case").is_some() {
                let fallback = format!("workflow[{}]", idx);
                let step_name = step
                    .get("step")
                    .and_then(|s| s.as_str())
                    .unwrap_or(&fallback);

                return Err(AppError::Validation(format!(
                    "Step '{}': 'case' blocks are not allowed in canonical format. \
                     Use 'step.when' for enable guards and 'next[].when' for conditional routing. \
                     For pipelines, use 'tool: [- label: {{kind: ...}}]' directly on the step.",
                    step_name
                )));
            }
        }
    }

    Ok(())
}

/// Validate a parsed playbook.
pub fn validate_playbook(playbook: &Playbook) -> AppResult<()> {
    // Check API version
    if playbook.api_version != "noetl.io/v2" {
        return Err(AppError::Validation(format!(
            "Unsupported API version: {}. Expected noetl.io/v2",
            playbook.api_version
        )));
    }

    // Check kind
    if playbook.kind != "Playbook" {
        return Err(AppError::Validation(format!(
            "Invalid kind: {}. Expected Playbook",
            playbook.kind
        )));
    }

    // Check for start step
    if !playbook.has_start_step() {
        return Err(AppError::Validation(
            "Workflow must have a step named 'start'".to_string(),
        ));
    }

    // Check for duplicate step names
    let mut seen_steps = std::collections::HashSet::new();
    for step in &playbook.workflow {
        if !seen_steps.insert(&step.step) {
            return Err(AppError::Validation(format!(
                "Duplicate step name: {}",
                step.step
            )));
        }
    }

    // Validate step transitions and canonical format
    let step_names: std::collections::HashSet<&str> =
        playbook.workflow.iter().map(|s| s.step.as_str()).collect();

    for step in &playbook.workflow {
        // Validate tool definition
        validate_tool_definition(&step.tool, &step.step)?;

        // Validate loop spec if present
        if let Some(ref loop_config) = step.r#loop {
            validate_loop_config(loop_config, &step.step)?;
        }

        // Validate step.when is a valid expression (basic check)
        if let Some(ref when) = step.when {
            if !is_valid_jinja_expression(when) {
                return Err(AppError::Validation(format!(
                    "Step '{}': invalid 'when' expression: {}",
                    step.step, when
                )));
            }
        }

        // Check next step references with when conditions
        if let Some(ref next) = step.next {
            validate_next_refs(next, &step_names, &step.step)?;
        }
    }

    Ok(())
}

/// Validate tool definition (single or pipeline).
fn validate_tool_definition(
    tool: &ToolDefinition,
    step_name: &str,
) -> AppResult<()> {
    match tool {
        ToolDefinition::Single(spec) => {
            // Validate eval conditions if present
            if let Some(ref eval) = spec.eval {
                validate_eval_conditions(eval, step_name)?;
            }
        }
        ToolDefinition::Pipeline(tasks) => {
            if tasks.is_empty() {
                return Err(AppError::Validation(format!(
                    "Step '{}': tool pipeline must have at least one task",
                    step_name
                )));
            }

            for (idx, task) in tasks.iter().enumerate() {
                // Each task should have exactly one key (the label)
                if task.len() != 1 {
                    return Err(AppError::Validation(format!(
                        "Step '{}': pipeline task[{}] must have exactly one labeled entry (got {})",
                        step_name, idx, task.len()
                    )));
                }

                // Validate eval conditions in each task
                for (label, spec) in task {
                    if let Some(ref eval) = spec.eval {
                        validate_eval_conditions_for_task(eval, step_name, label)?;
                    }
                }
            }
        }
    }
    Ok(())
}

/// Validate eval conditions list.
fn validate_eval_conditions(
    eval: &[crate::playbook::types::EvalEntry],
    step_name: &str,
) -> AppResult<()> {
    for (idx, entry) in eval.iter().enumerate() {
        match entry {
            crate::playbook::types::EvalEntry::Condition(cond) => {
                // Validate expr if present
                if let Some(ref expr) = cond.expr {
                    if !is_valid_jinja_expression(expr) {
                        return Err(AppError::Validation(format!(
                            "Step '{}': eval[{}] has invalid expression: {}",
                            step_name, idx, expr
                        )));
                    }
                }

                // Validate action
                let valid_actions = ["continue", "retry", "break", "jump", "fail"];
                if !valid_actions.contains(&cond.action.as_str()) {
                    return Err(AppError::Validation(format!(
                        "Step '{}': eval[{}] has invalid action '{}'. Valid: {:?}",
                        step_name, idx, cond.action, valid_actions
                    )));
                }
            }
            crate::playbook::types::EvalEntry::Else { r#else } => {
                // Validate action in else clause
                let valid_actions = ["continue", "retry", "break", "jump", "fail"];
                if !valid_actions.contains(&r#else.action.as_str()) {
                    return Err(AppError::Validation(format!(
                        "Step '{}': eval[{}] else has invalid action '{}'. Valid: {:?}",
                        step_name, idx, r#else.action, valid_actions
                    )));
                }
            }
        }
    }
    Ok(())
}

/// Validate eval conditions for a pipeline task.
fn validate_eval_conditions_for_task(
    eval: &[crate::playbook::types::EvalEntry],
    step_name: &str,
    task_label: &str,
) -> AppResult<()> {
    for (idx, entry) in eval.iter().enumerate() {
        match entry {
            crate::playbook::types::EvalEntry::Condition(cond) => {
                // Validate expr if present
                if let Some(ref expr) = cond.expr {
                    if !is_valid_jinja_expression(expr) {
                        return Err(AppError::Validation(format!(
                            "Step '{}': tool[].{}.eval[{}] has invalid expression: {}",
                            step_name, task_label, idx, expr
                        )));
                    }
                }

                // Validate action
                let valid_actions = ["continue", "retry", "break", "jump", "fail"];
                if !valid_actions.contains(&cond.action.as_str()) {
                    return Err(AppError::Validation(format!(
                        "Step '{}': tool[].{}.eval[{}] has invalid action '{}'. Valid: {:?}",
                        step_name, task_label, idx, cond.action, valid_actions
                    )));
                }
            }
            crate::playbook::types::EvalEntry::Else { r#else } => {
                // Validate action in else clause
                let valid_actions = ["continue", "retry", "break", "jump", "fail"];
                if !valid_actions.contains(&r#else.action.as_str()) {
                    return Err(AppError::Validation(format!(
                        "Step '{}': tool[].{}.eval[{}] else has invalid action '{}'. Valid: {:?}",
                        step_name, task_label, idx, r#else.action, valid_actions
                    )));
                }
            }
        }
    }
    Ok(())
}

/// Validate loop configuration.
fn validate_loop_config(
    loop_config: &crate::playbook::types::Loop,
    step_name: &str,
) -> AppResult<()> {
    // Validate in expression
    if !is_valid_jinja_expression(&loop_config.in_expr) {
        return Err(AppError::Validation(format!(
            "Step '{}': loop.in has invalid expression: {}",
            step_name, loop_config.in_expr
        )));
    }

    // Validate iterator name
    if loop_config.iterator.is_empty() {
        return Err(AppError::Validation(format!(
            "Step '{}': loop.iterator must not be empty",
            step_name
        )));
    }

    // Note: loop.spec.mode validation is done by serde during deserialization
    // (LoopMode enum only allows "sequential" or "parallel")

    Ok(())
}

/// Basic validation that a string looks like a Jinja expression.
fn is_valid_jinja_expression(expr: &str) -> bool {
    // Basic check: should contain {{ }} or be a simple expression
    // More sophisticated validation would require a Jinja parser
    !expr.is_empty() && (expr.contains("{{") || !expr.contains('{'))
}

/// Validate next step references (canonical format).
fn validate_next_refs(
    next: &crate::playbook::types::NextSpec,
    valid_steps: &std::collections::HashSet<&str>,
    current_step: &str,
) -> AppResult<()> {
    match next {
        crate::playbook::types::NextSpec::Single(name) => {
            if !valid_steps.contains(name.as_str()) {
                return Err(AppError::Validation(format!(
                    "Step '{}' references unknown step '{}' in next",
                    current_step, name
                )));
            }
        }
        crate::playbook::types::NextSpec::List(names) => {
            for name in names {
                if !valid_steps.contains(name.as_str()) {
                    return Err(AppError::Validation(format!(
                        "Step '{}' references unknown step '{}' in next",
                        current_step, name
                    )));
                }
            }
        }
        crate::playbook::types::NextSpec::Router(router) => {
            // Canonical v10 format: validate arcs
            for arc in &router.arcs {
                if !valid_steps.contains(arc.step.as_str()) {
                    return Err(AppError::Validation(format!(
                        "Step '{}' references unknown step '{}' in next.arcs",
                        current_step, arc.step
                    )));
                }

                // Validate when condition if present
                if let Some(ref when) = arc.when {
                    if !is_valid_jinja_expression(when) {
                        return Err(AppError::Validation(format!(
                            "Step '{}': next.arcs[].when has invalid expression: {}",
                            current_step, when
                        )));
                    }
                }
            }
        }
        crate::playbook::types::NextSpec::Targets(targets) => {
            // Legacy canonical format
            for target in targets {
                if !valid_steps.contains(target.step.as_str()) {
                    return Err(AppError::Validation(format!(
                        "Step '{}' references unknown step '{}' in next",
                        current_step, target.step
                    )));
                }

                // Validate when condition if present
                if let Some(ref when) = target.when {
                    if !is_valid_jinja_expression(when) {
                        return Err(AppError::Validation(format!(
                            "Step '{}': next[].when has invalid expression: {}",
                            current_step, when
                        )));
                    }
                }
            }
        }
    }
    Ok(())
}

/// Extract kind from YAML content without full parsing.
/// Useful for determining resource type before full parse.
pub fn extract_kind(yaml_content: &str) -> AppResult<String> {
    // Quick parse to get just the kind field
    let value: serde_yaml::Value =
        serde_yaml::from_str(yaml_content).map_err(|e| AppError::Parse(e.to_string()))?;

    value
        .get("kind")
        .and_then(|k| k.as_str())
        .map(|s| s.to_string())
        .ok_or_else(|| AppError::Validation("Missing 'kind' field".to_string()))
}

/// Extract metadata from YAML content.
pub fn extract_metadata(yaml_content: &str) -> AppResult<(String, Option<String>, Option<String>)> {
    let value: serde_yaml::Value =
        serde_yaml::from_str(yaml_content).map_err(|e| AppError::Parse(e.to_string()))?;

    let metadata = value
        .get("metadata")
        .ok_or_else(|| AppError::Validation("Missing 'metadata' field".to_string()))?;

    let name = metadata
        .get("name")
        .and_then(|n| n.as_str())
        .map(|s| s.to_string())
        .ok_or_else(|| AppError::Validation("Missing 'metadata.name' field".to_string()))?;

    let path = metadata
        .get("path")
        .and_then(|p| p.as_str())
        .map(|s| s.to_string());

    let description = metadata
        .get("description")
        .and_then(|d| d.as_str())
        .map(|s| s.to_string());

    Ok((name, path, description))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_valid_playbook() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
workflow:
  - step: start
    tool:
      kind: python
      code: return {}
"#;

        let result = parse_playbook(yaml);
        assert!(result.is_ok());
    }

    #[test]
    fn test_parse_invalid_api_version() {
        let yaml = r#"
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: test
workflow:
  - step: start
    tool:
      kind: python
      code: return {}
"#;

        let result = parse_playbook(yaml);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Unsupported API version"));
    }

    #[test]
    fn test_parse_missing_start_step() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
workflow:
  - step: process
    tool:
      kind: python
      code: return {}
"#;

        let result = parse_playbook(yaml);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("start"));
    }

    #[test]
    fn test_parse_duplicate_step_names() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
workflow:
  - step: start
    tool:
      kind: python
      code: return {}
  - step: start
    tool:
      kind: python
      code: return {}
"#;

        let result = parse_playbook(yaml);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Duplicate"));
    }

    #[test]
    fn test_parse_invalid_next_reference() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
workflow:
  - step: start
    tool:
      kind: python
      code: return {}
    next:
      - step: nonexistent
"#;

        let result = parse_playbook(yaml);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("unknown step"));
    }

    #[test]
    fn test_reject_case_blocks() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
workflow:
  - step: start
    tool:
      kind: python
      code: return {}
    case:
      - when: "{{ result.value > 5 }}"
        then:
          - next:
              step: high
"#;

        let result = parse_playbook(yaml);
        assert!(result.is_err());
        let err_msg = result.unwrap_err().to_string();
        assert!(err_msg.contains("case"));
        assert!(err_msg.contains("not allowed"));
    }

    #[test]
    fn test_parse_canonical_next_when() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
workflow:
  - step: start
    tool:
      kind: python
      code: |
        result = {"value": 10}
    next:
      - step: high
        when: "{{ start.value > 5 }}"
      - step: low
        when: "{{ start.value <= 5 }}"
  - step: high
    tool:
      kind: noop
  - step: low
    tool:
      kind: noop
"#;

        let result = parse_playbook(yaml);
        assert!(result.is_ok());
    }

    #[test]
    fn test_parse_step_when_guard() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
workflow:
  - step: start
    when: "{{ workload.enabled }}"
    tool:
      kind: python
      code: return {}
"#;

        let result = parse_playbook(yaml);
        assert!(result.is_ok());
    }

    #[test]
    fn test_parse_pipeline_format() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
workflow:
  - step: start
    tool:
      - fetch:
          kind: http
          url: "https://api.example.com"
          method: GET
      - transform:
          kind: python
          code: |
            result = {"processed": True}
"#;

        let result = parse_playbook(yaml);
        assert!(result.is_ok());
    }

    #[test]
    fn test_parse_loop_spec_mode() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
workflow:
  - step: start
    loop:
      in: "{{ workload.items }}"
      iterator: item
      spec:
        mode: parallel
        max_in_flight: 5
    tool:
      kind: python
      code: return {}
"#;

        let result = parse_playbook(yaml);
        assert!(result.is_ok());
    }

    #[test]
    fn test_extract_kind() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test
"#;

        let kind = extract_kind(yaml).unwrap();
        assert_eq!(kind, "Playbook");
    }

    #[test]
    fn test_extract_metadata() {
        let yaml = r#"
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: my_playbook
  path: test/path
  description: A test playbook
"#;

        let (name, path, desc) = extract_metadata(yaml).unwrap();
        assert_eq!(name, "my_playbook");
        assert_eq!(path, Some("test/path".to_string()));
        assert_eq!(desc, Some("A test playbook".to_string()));
    }
}
