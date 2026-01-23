//! Condition evaluation for workflow transitions.
//!
//! Evaluates Jinja2-style conditions and case/when/then logic
//! for workflow transition decisions.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::playbook::types::{NextSpec, Step};
use crate::template::TemplateRenderer;

/// Result of evaluating a condition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvaluationResult {
    /// Whether the condition evaluated to true.
    pub matched: bool,
    /// The next step to transition to (if matched).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub next_step: Option<String>,
    /// Parameters to pass to the next step.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub with_params: Option<serde_json::Value>,
    /// Error message if evaluation failed.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl EvaluationResult {
    /// Create a matched result.
    pub fn matched(next_step: &str, with_params: Option<serde_json::Value>) -> Self {
        Self {
            matched: true,
            next_step: Some(next_step.to_string()),
            with_params,
            error: None,
        }
    }

    /// Create a non-matched result.
    pub fn not_matched() -> Self {
        Self {
            matched: false,
            next_step: None,
            with_params: None,
            error: None,
        }
    }

    /// Create an error result.
    pub fn error(message: &str) -> Self {
        Self {
            matched: false,
            next_step: None,
            with_params: None,
            error: Some(message.to_string()),
        }
    }
}

/// Condition evaluator for workflow transitions.
pub struct ConditionEvaluator {
    renderer: TemplateRenderer,
}

impl Default for ConditionEvaluator {
    fn default() -> Self {
        Self::new()
    }
}

impl ConditionEvaluator {
    /// Create a new condition evaluator.
    pub fn new() -> Self {
        Self {
            renderer: TemplateRenderer::new(),
        }
    }

    /// Evaluate a simple condition expression.
    pub fn evaluate_condition(
        &self,
        condition: &str,
        context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<bool> {
        self.renderer.evaluate_condition(condition, context)
    }

    /// Evaluate transition logic for a step.
    ///
    /// Returns the next step(s) to execute based on the step's `next` configuration.
    pub fn evaluate_next(
        &self,
        step: &Step,
        _context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<Vec<EvaluationResult>> {
        let mut results = Vec::new();

        match &step.next {
            Some(NextSpec::Single(next_step)) => {
                // Single next: always transition
                results.push(EvaluationResult::matched(next_step, None));
            }
            Some(NextSpec::List(next_steps)) => {
                // List of next steps: transition to all (parallel branches)
                for next_step in next_steps {
                    results.push(EvaluationResult::matched(next_step, None));
                }
            }
            Some(NextSpec::Targets(targets)) => {
                // Targets with optional args
                for target in targets {
                    let with_params = target
                        .args
                        .as_ref()
                        .map(|args| serde_json::to_value(args).unwrap_or(serde_json::Value::Null));
                    results.push(EvaluationResult::matched(&target.step, with_params));
                }
            }
            None => {
                // No next specified - workflow ends or implicit 'end'
            }
        }

        Ok(results)
    }

    /// Evaluate a step's case/when/then logic.
    ///
    /// The CaseEntry has `when` (condition) and `then` (actions) fields.
    /// Actions can contain `next` directives for transitions.
    pub fn evaluate_case_entries(
        &self,
        step: &Step,
        context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<Option<EvaluationResult>> {
        let case_entries = match &step.case {
            Some(entries) => entries,
            None => return Ok(None),
        };

        for entry in case_entries {
            // Evaluate the when condition
            if self.evaluate_condition(&entry.when, context)? {
                // Find the next step from the then actions
                for action in &entry.then {
                    if let Some(next_obj) = action.get("next") {
                        if let Some(next_step) = next_obj.get("step").and_then(|v| v.as_str()) {
                            let args = next_obj.get("args").cloned();
                            return Ok(Some(EvaluationResult::matched(next_step, args)));
                        }
                    }
                }
            }
        }

        Ok(None)
    }

    /// Evaluate a loop condition.
    ///
    /// Returns the collection to iterate over after rendering templates.
    pub fn evaluate_loop(
        &self,
        loop_expr: &str,
        context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<Vec<serde_json::Value>> {
        // Render the loop expression to get the collection
        let value = self.renderer.render_to_value(loop_expr, context)?;

        // Convert to array
        match value {
            serde_json::Value::Array(arr) => Ok(arr),
            serde_json::Value::Object(map) => {
                // Convert object to array of key-value pairs
                Ok(map
                    .into_iter()
                    .map(|(k, v)| serde_json::json!({"key": k, "value": v}))
                    .collect())
            }
            serde_json::Value::String(s) => {
                // Try to parse as JSON array
                if let Ok(arr) = serde_json::from_str::<Vec<serde_json::Value>>(&s) {
                    Ok(arr)
                } else {
                    // Split string by newlines or commas
                    Ok(s.split([',', '\n'])
                        .map(|item| serde_json::Value::String(item.trim().to_string()))
                        .filter(|v| !v.as_str().unwrap_or("").is_empty())
                        .collect())
                }
            }
            serde_json::Value::Number(n) => {
                // Create a range [0, n)
                let n = n.as_u64().unwrap_or(0) as usize;
                Ok((0..n).map(|i| serde_json::json!(i)).collect())
            }
            _ => Err(AppError::Validation(format!(
                "Loop expression did not evaluate to an iterable: {}",
                loop_expr
            ))),
        }
    }
}

/// Entry in a case/when block (for standalone use).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaseWhenEntry {
    /// Value to match against the case expression.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<String>,
    /// Condition to evaluate (alternative to value matching).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub condition: Option<String>,
    /// Whether this is the default case.
    #[serde(default)]
    pub is_default: bool,
    /// Step to transition to if matched.
    pub then_step: String,
    /// Parameters to pass to the next step.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub with_params: Option<serde_json::Value>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_evaluate_simple_condition() {
        let evaluator = ConditionEvaluator::new();
        let mut context = HashMap::new();
        context.insert("status".to_string(), serde_json::json!("success"));
        context.insert("count".to_string(), serde_json::json!(5));

        assert!(evaluator
            .evaluate_condition("status == 'success'", &context)
            .unwrap());
        assert!(!evaluator
            .evaluate_condition("status == 'failed'", &context)
            .unwrap());
        assert!(evaluator.evaluate_condition("count > 3", &context).unwrap());
        assert!(!evaluator
            .evaluate_condition("count > 10", &context)
            .unwrap());
    }

    #[test]
    fn test_evaluate_loop_array() {
        let evaluator = ConditionEvaluator::new();
        let mut context = HashMap::new();
        context.insert("items".to_string(), serde_json::json!(["a", "b", "c"]));

        let result = evaluator.evaluate_loop("{{ items }}", &context).unwrap();
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn test_evaluate_loop_number() {
        let evaluator = ConditionEvaluator::new();
        let mut context = HashMap::new();
        context.insert("count".to_string(), serde_json::json!(5));

        let result = evaluator.evaluate_loop("{{ count }}", &context).unwrap();
        assert_eq!(result.len(), 5);
    }

    #[test]
    fn test_evaluation_result_serialization() {
        let result =
            EvaluationResult::matched("next_step", Some(serde_json::json!({"key": "value"})));
        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("next_step"));
        assert!(json.contains("matched"));
    }

    #[test]
    fn test_evaluation_result_not_matched() {
        let result = EvaluationResult::not_matched();
        assert!(!result.matched);
        assert!(result.next_step.is_none());
    }

    #[test]
    fn test_evaluation_result_error() {
        let result = EvaluationResult::error("something went wrong");
        assert!(!result.matched);
        assert_eq!(result.error, Some("something went wrong".to_string()));
    }
}
