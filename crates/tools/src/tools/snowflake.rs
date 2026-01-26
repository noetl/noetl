//! Snowflake database query execution tool.
//!
//! This tool uses the Snowflake SQL REST API to execute queries.
//! See: https://docs.snowflake.com/en/developer-guide/sql-api/

use async_trait::async_trait;
use base64::Engine;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::registry::{Tool, ToolConfig};
use crate::result::ToolResult;
use crate::template::TemplateEngine;

/// Snowflake tool configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SnowflakeConfig {
    /// Base64-encoded SQL command(s).
    #[serde(alias = "commands_b64")]
    pub command_b64: Option<String>,

    /// Plain SQL command (alternative to base64).
    pub command: Option<String>,

    /// Multiple SQL commands.
    pub commands: Option<Vec<String>>,

    /// Snowflake account identifier (e.g., "myaccount" or "myaccount.us-east-1").
    pub account: String,

    /// Username.
    pub user: String,

    /// Password (for password authentication).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub password: Option<String>,

    /// Private key in PEM format (for key-pair authentication).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub private_key: Option<String>,

    /// Passphrase for encrypted private key.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub private_key_passphrase: Option<String>,

    /// Warehouse name.
    #[serde(default = "default_warehouse")]
    pub warehouse: String,

    /// Database name.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub database: Option<String>,

    /// Schema name.
    #[serde(default = "default_schema")]
    pub schema: String,

    /// User role.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
}

fn default_warehouse() -> String {
    "COMPUTE_WH".to_string()
}

fn default_schema() -> String {
    "PUBLIC".to_string()
}

/// Result from a single SQL statement execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StatementResult {
    /// Status of the statement execution.
    pub status: String,

    /// Number of rows affected or returned.
    pub row_count: usize,

    /// Result data (for SELECT queries).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Vec<serde_json::Value>>,

    /// Column names.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub columns: Option<Vec<String>>,

    /// Error message if failed.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Snowflake SQL API response.
#[derive(Debug, Deserialize)]
struct SnowflakeResponse {
    #[serde(default)]
    data: Vec<Vec<serde_json::Value>>,
    #[serde(rename = "resultSetMetaData")]
    result_set_meta_data: Option<ResultSetMetaData>,
    message: Option<String>,
    #[serde(rename = "statementHandle")]
    statement_handle: Option<String>,
    #[serde(rename = "statementStatusUrl")]
    statement_status_url: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ResultSetMetaData {
    #[serde(rename = "rowType")]
    row_type: Option<Vec<RowType>>,
    #[serde(rename = "numRows")]
    num_rows: Option<i64>,
}

#[derive(Debug, Deserialize)]
struct RowType {
    name: String,
    #[serde(rename = "type")]
    data_type: Option<String>,
}

/// Snowflake login response.
#[derive(Debug, Deserialize)]
struct LoginResponse {
    data: Option<LoginData>,
    message: Option<String>,
    success: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct LoginData {
    token: Option<String>,
    #[serde(rename = "masterToken")]
    master_token: Option<String>,
}

/// Snowflake query execution tool.
pub struct SnowflakeTool {
    http_client: Client,
    template_engine: TemplateEngine,
}

impl SnowflakeTool {
    /// Create a new Snowflake tool.
    pub fn new() -> Self {
        Self {
            http_client: Client::new(),
            template_engine: TemplateEngine::new(),
        }
    }

    /// Execute SQL commands against Snowflake.
    pub async fn execute_commands(
        &self,
        config: &SnowflakeConfig,
    ) -> Result<ToolResult, ToolError> {
        let start = std::time::Instant::now();

        // Get SQL commands
        let commands = self.get_commands(config)?;

        if commands.is_empty() {
            return Err(ToolError::Configuration(
                "No SQL commands provided".to_string(),
            ));
        }

        // Get session token
        let token = self.authenticate(config).await?;

        let mut results: HashMap<String, StatementResult> = HashMap::new();
        let mut overall_success = true;

        // Build base URL
        let account_url = self.get_account_url(&config.account);

        // Execute setup commands first
        let mut setup_commands = Vec::new();
        setup_commands.push(format!("USE WAREHOUSE {}", config.warehouse));
        if let Some(ref db) = config.database {
            setup_commands.push(format!("USE DATABASE {}", db));
        }
        setup_commands.push(format!("USE SCHEMA {}", config.schema));
        if let Some(ref role) = config.role {
            setup_commands.push(format!("USE ROLE {}", role));
        }

        // Execute setup commands (ignore errors)
        for setup_cmd in setup_commands {
            let _ = self
                .execute_statement(&account_url, &token, &setup_cmd)
                .await;
        }

        // Execute user commands
        for (idx, command) in commands.iter().enumerate() {
            let key = format!("statement_{}", idx);

            match self
                .execute_statement(&account_url, &token, command)
                .await
            {
                Ok(response) => {
                    let (rows, columns, row_count) = self.parse_response(&response);

                    results.insert(
                        key,
                        StatementResult {
                            status: "success".to_string(),
                            row_count,
                            result: rows,
                            columns,
                            error: None,
                        },
                    );
                }
                Err(e) => {
                    overall_success = false;
                    results.insert(
                        key,
                        StatementResult {
                            status: "error".to_string(),
                            row_count: 0,
                            result: None,
                            columns: None,
                            error: Some(e.to_string()),
                        },
                    );
                }
            }
        }

        let duration_ms = start.elapsed().as_millis() as u64;

        if overall_success {
            Ok(ToolResult::success(serde_json::json!(results)).with_duration(duration_ms))
        } else {
            Ok(ToolResult::error("Some statements failed".to_string())
                .with_data(serde_json::json!(results))
                .with_duration(duration_ms))
        }
    }

