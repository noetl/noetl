//! Playbook YAML parser.
//!
//! Parses YAML playbook definitions into Playbook structures.

use crate::error::{AppError, AppResult};
use crate::playbook::types::Playbook;

/// Parse a YAML string into a Playbook.
pub fn parse_playbook(yaml_content: &str) -> AppResult<Playbook> {
    let playbook: Playbook =
        serde_yaml::from_str(yaml_content).map_err(|e| AppError::Parse(e.to_string()))?;

    // Validate the playbook
    validate_playbook(&playbook)?;

    Ok(playbook)
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

    // Validate step transitions
    let step_names: std::collections::HashSet<&str> =
        playbook.workflow.iter().map(|s| s.step.as_str()).collect();

    for step in &playbook.workflow {
        // Check next step references
        if let Some(ref next) = step.next {
            validate_next_refs(next, &step_names, &step.step)?;
        }

        // Check case/then next references
        if let Some(ref cases) = step.case {
            for (i, case_entry) in cases.iter().enumerate() {
                validate_case_refs(
                    &case_entry.then,
                    &step_names,
                    &step.step,
                    &case_entry.when,
                    i,
                )?;
            }
        }
    }

    Ok(())
}

/// Validate next step references.
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
        crate::playbook::types::NextSpec::Targets(targets) => {
            for target in targets {
                if !valid_steps.contains(target.step.as_str()) {
                    return Err(AppError::Validation(format!(
                        "Step '{}' references unknown step '{}' in next",
                        current_step, target.step
                    )));
                }
            }
        }
    }
    Ok(())
}

/// Validate case/then references.
fn validate_case_refs(
    then_actions: &[serde_json::Value],
    valid_steps: &std::collections::HashSet<&str>,
    current_step: &str,
    when_condition: &str,
    case_index: usize,
) -> AppResult<()> {
    for action in then_actions {
        if let Some(next_obj) = action.get("next") {
            if let Some(step_name) = next_obj.get("step").and_then(|s| s.as_str()) {
                if !valid_steps.contains(step_name) {
                    return Err(AppError::Validation(format!(
                        "Step '{}' case[{}] (when: '{}') references unknown step '{}'",
                        current_step, case_index, when_condition, step_name
                    )));
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
