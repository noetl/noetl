//! Jinja2-style template rendering using minijinja.
//!
//! This module provides template rendering for NoETL playbooks,
//! supporting variables, filters, and control structures.

use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use minijinja::{value::ValueKind, Environment, Error, ErrorKind, Value};
use std::collections::HashMap;

use crate::error::{AppError, AppResult};

/// Template renderer with custom filters and context.
pub struct TemplateRenderer {
    env: Environment<'static>,
}

impl Default for TemplateRenderer {
    fn default() -> Self {
        Self::new()
    }
}

impl TemplateRenderer {
    /// Create a new template renderer with custom filters.
    pub fn new() -> Self {
        let mut env = Environment::new();

        // Add custom filters
        env.add_filter("b64encode", filter_b64encode);
        env.add_filter("b64decode", filter_b64decode);
        env.add_filter("tojson", filter_tojson);
        env.add_filter("fromjson", filter_fromjson);
        env.add_filter("default", filter_default);
        env.add_filter("int", filter_int);
        env.add_filter("float", filter_float);
        env.add_filter("string", filter_string);
        env.add_filter("lower", filter_lower);
        env.add_filter("upper", filter_upper);
        env.add_filter("trim", filter_trim);
        env.add_filter("split", filter_split);
        env.add_filter("join", filter_join);
        env.add_filter("first", filter_first);
        env.add_filter("last", filter_last);
        env.add_filter("length", filter_length);
        env.add_filter("keys", filter_keys);
        env.add_filter("values", filter_values);
        env.add_filter("items", filter_items);
        env.add_filter("get", filter_get);
        env.add_filter("safe", filter_safe);

        // Add custom tests
        env.add_test("defined", test_defined);
        env.add_test("undefined", test_undefined);
        env.add_test("none", test_none);
        env.add_test("string", test_string);
        env.add_test("number", test_number);
        env.add_test("sequence", test_sequence);
        env.add_test("mapping", test_mapping);

        Self { env }
    }

