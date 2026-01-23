//! Sensitive data sanitization for NoETL.
//!
//! This module provides utilities to redact sensitive information like bearer tokens,
//! passwords, API keys, and other credentials from JSON values before they are
//! logged or stored in events.

use serde_json::{Map, Value};
use std::collections::HashSet;

/// Default redaction placeholder
const REDACTED: &str = "[REDACTED]";

/// Keys that indicate sensitive data (lowercase for comparison)
static SENSITIVE_KEYS: &[&str] = &[
    // Authentication
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "bearer",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "auth_token",
    "authorization",
    "auth",
    "credential",
    "credentials",
    "private_key",
    "privatekey",
    "secret_key",
    "secretkey",
    "client_secret",
    "clientsecret",
    // Database
    "connection_string",
    "connectionstring",
    "db_password",
    "database_password",
    // Cloud
    "aws_secret",
    "gcp_key",
    "azure_key",
    // SSH/TLS
    "ssh_key",
    "sshkey",
    "passphrase",
    "pem",
    "cert",
    "certificate",
    // OAuth
    "oauth_token",
    "id_token",
    // Encryption
    "encryption_key",
    "decrypt_key",
    "master_key",
    // Snowflake specific
    "snowflake_password",
    "snowflake_token",
    "private_key_passphrase",
];

/// Check if a key indicates sensitive data.
fn is_sensitive_key(key: &str) -> bool {
    let key_lower = key.to_lowercase().replace('-', "_");

    // Direct match
    if SENSITIVE_KEYS.contains(&key_lower.as_str()) {
        return true;
    }

    // Partial match (key contains sensitive term)
    for sensitive in SENSITIVE_KEYS {
        if key_lower.contains(sensitive) {
            return true;
        }
    }

    false
}

/// Check if a string value looks like sensitive data.
fn is_sensitive_value(value: &str) -> bool {
    // Bearer token pattern
    if value.to_lowercase().starts_with("bearer ") {
        return true;
    }

    // Basic auth header
    if value.to_lowercase().starts_with("basic ") {
        return true;
    }

    // JWT pattern (header.payload.signature)
    if value.starts_with("eyJ")
        && value.chars().filter(|&c| c == '.').count() == 2
        && value.len() > 50
    {
        return true;
    }

    // Private key content
    if value.contains("-----BEGIN") && value.contains("PRIVATE KEY-----") {
        return true;
    }

    // Long alphanumeric strings (potential API keys) - 40+ chars
    if value.len() >= 40 && value.chars().all(|c| c.is_alphanumeric() || c == '+' || c == '/' || c == '=') {
        return true;
    }

    false
}

/// Recursively sanitize sensitive data from a JSON value.
///
/// This function:
/// - Redacts values for keys that match sensitive patterns (password, token, etc.)
/// - Redacts string values that match sensitive value patterns (Bearer tokens, JWTs)
/// - Recursively processes nested objects and arrays
/// - Returns a new value (does not modify the original)
///
/// # Arguments
///
/// * `value` - JSON value to sanitize
///
/// # Returns
///
/// Sanitized copy of the value
pub fn sanitize_sensitive_data(value: &Value) -> Value {
    sanitize_recursive(value, 0, 20)
}

/// Internal recursive sanitization helper with depth limiting.
fn sanitize_recursive(value: &Value, depth: usize, max_depth: usize) -> Value {
    // Prevent infinite recursion
    if depth >= max_depth {
        return value.clone();
    }

    match value {
        Value::Object(map) => {
            let mut result = Map::new();
            for (key, val) in map {
                if is_sensitive_key(key) {
                    result.insert(key.clone(), Value::String(REDACTED.to_string()));
                } else {
                    result.insert(key.clone(), sanitize_recursive(val, depth + 1, max_depth));
                }
            }
            Value::Object(result)
        }
        Value::Array(arr) => {
            Value::Array(
                arr.iter()
                    .map(|item| sanitize_recursive(item, depth + 1, max_depth))
                    .collect(),
            )
        }
        Value::String(s) => {
            if is_sensitive_value(s) {
                Value::String(REDACTED.to_string())
            } else {
                value.clone()
            }
        }
        // Scalars (numbers, booleans, null) - return as-is
        _ => value.clone(),
    }
}

/// Sanitize HTTP headers for logging.
///
/// Specifically redacts Authorization, Cookie, and other sensitive headers.
pub fn sanitize_headers(headers: &Map<String, Value>) -> Map<String, Value> {
    let sensitive_headers: HashSet<&str> = [
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-access-token",
        "proxy-authorization",
        "www-authenticate",
    ]
    .iter()
    .copied()
    .collect();

    let mut result = Map::new();
    for (key, value) in headers {
        if sensitive_headers.contains(key.to_lowercase().as_str()) || is_sensitive_key(key) {
            result.insert(key.clone(), Value::String(REDACTED.to_string()));
        } else {
            result.insert(key.clone(), value.clone());
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_sanitize_password_key() {
        let data = json!({"user": "admin", "password": "secret123"});
        let result = sanitize_sensitive_data(&data);
        assert_eq!(result["user"], "admin");
        assert_eq!(result["password"], "[REDACTED]");
    }

    #[test]
    fn test_sanitize_bearer_token_key() {
        let data = json!({"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"});
        let result = sanitize_sensitive_data(&data);
        assert_eq!(result["Authorization"], "[REDACTED]");
    }

    #[test]
    fn test_sanitize_bearer_value() {
        let data = json!({"header": "Bearer xyz123abc456"});
        let result = sanitize_sensitive_data(&data);
        assert_eq!(result["header"], "[REDACTED]");
    }

    #[test]
    fn test_sanitize_nested() {
        let data = json!({
            "config": {
                "username": "admin",
                "api_key": "secret_key_123"
            }
        });
        let result = sanitize_sensitive_data(&data);
        assert_eq!(result["config"]["username"], "admin");
        assert_eq!(result["config"]["api_key"], "[REDACTED]");
    }

    #[test]
    fn test_sanitize_array() {
        let data = json!([
            {"name": "item1", "token": "secret1"},
            {"name": "item2", "token": "secret2"}
        ]);
        let result = sanitize_sensitive_data(&data);
        assert_eq!(result[0]["name"], "item1");
        assert_eq!(result[0]["token"], "[REDACTED]");
        assert_eq!(result[1]["token"], "[REDACTED]");
    }

    #[test]
    fn test_non_sensitive_preserved() {
        let data = json!({
            "name": "test",
            "count": 42,
            "enabled": true,
            "tags": ["a", "b"]
        });
        let result = sanitize_sensitive_data(&data);
        assert_eq!(result, data);
    }

    #[test]
    fn test_jwt_detection() {
        let data = json!({
            "header": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.Rq8IjqbeD5K5"
        });
        let result = sanitize_sensitive_data(&data);
        assert_eq!(result["header"], "[REDACTED]");
    }
}
