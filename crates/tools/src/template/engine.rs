//! Template engine implementation using minijinja.

use minijinja::{Environment, Value};
use std::collections::HashMap;

use crate::context::ExecutionContext;
use crate::error::ToolError;

/// Template engine with Jinja2-compatible syntax.
pub struct TemplateEngine {
    env: Environment<'static>,
}

impl TemplateEngine {
    /// Create a new template engine with custom filters.
    pub fn new() -> Self {
        let mut env = Environment::new();

        // Register custom filters
        env.add_filter("int", filter_int);
        env.add_filter("float", filter_float);
        env.add_filter("default", filter_default);
        env.add_filter("d", filter_default); // alias
        env.add_filter("tojson", filter_tojson);
        env.add_filter("fromjson", filter_fromjson);
        env.add_filter("length", filter_length);
        env.add_filter("len", filter_length); // alias
        env.add_filter("upper", filter_upper);
        env.add_filter("lower", filter_lower);
        env.add_filter("trim", filter_trim);
        env.add_filter("replace", filter_replace);
        env.add_filter("split", filter_split);
        env.add_filter("join", filter_join);
        env.add_filter("first", filter_first);
        env.add_filter("last", filter_last);
        env.add_filter("b64encode", filter_b64encode);
        env.add_filter("b64decode", filter_b64decode);

        Self { env }
    }

    /// Render a template string with the given context.
    pub fn render(
        &self,
        template: &str,
        context: &HashMap<String, serde_json::Value>,
    ) -> Result<String, ToolError> {
        let tmpl = self.env.template_from_str(template)?;

        // Convert context to minijinja Value
        let ctx = context_to_value(context);

        tmpl.render(ctx).map_err(|e| ToolError::Template(e.to_string()))
    }

    /// Render a template with an ExecutionContext.
    pub fn render_with_context(
        &self,
        template: &str,
        ctx: &ExecutionContext,
    ) -> Result<String, ToolError> {
        self.render(template, &ctx.to_template_context())
    }

    /// Check if a string contains template syntax.
    pub fn is_template(s: &str) -> bool {
        s.contains("{{") || s.contains("{%")
    }

    /// Render a value that might be a template.
    ///
    /// If the value is a string containing template syntax, render it.
    /// Otherwise, return the JSON representation.
    pub fn render_value(
        &self,
        value: &serde_json::Value,
        context: &HashMap<String, serde_json::Value>,
    ) -> Result<serde_json::Value, ToolError> {
        match value {
            serde_json::Value::String(s) if Self::is_template(s) => {
                let rendered = self.render(s, context)?;
                // Try to parse as JSON, otherwise return as string
                Ok(serde_json::from_str(&rendered).unwrap_or_else(|_| serde_json::json!(rendered)))
            }
            serde_json::Value::Object(obj) => {
                let mut result = serde_json::Map::new();
                for (k, v) in obj {
                    result.insert(k.clone(), self.render_value(v, context)?);
                }
                Ok(serde_json::Value::Object(result))
            }
            serde_json::Value::Array(arr) => {
                let result: Result<Vec<_>, _> = arr
                    .iter()
                    .map(|v| self.render_value(v, context))
                    .collect();
                Ok(serde_json::Value::Array(result?))
            }
            _ => Ok(value.clone()),
        }
    }
}

impl Default for TemplateEngine {
    fn default() -> Self {
        Self::new()
    }
}

/// Convert a HashMap context to minijinja Value.
fn context_to_value(context: &HashMap<String, serde_json::Value>) -> Value {
    let json = serde_json::Value::Object(
        context
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect(),
    );
    Value::from_serialize(&json)
}

// Custom filters

fn filter_int(value: Value) -> Result<Value, minijinja::Error> {
    // Try to convert to i64 via string parsing
    let s = value.to_string();
    // First try parsing as integer directly
    if let Ok(n) = s.parse::<i64>() {
        return Ok(Value::from(n));
    }
    // Then try parsing as float and truncating
    if let Ok(f) = s.parse::<f64>() {
        return Ok(Value::from(f as i64));
    }
    Ok(Value::from(0i64))
}

fn filter_float(value: Value) -> Result<Value, minijinja::Error> {
    // Try to convert to f64 via string parsing
    let s = value.to_string();
    if let Ok(f) = s.parse::<f64>() {
        return Ok(Value::from(f));
    }
    // Try parsing as integer and converting
    if let Ok(n) = s.parse::<i64>() {
        return Ok(Value::from(n as f64));
    }
    Ok(Value::from(0.0f64))
}