    /// Authenticate with Snowflake and get a session token.
    async fn authenticate(&self, config: &SnowflakeConfig) -> Result<String, ToolError> {
        let password = config.password.clone().ok_or_else(|| {
            ToolError::Configuration(
                "Password is required for Snowflake authentication".to_string(),
            )
        })?;

        let account_url = self.get_account_url(&config.account);
        let login_url = format!("{}/session/v1/login-request", account_url);

        let login_body = serde_json::json!({
            "data": {
                "LOGIN_NAME": config.user,
                "PASSWORD": password,
                "ACCOUNT_NAME": config.account,
            }
        });

        let response = self
            .http_client
            .post(&login_url)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .json(&login_body)
            .send()
            .await
            .map_err(|e| ToolError::Http(format!("Snowflake login request failed: {}", e)))?;

        let login_response: LoginResponse = response
            .json()
            .await
            .map_err(|e| ToolError::Http(format!("Failed to parse Snowflake login response: {}", e)))?;

        if login_response.success != Some(true) {
            return Err(ToolError::Auth(
                login_response
                    .message
                    .unwrap_or_else(|| "Unknown authentication error".to_string()),
            ));
        }

        login_response
            .data
            .and_then(|d| d.token)
            .ok_or_else(|| ToolError::Auth("No token in login response".to_string()))
    }

    /// Execute a single SQL statement.
    async fn execute_statement(
        &self,
        account_url: &str,
        token: &str,
        statement: &str,
    ) -> Result<SnowflakeResponse, ToolError> {
        let sql_url = format!("{}/api/v2/statements", account_url);

        let body = serde_json::json!({
            "statement": statement,
            "timeout": 60,
            "resultSetMetaData": {
                "format": "jsonv2"
            }
        });

        let response = self
            .http_client
            .post(&sql_url)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .header("Authorization", format!("Snowflake Token=\"{}\"", token))
            .header("X-Snowflake-Authorization-Token-Type", "KEYPAIR_JWT")
            .json(&body)
            .send()
            .await
            .map_err(|e| ToolError::Http(format!("Snowflake statement failed: {}", e)))?;

        let status = response.status();
        if !status.is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(ToolError::Database(format!(
                "Snowflake query failed with status {}: {}",
                status, error_text
            )));
        }

        response
            .json()
            .await
            .map_err(|e| ToolError::Http(format!("Failed to parse Snowflake response: {}", e)))
    }

    /// Parse Snowflake response into rows and columns.
    fn parse_response(
        &self,
        response: &SnowflakeResponse,
    ) -> (Option<Vec<serde_json::Value>>, Option<Vec<String>>, usize) {
        let columns: Vec<String> = response
            .result_set_meta_data
            .as_ref()
            .and_then(|m| m.row_type.as_ref())
            .map(|rt| rt.iter().map(|r| r.name.clone()).collect())
            .unwrap_or_default();

        if response.data.is_empty() {
            return (None, if columns.is_empty() { None } else { Some(columns) }, 0);
        }

        let rows: Vec<serde_json::Value> = response
            .data
            .iter()
            .map(|row| {
                let mut obj = serde_json::Map::new();
                for (i, col_name) in columns.iter().enumerate() {
                    let value = row.get(i).cloned().unwrap_or(serde_json::Value::Null);
                    obj.insert(col_name.clone(), value);
                }
                serde_json::Value::Object(obj)
            })
            .collect();

        let row_count = rows.len();
        (Some(rows), Some(columns), row_count)
    }

    /// Get the Snowflake account URL.
    fn get_account_url(&self, account: &str) -> String {
        // Handle both formats: "account" and "account.region"
        if account.contains('.') {
            format!("https://{}.snowflakecomputing.com", account)
        } else {
            format!("https://{}.snowflakecomputing.com", account)
        }
    }