    /// Render a template string with the given context.
    pub fn render(
        &self,
        template: &str,
        context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<String> {
        // Quick check for non-template strings
        if !contains_template_syntax(template) {
            return Ok(template.to_string());
        }

        // Convert JSON context to minijinja Value
        let ctx = json_to_value(context);

        let tmpl = self
            .env
            .template_from_str(template)
            .map_err(|e| AppError::Template(format!("Template parse error: {}", e)))?;

        tmpl.render(ctx)
            .map_err(|e| AppError::Template(format!("Template render error: {}", e)))
    }

    /// Render a template and return the result as a JSON value.
    /// Attempts to parse the rendered string as JSON if it looks like JSON.
    pub fn render_to_value(
        &self,
        template: &str,
        context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<serde_json::Value> {
        let rendered = self.render(template, context)?;

        // Try to parse as JSON if it looks like JSON
        let trimmed = rendered.trim();
        if (trimmed.starts_with('{') && trimmed.ends_with('}'))
            || (trimmed.starts_with('[') && trimmed.ends_with(']'))
        {
            if let Ok(value) = serde_json::from_str(&rendered) {
                return Ok(value);
            }
        }

        // Try to parse as primitive values
        if let Ok(b) = trimmed.parse::<bool>() {
            return Ok(serde_json::Value::Bool(b));
        }
        if let Ok(i) = trimmed.parse::<i64>() {
            return Ok(serde_json::Value::Number(i.into()));
        }
        if let Ok(f) = trimmed.parse::<f64>() {
            if let Some(n) = serde_json::Number::from_f64(f) {
                return Ok(serde_json::Value::Number(n));
            }
        }
        if trimmed == "null" || trimmed == "None" || trimmed.is_empty() {
            return Ok(serde_json::Value::Null);
        }

        Ok(serde_json::Value::String(rendered))
    }

    /// Render a nested structure (dict or list) recursively.
    pub fn render_value(
        &self,
        value: &serde_json::Value,
        context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<serde_json::Value> {
        match value {
            serde_json::Value::String(s) => self.render_to_value(s, context),
            serde_json::Value::Object(map) => {
                let mut result = serde_json::Map::new();
                for (k, v) in map {
                    let rendered_key = self.render(k, context)?;
                    let rendered_value = self.render_value(v, context)?;
                    result.insert(rendered_key, rendered_value);
                }
                Ok(serde_json::Value::Object(result))
            }
            serde_json::Value::Array(arr) => {
                let result: Result<Vec<_>, _> =
                    arr.iter().map(|v| self.render_value(v, context)).collect();
                Ok(serde_json::Value::Array(result?))
            }
            _ => Ok(value.clone()),
        }
    }

    /// Evaluate a condition expression.
    pub fn evaluate_condition(
        &self,
        condition: &str,
        context: &HashMap<String, serde_json::Value>,
    ) -> AppResult<bool> {
        // Wrap condition in {{ }} if not already
        let template = if contains_template_syntax(condition) {
            condition.to_string()
        } else {
            format!("{{{{ {} }}}}", condition)
        };

        let rendered = self.render(&template, context)?;
        let trimmed = rendered.trim().to_lowercase();

        // Evaluate as boolean
        Ok(matches!(trimmed.as_str(), "true" | "1" | "yes"))
    }
}

/// Check if a string contains Jinja2 template syntax.
fn contains_template_syntax(s: &str) -> bool {
    (s.contains("{{") && s.contains("}}")) || (s.contains("{%") && s.contains("%}"))
}

/// Convert a JSON HashMap to a minijinja Value.
fn json_to_value(json: &HashMap<String, serde_json::Value>) -> Value {
    let converted: HashMap<String, Value> = json
        .iter()
        .map(|(k, v)| (k.clone(), json_value_to_minijinja(v)))
        .collect();
    Value::from_object(converted)
}

/// Convert a serde_json::Value to a minijinja Value.
fn json_value_to_minijinja(value: &serde_json::Value) -> Value {
    match value {
        serde_json::Value::Null => Value::UNDEFINED,
        serde_json::Value::Bool(b) => Value::from(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::from(i)
            } else if let Some(f) = n.as_f64() {
                Value::from(f)
            } else {
                Value::UNDEFINED
            }
        }
        serde_json::Value::String(s) => Value::from(s.as_str()),
        serde_json::Value::Array(arr) => {
            let items: Vec<Value> = arr.iter().map(json_value_to_minijinja).collect();
            Value::from(items)
        }
        serde_json::Value::Object(map) => {
            let items: HashMap<String, Value> = map
                .iter()
                .map(|(k, v)| (k.clone(), json_value_to_minijinja(v)))
                .collect();
            Value::from_object(items)
        }
    }
}

// ============================================================================
// Custom Filters
// ============================================================================

/// Base64 encode filter.
fn filter_b64encode(value: &Value) -> Result<String, Error> {
    let s = value.to_string();
    Ok(BASE64.encode(s.as_bytes()))
}

/// Base64 decode filter.
fn filter_b64decode(value: &Value) -> Result<String, Error> {
    let s = value.to_string();
    let decoded = BASE64.decode(s.as_bytes()).map_err(|e| {
        Error::new(
            ErrorKind::InvalidOperation,
            format!("b64decode error: {}", e),
        )
    })?;
    String::from_utf8(decoded)
        .map_err(|e| Error::new(ErrorKind::InvalidOperation, format!("utf8 error: {}", e)))
}

/// JSON encode filter.
fn filter_tojson(value: &Value) -> Result<String, Error> {
    // Convert Value back to JSON
    let json_val = minijinja_to_json(value);
    serde_json::to_string(&json_val)
        .map_err(|e| Error::new(ErrorKind::InvalidOperation, format!("tojson error: {}", e)))
}

/// JSON decode filter.
fn filter_fromjson(value: &Value) -> Result<Value, Error> {
    let s = value.to_string();
    let json_val: serde_json::Value = serde_json::from_str(&s).map_err(|e| {
        Error::new(
            ErrorKind::InvalidOperation,
            format!("fromjson error: {}", e),
        )
    })?;
    Ok(json_value_to_minijinja(&json_val))
}

/// Default value filter.
fn filter_default(value: &Value, default: Option<&Value>) -> Value {
    if value.is_undefined() || value.is_none() {
        default.cloned().unwrap_or(Value::from(""))
    } else {
        value.clone()
    }
}

/// Convert to integer filter.
fn filter_int(value: &Value) -> Result<i64, Error> {
    if let Some(i) = value.as_i64() {
        return Ok(i);
    }
    let s = value.to_string();
    // Try parsing as float first then convert to int
    if let Ok(f) = s.parse::<f64>() {
        return Ok(f as i64);
    }
    s.parse::<i64>()
        .map_err(|e| Error::new(ErrorKind::InvalidOperation, format!("int error: {}", e)))
}

/// Convert to float filter.
fn filter_float(value: &Value) -> Result<f64, Error> {
    if let Some(i) = value.as_i64() {
        return Ok(i as f64);
    }
    let s = value.to_string();
    s.parse::<f64>()
        .map_err(|e| Error::new(ErrorKind::InvalidOperation, format!("float error: {}", e)))
}

/// Convert to string filter.
fn filter_string(value: &Value) -> String {
    value.to_string()
}

/// Lowercase filter.
fn filter_lower(value: &Value) -> String {
    value.to_string().to_lowercase()
}

/// Uppercase filter.
fn filter_upper(value: &Value) -> String {
    value.to_string().to_uppercase()
}

/// Trim whitespace filter.
fn filter_trim(value: &Value) -> String {
    value.to_string().trim().to_string()
}

/// Split string filter.
fn filter_split(value: &Value, sep: Option<&Value>) -> Vec<String> {
    let s = value.to_string();
    let separator = sep
        .map(|v| v.to_string())
        .unwrap_or_else(|| " ".to_string());
    s.split(&separator).map(|s| s.to_string()).collect()
}

/// Join list filter.
fn filter_join(value: &Value, sep: Option<&Value>) -> Result<String, Error> {
    let separator = sep.map(|v| v.to_string()).unwrap_or_default();
    let iter = value
        .try_iter()
        .map_err(|_| Error::new(ErrorKind::InvalidOperation, "join requires a sequence"))?;
    let items: Vec<String> = iter.map(|v| v.to_string()).collect();
    Ok(items.join(&separator))
}

/// Get first element filter.
fn filter_first(value: &Value) -> Result<Value, Error> {
    let mut iter = value
        .try_iter()
        .map_err(|_| Error::new(ErrorKind::InvalidOperation, "first requires a sequence"))?;
    iter.next()
        .ok_or_else(|| Error::new(ErrorKind::InvalidOperation, "sequence is empty"))
}

/// Get last element filter.
fn filter_last(value: &Value) -> Result<Value, Error> {
    let iter = value
        .try_iter()
        .map_err(|_| Error::new(ErrorKind::InvalidOperation, "last requires a sequence"))?;
    iter.last()
        .ok_or_else(|| Error::new(ErrorKind::InvalidOperation, "sequence is empty"))
}

/// Length filter.
fn filter_length(value: &Value) -> Result<usize, Error> {
    if let Some(s) = value.as_str() {
        return Ok(s.len());
    }
    if let Some(len) = value.len() {
        return Ok(len);
    }
    Err(Error::new(
        ErrorKind::InvalidOperation,
        "length requires string, sequence, or mapping",
    ))
}

/// Get dict keys filter.
fn filter_keys(value: &Value) -> Result<Vec<String>, Error> {
    if value.kind() != ValueKind::Map {
        return Err(Error::new(
            ErrorKind::InvalidOperation,
            "keys requires a mapping",
        ));
    }
    let iter = value
        .try_iter()
        .map_err(|_| Error::new(ErrorKind::InvalidOperation, "cannot iterate keys"))?;
    Ok(iter.map(|v| v.to_string()).collect())
}

/// Get dict values filter.
fn filter_values(value: &Value) -> Result<Vec<Value>, Error> {
    if value.kind() != ValueKind::Map {
        return Err(Error::new(
            ErrorKind::InvalidOperation,
            "values requires a mapping",
        ));
    }
    let iter = value
        .try_iter()
        .map_err(|_| Error::new(ErrorKind::InvalidOperation, "cannot iterate values"))?;
    let mut result = Vec::new();
    for key in iter {
        if let Ok(val) = value.get_item(&key) {
            result.push(val);
        }
    }
    Ok(result)
}

/// Get dict items filter (as list of [key, value] pairs).
fn filter_items(value: &Value) -> Result<Vec<Vec<Value>>, Error> {
    if value.kind() != ValueKind::Map {
        return Err(Error::new(
            ErrorKind::InvalidOperation,
            "items requires a mapping",
        ));
    }
    let iter = value
        .try_iter()
        .map_err(|_| Error::new(ErrorKind::InvalidOperation, "cannot iterate items"))?;
    let mut result = Vec::new();
    for key in iter {
        if let Ok(val) = value.get_item(&key) {
            result.push(vec![key.clone(), val]);
        }
    }
    Ok(result)
}

/// Get value from dict by key.
fn filter_get(value: &Value, key: &Value) -> Value {
    value.get_item(key).unwrap_or(Value::UNDEFINED)
}

/// Mark as safe (no-op in our implementation).
fn filter_safe(value: &Value) -> Value {
    value.clone()
}

// ============================================================================
// Custom Tests
// ============================================================================

/// Test if value is defined.
fn test_defined(value: &Value) -> bool {
    !value.is_undefined()
}

/// Test if value is undefined.
fn test_undefined(value: &Value) -> bool {
    value.is_undefined()
}

/// Test if value is none/null.
fn test_none(value: &Value) -> bool {
    value.is_none()
}

/// Test if value is a string.
fn test_string(value: &Value) -> bool {
    value.kind() == ValueKind::String
}

/// Test if value is a number.
fn test_number(value: &Value) -> bool {
    value.kind() == ValueKind::Number
}

/// Test if value is a sequence (list).
fn test_sequence(value: &Value) -> bool {
    value.kind() == ValueKind::Seq
}

/// Test if value is a mapping (dict).
fn test_mapping(value: &Value) -> bool {
    value.kind() == ValueKind::Map
}

/// Convert minijinja Value back to serde_json::Value.
fn minijinja_to_json(value: &Value) -> serde_json::Value {
    if value.is_undefined() || value.is_none() {
        return serde_json::Value::Null;
    }
    // Check for bool by testing is_true and kind
    if value.kind() == ValueKind::Bool {
        return serde_json::Value::Bool(value.is_true());
    }
    if let Some(i) = value.as_i64() {
        return serde_json::Value::Number(i.into());
    }
    if let Some(s) = value.as_str() {
        return serde_json::Value::String(s.to_string());
    }
    if value.kind() == ValueKind::Seq {
        if let Ok(iter) = value.try_iter() {
            let arr: Vec<serde_json::Value> = iter.map(|v| minijinja_to_json(&v)).collect();
            return serde_json::Value::Array(arr);
        }
    }
    if value.kind() == ValueKind::Map {
        let mut map = serde_json::Map::new();
        if let Ok(iter) = value.try_iter() {
            for key in iter {
                if let Ok(val) = value.get_item(&key) {
                    map.insert(key.to_string(), minijinja_to_json(&val));
                }
            }
        }
        return serde_json::Value::Object(map);
    }
    // Fallback to string
    serde_json::Value::String(value.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_context() -> HashMap<String, serde_json::Value> {
        let mut ctx = HashMap::new();
        ctx.insert("name".to_string(), serde_json::json!("Alice"));
        ctx.insert("age".to_string(), serde_json::json!(30));
        ctx.insert("active".to_string(), serde_json::json!(true));
        ctx.insert(
            "items".to_string(),
            serde_json::json!(["apple", "banana", "cherry"]),
        );
        ctx.insert(
            "user".to_string(),
            serde_json::json!({"email": "alice@example.com", "id": 123}),
        );
        ctx
    }

    #[test]
    fn test_simple_variable() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer.render("Hello, {{ name }}!", &ctx).unwrap();
        assert_eq!(result, "Hello, Alice!");
    }

    #[test]
    fn test_no_template() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer.render("Plain text", &ctx).unwrap();
        assert_eq!(result, "Plain text");
    }

    #[test]
    fn test_nested_variable() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer.render("Email: {{ user.email }}", &ctx).unwrap();
        assert_eq!(result, "Email: alice@example.com");
    }

