//! Case/when/then evaluation.

use anyhow::Result;
use noetl_tools::context::ExecutionContext;
use noetl_tools::template::TemplateEngine;
use serde::{Deserialize, Serialize};

/// Condition operator for case evaluation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
#[derive(Default)]
pub enum Operator {
    /// Equality check.
    #[default]
    Eq,
    /// Inequality check.
    Ne,
    /// Greater than.
    Gt,
    /// Less than.
    Lt,
    /// Greater than or equal.
    Gte,
    /// Less than or equal.
    Lte,
    /// String contains.
    Contains,
    /// Regex match.
    Matches,
    /// Value is truthy.
    Truthy,
    /// Value is falsy.
    Falsy,
    /// Value is in list.
    In,
    /// Value is not in list.
    NotIn,
}


/// Condition to evaluate.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Condition {
    /// Left-hand side value or variable reference.
    pub left: String,

    /// Operator.
    #[serde(default)]
    pub op: Operator,

    /// Right-hand side value.
    #[serde(default)]
    pub right: Option<serde_json::Value>,
}

/// Case specification with when/then.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Case {
    /// Condition(s) to evaluate.
    #[serde(rename = "when")]
    pub conditions: Vec<Condition>,

    /// Action to take if conditions match.
    pub then: CaseAction,
}

/// Action to take when a case matches.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CaseAction {
    /// Continue to next step.
    Continue,
    /// Exit step with status.
    Exit { status: String, data: Option<serde_json::Value> },
    /// Set a variable.
    SetVar { name: String, value: serde_json::Value },
    /// Jump to another step.
    Goto { step: String },
    /// Retry the current call.
    Retry { delay_ms: Option<u64> },
    /// Fail the command.
    Fail { message: String },
}

/// Result of case evaluation.
#[derive(Debug, Clone)]
pub struct CaseResult {
    /// The matched case index.
    pub case_index: usize,

    /// The action to take.
    pub action: CaseAction,
}

/// Evaluates case/when/then conditions.
pub struct CaseEvaluator {
    template_engine: TemplateEngine,
}

impl CaseEvaluator {
    /// Create a new case evaluator.
    pub fn new() -> Self {
        Self {
            template_engine: TemplateEngine::new(),
        }
    }

    /// Evaluate cases against the execution context and tool result.
    ///
    /// Returns the first matching case or None if no case matches.
    pub fn evaluate(
        &self,
        cases: &[Case],
        ctx: &ExecutionContext,
        result: Option<&serde_json::Value>,
    ) -> Result<Option<CaseResult>> {
        for (index, case) in cases.iter().enumerate() {
            if self.evaluate_conditions(&case.conditions, ctx, result)? {
                return Ok(Some(CaseResult {
                    case_index: index,
                    action: case.then.clone(),
                }));
            }
        }

        Ok(None)
    }

    /// Evaluate a set of conditions (AND logic).
    fn evaluate_conditions(
        &self,
        conditions: &[Condition],
        ctx: &ExecutionContext,
        result: Option<&serde_json::Value>,
    ) -> Result<bool> {
        for condition in conditions {
            if !self.evaluate_condition(condition, ctx, result)? {
                return Ok(false);
            }
        }

        Ok(true)
    }