fn filter_default(value: Value, default: Option<Value>) -> Value {
    if value.is_undefined() || value.is_none() {
        default.unwrap_or_else(|| Value::from(""))
    } else {
        value
    }
}

fn filter_tojson(value: Value) -> Result<String, minijinja::Error> {
    Ok(serde_json::to_string(&value).unwrap_or_else(|_| "null".to_string()))
}

fn filter_fromjson(value: Value) -> Result<Value, minijinja::Error> {
    let s = value.to_string();
    let json: serde_json::Value = serde_json::from_str(&s).unwrap_or(serde_json::Value::Null);
    Ok(Value::from_serialize(&json))
}

fn filter_length(value: Value) -> Result<Value, minijinja::Error> {
    match value.kind() {
        minijinja::value::ValueKind::String => Ok(Value::from(value.to_string().len())),
        minijinja::value::ValueKind::Seq => Ok(Value::from(value.len().unwrap_or(0))),
        minijinja::value::ValueKind::Map => Ok(Value::from(value.len().unwrap_or(0))),
        _ => Ok(Value::from(0)),
    }
}

fn filter_upper(value: Value) -> String {
    value.to_string().to_uppercase()
}

fn filter_lower(value: Value) -> String {
    value.to_string().to_lowercase()
}

fn filter_trim(value: Value) -> String {
    value.to_string().trim().to_string()
}

fn filter_replace(value: Value, old: String, new: String) -> String {
    value.to_string().replace(&old, &new)
}

fn filter_split(value: Value, sep: String) -> Vec<String> {
    value.to_string().split(&sep).map(|s| s.to_string()).collect()
}

fn filter_join(value: Value, sep: Option<String>) -> Result<String, minijinja::Error> {
    let sep = sep.unwrap_or_default();
    if let Some(len) = value.len() {
        let items: Vec<String> = (0..len)
            .filter_map(|i| value.get_item(&Value::from(i)).ok())
            .map(|v| v.to_string())
            .collect();
        Ok(items.join(&sep))
    } else {
        Ok(value.to_string())
    }
}

fn filter_first(value: Value) -> Result<Value, minijinja::Error> {
    if let Some(len) = value.len() {
        if len > 0 {
            return value.get_item(&Value::from(0));
        }
    }
    Ok(Value::UNDEFINED)
}

fn filter_last(value: Value) -> Result<Value, minijinja::Error> {
    if let Some(len) = value.len() {
        if len > 0 {
            return value.get_item(&Value::from(len - 1));
        }
    }
    Ok(Value::UNDEFINED)
}

fn filter_b64encode(value: Value) -> String {
    use base64::{engine::general_purpose::STANDARD, Engine};
    STANDARD.encode(value.to_string().as_bytes())
}