    #[test]
    fn test_b64encode_filter() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer.render("{{ name | b64encode }}", &ctx).unwrap();
        assert_eq!(result, "QWxpY2U=");
    }

    #[test]
    fn test_default_filter() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer
            .render("{{ missing | default('fallback') }}", &ctx)
            .unwrap();
        assert_eq!(result, "fallback");
    }

    #[test]
    fn test_lower_upper_filters() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer.render("{{ name | lower }}", &ctx).unwrap();
        assert_eq!(result, "alice");

        let result = renderer.render("{{ name | upper }}", &ctx).unwrap();
        assert_eq!(result, "ALICE");
    }

    #[test]
    fn test_length_filter() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer.render("{{ items | length }}", &ctx).unwrap();
        assert_eq!(result, "3");
    }

    #[test]
    fn test_first_last_filters() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer.render("{{ items | first }}", &ctx).unwrap();
        assert_eq!(result, "apple");

        let result = renderer.render("{{ items | last }}", &ctx).unwrap();
        assert_eq!(result, "cherry");
    }

    #[test]
    fn test_join_filter() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer.render("{{ items | join(', ') }}", &ctx).unwrap();
        assert_eq!(result, "apple, banana, cherry");
    }

    #[test]
    fn test_conditional() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer
            .render("{% if active %}Active{% else %}Inactive{% endif %}", &ctx)
            .unwrap();
        assert_eq!(result, "Active");
    }

    #[test]
    fn test_for_loop() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer
            .render("{% for item in items %}{{ item }} {% endfor %}", &ctx)
            .unwrap();
        assert_eq!(result, "apple banana cherry ");
    }

    #[test]
    fn test_evaluate_condition() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        assert!(renderer.evaluate_condition("age > 25", &ctx).unwrap());
        assert!(!renderer.evaluate_condition("age < 25", &ctx).unwrap());
        assert!(renderer.evaluate_condition("active", &ctx).unwrap());
    }

    #[test]
    fn test_render_to_value_json() {
        let renderer = TemplateRenderer::new();
        let mut ctx = HashMap::new();
        ctx.insert("data".to_string(), serde_json::json!({"key": "value"}));

        let result = renderer
            .render_to_value("{{ data | tojson }}", &ctx)
            .unwrap();
        assert_eq!(result, serde_json::json!({"key": "value"}));
    }

    #[test]
    fn test_render_to_value_number() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let result = renderer.render_to_value("{{ age }}", &ctx).unwrap();
        assert_eq!(result, serde_json::json!(30));
    }

    #[test]
    fn test_render_value_nested() {
        let renderer = TemplateRenderer::new();
        let ctx = make_context();

        let value = serde_json::json!({
            "greeting": "Hello, {{ name }}!",
            "info": {
                "age_str": "Age: {{ age }}"
            }
        });

        let result = renderer.render_value(&value, &ctx).unwrap();
        assert_eq!(result["greeting"], "Hello, Alice!");
        assert_eq!(result["info"]["age_str"], "Age: 30");
    }
}