    /// Evaluate a single condition.
    fn evaluate_condition(
        &self,
        condition: &Condition,
        ctx: &ExecutionContext,
        result: Option<&serde_json::Value>,
    ) -> Result<bool> {
        // Resolve left-hand side
        let left = self.resolve_value(&condition.left, ctx, result)?;

        // Resolve right-hand side if present
        let right = condition
            .right
            .as_ref()
            .map(|r| self.resolve_json_value(r, ctx, result))
            .transpose()?;

        // Evaluate based on operator
        match condition.op {
            Operator::Eq => Ok(left == right.unwrap_or(serde_json::Value::Null)),
            Operator::Ne => Ok(left != right.unwrap_or(serde_json::Value::Null)),
            Operator::Gt => self.compare_numeric(&left, &right, |a, b| a > b),
            Operator::Lt => self.compare_numeric(&left, &right, |a, b| a < b),
            Operator::Gte => self.compare_numeric(&left, &right, |a, b| a >= b),
            Operator::Lte => self.compare_numeric(&left, &right, |a, b| a <= b),
            Operator::Contains => {
                let left_str = left.as_str().unwrap_or("");
                let right_str = right.as_ref().and_then(|r| r.as_str()).unwrap_or("");
                Ok(left_str.contains(right_str))
            }
            Operator::Matches => {
                let left_str = left.as_str().unwrap_or("");
                let pattern = right.as_ref().and_then(|r| r.as_str()).unwrap_or("");
                let re = regex::Regex::new(pattern).map_err(|e| anyhow::anyhow!("Invalid regex: {}", e))?;
                Ok(re.is_match(left_str))
            }
            Operator::Truthy => Ok(is_truthy(&left)),
            Operator::Falsy => Ok(!is_truthy(&left)),
            Operator::In => {
                if let Some(serde_json::Value::Array(arr)) = &right {
                    Ok(arr.contains(&left))
                } else {
                    Ok(false)
                }
            }
            Operator::NotIn => {
                if let Some(serde_json::Value::Array(arr)) = &right {
                    Ok(!arr.contains(&left))
                } else {
                    Ok(true)
                }
            }
        }
    }

    /// Resolve a value reference to a JSON value.
    fn resolve_value(
        &self,
        value: &str,
        ctx: &ExecutionContext,
        result: Option<&serde_json::Value>,
    ) -> Result<serde_json::Value> {
        // Check for special references
        if let Some(path) = value.strip_prefix("result.") {
            if let Some(res) = result {
                return Ok(self.json_path(res, path).cloned().unwrap_or(serde_json::Value::Null));
            }
            return Ok(serde_json::Value::Null);
        }

        if value == "result" {
            return Ok(result.cloned().unwrap_or(serde_json::Value::Null));
        }

        // Check for variable reference
        if let Some(var) = ctx.get_variable(value) {
            return Ok(var.clone());
        }

        // Try template rendering
        if TemplateEngine::is_template(value) {
            let template_ctx = ctx.to_template_context();
            let rendered = self.template_engine.render(value, &template_ctx)?;
            // Try to parse as JSON, otherwise return as string
            return Ok(serde_json::from_str(&rendered).unwrap_or(serde_json::json!(rendered)));
        }

        // Return as literal string
        Ok(serde_json::json!(value))
    }

    /// Resolve a JSON value that might contain templates.
    fn resolve_json_value(
        &self,
        value: &serde_json::Value,
        ctx: &ExecutionContext,
        _result: Option<&serde_json::Value>,
    ) -> Result<serde_json::Value> {
        let template_ctx = ctx.to_template_context();
        self.template_engine.render_value(value, &template_ctx).map_err(|e| anyhow::anyhow!(e))
    }

    /// Navigate a JSON path.
    fn json_path<'a>(&self, value: &'a serde_json::Value, path: &str) -> Option<&'a serde_json::Value> {
        let mut current = value;

        for segment in path.split('.') {
            match current {
                serde_json::Value::Object(obj) => {
                    current = obj.get(segment)?;
                }
                serde_json::Value::Array(arr) => {
                    let idx: usize = segment.parse().ok()?;
                    current = arr.get(idx)?;
                }
                _ => return None,
            }
        }

        Some(current)
    }

    /// Compare two values numerically.
    fn compare_numeric<F>(
        &self,
        left: &serde_json::Value,
        right: &Option<serde_json::Value>,
        cmp: F,
    ) -> Result<bool>
    where
        F: Fn(f64, f64) -> bool,
    {
        let left_num = value_to_f64(left)?;
        let right_num = value_to_f64(right.as_ref().unwrap_or(&serde_json::Value::Null))?;
        Ok(cmp(left_num, right_num))
    }
}

impl Default for CaseEvaluator {
    fn default() -> Self {
        Self::new()
    }
}