fn filter_b64decode(value: Value) -> Result<String, minijinja::Error> {
    use base64::{engine::general_purpose::STANDARD, Engine};
    let decoded = STANDARD
        .decode(value.to_string().as_bytes())
        .map_err(|e| minijinja::Error::new(minijinja::ErrorKind::InvalidOperation, e.to_string()))?;
    String::from_utf8(decoded)
        .map_err(|e| minijinja::Error::new(minijinja::ErrorKind::InvalidOperation, e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_template() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("name".to_string(), serde_json::json!("World"));

        let result = engine.render("Hello, {{ name }}!", &ctx).unwrap();
        assert_eq!(result, "Hello, World!");
    }

    #[test]
    fn test_filter_int() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("val".to_string(), serde_json::json!("42"));

        let result = engine.render("{{ val | int }}", &ctx).unwrap();
        assert_eq!(result, "42");
    }

    #[test]
    fn test_filter_float() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("val".to_string(), serde_json::json!("3.14"));

        let result = engine.render("{{ val | float }}", &ctx).unwrap();
        assert_eq!(result, "3.14");
    }

    #[test]
    fn test_filter_default() {
        let engine = TemplateEngine::new();
        let ctx = HashMap::new();

        let result = engine.render("{{ missing | default('fallback') }}", &ctx).unwrap();
        assert_eq!(result, "fallback");
    }

    #[test]
    fn test_filter_length() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("items".to_string(), serde_json::json!(["a", "b", "c"]));

        let result = engine.render("{{ items | length }}", &ctx).unwrap();
        assert_eq!(result, "3");
    }

    #[test]
    fn test_filter_upper_lower() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("text".to_string(), serde_json::json!("Hello"));

        let result = engine.render("{{ text | upper }}", &ctx).unwrap();
        assert_eq!(result, "HELLO");

        let result = engine.render("{{ text | lower }}", &ctx).unwrap();
        assert_eq!(result, "hello");
    }

    #[test]
    fn test_filter_trim() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("text".to_string(), serde_json::json!("  hello  "));

        let result = engine.render("{{ text | trim }}", &ctx).unwrap();
        assert_eq!(result, "hello");
    }

    #[test]
    fn test_filter_replace() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("text".to_string(), serde_json::json!("hello world"));

        let result = engine.render("{{ text | replace('world', 'rust') }}", &ctx).unwrap();
        assert_eq!(result, "hello rust");
    }

    #[test]
    fn test_filter_split_join() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("text".to_string(), serde_json::json!("a,b,c"));

        let result = engine.render("{{ text | split(',') | join('-') }}", &ctx).unwrap();
        assert_eq!(result, "a-b-c");
    }

    #[test]
    fn test_filter_first_last() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("items".to_string(), serde_json::json!(["first", "middle", "last"]));

        let result = engine.render("{{ items | first }}", &ctx).unwrap();
        assert_eq!(result, "first");

        let result = engine.render("{{ items | last }}", &ctx).unwrap();
        assert_eq!(result, "last");
    }

    #[test]
    fn test_filter_b64() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("text".to_string(), serde_json::json!("hello"));

        let result = engine.render("{{ text | b64encode }}", &ctx).unwrap();
        assert_eq!(result, "aGVsbG8=");

        ctx.insert("encoded".to_string(), serde_json::json!("aGVsbG8="));
        let result = engine.render("{{ encoded | b64decode }}", &ctx).unwrap();
        assert_eq!(result, "hello");
    }

    #[test]
    fn test_filter_tojson() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("data".to_string(), serde_json::json!({"key": "value"}));

        let result = engine.render("{{ data | tojson }}", &ctx).unwrap();
        assert!(result.contains("\"key\"") && result.contains("\"value\""));
    }

    #[test]
    fn test_is_template() {
        assert!(TemplateEngine::is_template("Hello {{ name }}"));
        assert!(TemplateEngine::is_template("{% for x in items %}{{ x }}{% endfor %}"));
        assert!(!TemplateEngine::is_template("plain text"));
    }

    #[test]
    fn test_render_value() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("name".to_string(), serde_json::json!("World"));

        // String template
        let value = serde_json::json!("Hello, {{ name }}!");
        let result = engine.render_value(&value, &ctx).unwrap();
        assert_eq!(result, serde_json::json!("Hello, World!"));

        // Object with template
        let value = serde_json::json!({
            "greeting": "Hello, {{ name }}!",
            "plain": "no template"
        });
        let result = engine.render_value(&value, &ctx).unwrap();
        assert_eq!(result["greeting"], serde_json::json!("Hello, World!"));
        assert_eq!(result["plain"], serde_json::json!("no template"));

        // Non-template value
        let value = serde_json::json!(42);
        let result = engine.render_value(&value, &ctx).unwrap();
        assert_eq!(result, serde_json::json!(42));
    }

    #[test]
    fn test_execution_context_rendering() {
        let engine = TemplateEngine::new();
        let mut ctx = ExecutionContext::new(12345, "step1", "http://localhost");
        ctx.set_variable("input", serde_json::json!("test"));

        let result = engine
            .render_with_context("Execution {{ execution_id }}: {{ input }}", &ctx)
            .unwrap();
        assert_eq!(result, "Execution 12345: test");
    }

    #[test]
    fn test_nested_object() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("user".to_string(), serde_json::json!({"name": "Alice", "age": 30}));

        let result = engine.render("{{ user.name }} is {{ user.age }}", &ctx).unwrap();
        assert_eq!(result, "Alice is 30");
    }

    #[test]
    fn test_loop() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("items".to_string(), serde_json::json!(["a", "b", "c"]));

        let result = engine
            .render("{% for item in items %}{{ item }}{% endfor %}", &ctx)
            .unwrap();
        assert_eq!(result, "abc");
    }

    #[test]
    fn test_conditional() {
        let engine = TemplateEngine::new();
        let mut ctx = HashMap::new();
        ctx.insert("active".to_string(), serde_json::json!(true));

        let result = engine
            .render("{% if active %}yes{% else %}no{% endif %}", &ctx)
            .unwrap();
        assert_eq!(result, "yes");

        ctx.insert("active".to_string(), serde_json::json!(false));
        let result = engine
            .render("{% if active %}yes{% else %}no{% endif %}", &ctx)
            .unwrap();
        assert_eq!(result, "no");
    }
}