    /// Get SQL commands from configuration.
    fn get_commands(&self, config: &SnowflakeConfig) -> Result<Vec<String>, ToolError> {
        // Check for base64-encoded commands first
        if let Some(ref b64) = config.command_b64 {
            let decoded = base64::engine::general_purpose::STANDARD
                .decode(b64)
                .map_err(|e| ToolError::Configuration(format!("Invalid base64: {}", e)))?;
            let sql = String::from_utf8(decoded)
                .map_err(|e| ToolError::Configuration(format!("Invalid UTF-8: {}", e)))?;
            // Split by semicolon for multiple statements
            return Ok(sql
                .split(';')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect());
        }

        // Check for plain command
        if let Some(ref cmd) = config.command {
            return Ok(vec![cmd.clone()]);
        }

        // Check for multiple commands
        if let Some(ref cmds) = config.commands {
            return Ok(cmds.clone());
        }

        Err(ToolError::Configuration(
            "No SQL command provided (use command, command_b64, or commands)".to_string(),
        ))
    }

    /// Parse Snowflake config from tool config.
    fn parse_config(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<SnowflakeConfig, ToolError> {
        let template_ctx = ctx.to_template_context();
        let rendered_config = self
            .template_engine
            .render_value(&config.config, &template_ctx)?;

        serde_json::from_value(rendered_config)
            .map_err(|e| ToolError::Configuration(format!("Invalid snowflake config: {}", e)))
    }
}

impl Default for SnowflakeTool {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for SnowflakeTool {
    fn name(&self) -> &'static str {
        "snowflake"
    }

    async fn execute(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let snowflake_config = self.parse_config(config, ctx)?;

        tracing::debug!(
            account = %snowflake_config.account,
            user = %snowflake_config.user,
            warehouse = %snowflake_config.warehouse,
            "Executing Snowflake query"
        );

        self.execute_commands(&snowflake_config).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_snowflake_config_deserialization() {
        let json = serde_json::json!({
            "command": "SELECT 1",
            "account": "myaccount",
            "user": "myuser",
            "password": "mypassword",
            "warehouse": "MY_WH",
            "database": "MY_DB",
            "schema": "MY_SCHEMA"
        });

        let config: SnowflakeConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.account, "myaccount");
        assert_eq!(config.user, "myuser");
        assert_eq!(config.warehouse, "MY_WH");
        assert_eq!(config.database, Some("MY_DB".to_string()));
    }

    #[test]
    fn test_snowflake_config_defaults() {
        let json = serde_json::json!({
            "command": "SELECT 1",
            "account": "myaccount",
            "user": "myuser",
            "password": "mypassword"
        });

        let config: SnowflakeConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.warehouse, "COMPUTE_WH");
        assert_eq!(config.schema, "PUBLIC");
        assert!(config.database.is_none());
    }

    #[test]
    fn test_get_commands_base64() {
        let tool = SnowflakeTool::new();
        let b64_cmd = base64::engine::general_purpose::STANDARD.encode("SELECT 1; SELECT 2");

        let config = SnowflakeConfig {
            command_b64: Some(b64_cmd),
            command: None,
            commands: None,
            account: "test".to_string(),
            user: "test".to_string(),
            password: Some("test".to_string()),
            private_key: None,
            private_key_passphrase: None,
            warehouse: "COMPUTE_WH".to_string(),
            database: None,
            schema: "PUBLIC".to_string(),
            role: None,
        };

        let commands = tool.get_commands(&config).unwrap();
        assert_eq!(commands.len(), 2);
        assert_eq!(commands[0], "SELECT 1");
        assert_eq!(commands[1], "SELECT 2");
    }

    #[test]
    fn test_statement_result_serialization() {
        let result = StatementResult {
            status: "success".to_string(),
            row_count: 5,
            result: Some(vec![serde_json::json!({"id": 1, "name": "test"})]),
            columns: Some(vec!["id".to_string(), "name".to_string()]),
            error: None,
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("success"));
        assert!(json.contains("5"));
    }

    #[test]
    fn test_get_account_url() {
        let tool = SnowflakeTool::new();
        assert_eq!(
            tool.get_account_url("myaccount"),
            "https://myaccount.snowflakecomputing.com"
        );
        assert_eq!(
            tool.get_account_url("myaccount.us-east-1"),
            "https://myaccount.us-east-1.snowflakecomputing.com"
        );
    }

    #[tokio::test]
    async fn test_snowflake_tool_interface() {
        let tool = SnowflakeTool::new();
        assert_eq!(tool.name(), "snowflake");
    }
}