/// Check if a JSON value is truthy.
fn is_truthy(value: &serde_json::Value) -> bool {
    match value {
        serde_json::Value::Null => false,
        serde_json::Value::Bool(b) => *b,
        serde_json::Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(false),
        serde_json::Value::String(s) => !s.is_empty(),
        serde_json::Value::Array(a) => !a.is_empty(),
        serde_json::Value::Object(o) => !o.is_empty(),
    }
}

/// Convert a JSON value to f64.
fn value_to_f64(value: &serde_json::Value) -> Result<f64> {
    match value {
        serde_json::Value::Number(n) => n.as_f64().ok_or_else(|| anyhow::anyhow!("Invalid number")),
        serde_json::Value::String(s) => s.parse().map_err(|_| anyhow::anyhow!("Cannot parse as number")),
        serde_json::Value::Bool(b) => Ok(if *b { 1.0 } else { 0.0 }),
        serde_json::Value::Null => Ok(0.0),
        _ => Err(anyhow::anyhow!("Cannot convert to number")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_truthy() {
        assert!(!is_truthy(&serde_json::Value::Null));
        assert!(!is_truthy(&serde_json::json!(false)));
        assert!(is_truthy(&serde_json::json!(true)));
        assert!(!is_truthy(&serde_json::json!(0)));
        assert!(is_truthy(&serde_json::json!(1)));
        assert!(!is_truthy(&serde_json::json!("")));
        assert!(is_truthy(&serde_json::json!("hello")));
        assert!(!is_truthy(&serde_json::json!([])));
        assert!(is_truthy(&serde_json::json!([1])));
    }

    #[test]
    fn test_case_evaluator_eq() {
        let evaluator = CaseEvaluator::new();
        let mut ctx = ExecutionContext::default();
        ctx.set_variable("status", serde_json::json!("success"));

        let cases = vec![Case {
            conditions: vec![Condition {
                left: "status".to_string(),
                op: Operator::Eq,
                right: Some(serde_json::json!("success")),
            }],
            then: CaseAction::Continue,
        }];

        let result = evaluator.evaluate(&cases, &ctx, None).unwrap();
        assert!(result.is_some());
        assert!(matches!(result.unwrap().action, CaseAction::Continue));
    }

    #[test]
    fn test_case_evaluator_gt() {
        let evaluator = CaseEvaluator::new();
        let mut ctx = ExecutionContext::default();
        ctx.set_variable("count", serde_json::json!(10));

        let cases = vec![Case {
            conditions: vec![Condition {
                left: "count".to_string(),
                op: Operator::Gt,
                right: Some(serde_json::json!(5)),
            }],
            then: CaseAction::Continue,
        }];

        let result = evaluator.evaluate(&cases, &ctx, None).unwrap();
        assert!(result.is_some());
    }

    #[test]
    fn test_case_evaluator_contains() {
        let evaluator = CaseEvaluator::new();
        let mut ctx = ExecutionContext::default();
        ctx.set_variable("message", serde_json::json!("hello world"));

        let cases = vec![Case {
            conditions: vec![Condition {
                left: "message".to_string(),
                op: Operator::Contains,
                right: Some(serde_json::json!("world")),
            }],
            then: CaseAction::Continue,
        }];

        let result = evaluator.evaluate(&cases, &ctx, None).unwrap();
        assert!(result.is_some());
    }

    #[test]
    fn test_case_evaluator_result_path() {
        let evaluator = CaseEvaluator::new();
        let ctx = ExecutionContext::default();
        let result = serde_json::json!({
            "status": "ok",
            "data": {"count": 42}
        });

        let cases = vec![Case {
            conditions: vec![Condition {
                left: "result.status".to_string(),
                op: Operator::Eq,
                right: Some(serde_json::json!("ok")),
            }],
            then: CaseAction::Continue,
        }];

        let eval_result = evaluator.evaluate(&cases, &ctx, Some(&result)).unwrap();
        assert!(eval_result.is_some());
    }

    #[test]
    fn test_case_action_serialization() {
        let action = CaseAction::Exit {
            status: "completed".to_string(),
            data: Some(serde_json::json!({"result": 42})),
        };

        let json = serde_json::to_string(&action).unwrap();
        assert!(json.contains("exit"));
        assert!(json.contains("completed"));
    }
}
