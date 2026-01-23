//! Variable management API handlers.
//!
//! Handles runtime variables stored in the transient table
//! for playbook execution scope.

use axum::{
    extract::{Path, State},
    Json,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::db::DbPool;
use crate::error::AppError;

/// Variable type.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VarType {
    UserDefined,
    StepResult,
    Computed,
    IteratorState,
}

impl VarType {
    #[allow(dead_code)]
    fn as_str(&self) -> &'static str {
        match self {
            VarType::UserDefined => "user_defined",
            VarType::StepResult => "step_result",
            VarType::Computed => "computed",
            VarType::IteratorState => "iterator_state",
        }
    }
}

impl std::str::FromStr for VarType {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "user_defined" => Ok(VarType::UserDefined),
            "step_result" => Ok(VarType::StepResult),
            "computed" => Ok(VarType::Computed),
            "iterator_state" => Ok(VarType::IteratorState),
            _ => Err(format!("Unknown variable type: {}", s)),
        }
    }
}

/// Variable entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Variable {
    pub var_name: String,
    pub var_type: String,
    pub var_value: serde_json::Value,
    pub source_step: Option<String>,
    pub created_at: DateTime<Utc>,
    pub accessed_at: DateTime<Utc>,
    pub access_count: i32,
}

/// Request to set a variable.
#[derive(Debug, Clone, Deserialize)]
pub struct SetVariableRequest {
    pub var_name: String,
    pub var_value: serde_json::Value,
    #[serde(default = "default_var_type")]
    pub var_type: String,
    pub source_step: Option<String>,
}

fn default_var_type() -> String {
    "user_defined".to_string()
}

/// Request to set multiple variables.
#[derive(Debug, Clone, Deserialize)]
pub struct SetVariablesRequest {
    pub variables: Vec<SetVariableRequest>,
}

/// Response for variable operations.
#[derive(Debug, Clone, Serialize)]
pub struct VariableResponse {
    pub execution_id: i64,
    pub var_name: String,
    pub status: String,
}

/// List variables for an execution.
///
/// GET /api/vars/{execution_id}
#[allow(clippy::type_complexity)]
pub async fn list(
    State(db): State<DbPool>,
    Path(execution_id): Path<i64>,
) -> Result<Json<Vec<Variable>>, AppError> {
    let rows: Vec<(
        String,
        String,
        serde_json::Value,
        Option<String>,
        DateTime<Utc>,
        DateTime<Utc>,
        i32,
    )> = sqlx::query_as(
        r#"
            SELECT var_name, var_type, var_value, source_step, created_at, accessed_at, access_count
            FROM noetl.transient
            WHERE execution_id = $1
            ORDER BY var_name
            "#,
    )
    .bind(execution_id)
    .fetch_all(&db)
    .await?;

    let variables: Vec<Variable> = rows
        .into_iter()
        .map(
            |(
                var_name,
                var_type,
                var_value,
                source_step,
                created_at,
                accessed_at,
                access_count,
            )| {
                Variable {
                    var_name,
                    var_type,
                    var_value,
                    source_step,
                    created_at,
                    accessed_at,
                    access_count,
                }
            },
        )
        .collect();

    Ok(Json(variables))
}

/// Set variables for an execution.
///
/// POST /api/vars/{execution_id}
pub async fn set(
    State(db): State<DbPool>,
    Path(execution_id): Path<i64>,
    Json(request): Json<SetVariablesRequest>,
) -> Result<Json<serde_json::Value>, AppError> {
    let mut set_count = 0;

    for var in &request.variables {
        // Validate var_type
        let var_type = match var.var_type.as_str() {
            "user_defined" | "step_result" | "computed" | "iterator_state" => var.var_type.as_str(),
            _ => {
                return Err(AppError::Validation(format!(
                    "Invalid var_type: {}",
                    var.var_type
                )))
            }
        };

        sqlx::query(
            r#"
            INSERT INTO noetl.transient (
                execution_id, var_name, var_type, var_value, source_step, created_at, accessed_at, access_count
            ) VALUES ($1, $2, $3, $4, $5, NOW(), NOW(), 0)
            ON CONFLICT (execution_id, var_name) DO UPDATE SET
                var_value = EXCLUDED.var_value,
                var_type = EXCLUDED.var_type,
                source_step = EXCLUDED.source_step,
                accessed_at = NOW()
            "#,
        )
        .bind(execution_id)
        .bind(&var.var_name)
        .bind(var_type)
        .bind(&var.var_value)
        .bind(&var.source_step)
        .execute(&db)
        .await?;

        set_count += 1;
    }

    Ok(Json(serde_json::json!({
        "execution_id": execution_id,
        "variables_set": set_count,
        "status": "ok"
    })))
}

/// Get a specific variable.
///
/// GET /api/vars/{execution_id}/{var_name}
#[allow(clippy::type_complexity)]
pub async fn get(
    State(db): State<DbPool>,
    Path((execution_id, var_name)): Path<(i64, String)>,
) -> Result<Json<Variable>, AppError> {
    // Update access tracking and return variable
    let row: Option<(String, String, serde_json::Value, Option<String>, DateTime<Utc>, DateTime<Utc>, i32)> =
        sqlx::query_as(
            r#"
            UPDATE noetl.transient
            SET accessed_at = NOW(), access_count = access_count + 1
            WHERE execution_id = $1 AND var_name = $2
            RETURNING var_name, var_type, var_value, source_step, created_at, accessed_at, access_count
            "#,
        )
        .bind(execution_id)
        .bind(&var_name)
        .fetch_optional(&db)
        .await?;

    match row {
        Some((
            var_name,
            var_type,
            var_value,
            source_step,
            created_at,
            accessed_at,
            access_count,
        )) => Ok(Json(Variable {
            var_name,
            var_type,
            var_value,
            source_step,
            created_at,
            accessed_at,
            access_count,
        })),
        None => Err(AppError::NotFound(format!(
            "Variable not found: {} for execution {}",
            var_name, execution_id
        ))),
    }
}

/// Delete a specific variable.
///
/// DELETE /api/vars/{execution_id}/{var_name}
pub async fn delete_var(
    State(db): State<DbPool>,
    Path((execution_id, var_name)): Path<(i64, String)>,
) -> Result<Json<VariableResponse>, AppError> {
    let result =
        sqlx::query("DELETE FROM noetl.transient WHERE execution_id = $1 AND var_name = $2")
            .bind(execution_id)
            .bind(&var_name)
            .execute(&db)
            .await?;

    if result.rows_affected() == 0 {
        return Err(AppError::NotFound(format!(
            "Variable not found: {} for execution {}",
            var_name, execution_id
        )));
    }

    Ok(Json(VariableResponse {
        execution_id,
        var_name,
        status: "deleted".to_string(),
    }))
}

/// Delete all variables for an execution (cleanup).
///
/// DELETE /api/vars/{execution_id}
pub async fn cleanup(
    State(db): State<DbPool>,
    Path(execution_id): Path<i64>,
) -> Result<Json<serde_json::Value>, AppError> {
    let result = sqlx::query("DELETE FROM noetl.transient WHERE execution_id = $1")
        .bind(execution_id)
        .execute(&db)
        .await?;

    Ok(Json(serde_json::json!({
        "execution_id": execution_id,
        "variables_deleted": result.rows_affected(),
        "status": "ok"
    })))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_var_type_from_str() {
        assert!(matches!(
            "user_defined".parse::<VarType>().unwrap(),
            VarType::UserDefined
        ));
        assert!(matches!(
            "step_result".parse::<VarType>().unwrap(),
            VarType::StepResult
        ));
        assert!("invalid".parse::<VarType>().is_err());
    }

    #[test]
    fn test_var_type_as_str() {
        assert_eq!(VarType::UserDefined.as_str(), "user_defined");
        assert_eq!(VarType::StepResult.as_str(), "step_result");
    }

    #[test]
    fn test_variable_serialization() {
        let var = Variable {
            var_name: "test_var".to_string(),
            var_type: "user_defined".to_string(),
            var_value: serde_json::json!({"key": "value"}),
            source_step: Some("step1".to_string()),
            created_at: Utc::now(),
            accessed_at: Utc::now(),
            access_count: 5,
        };

        let json = serde_json::to_string(&var).unwrap();
        assert!(json.contains("test_var"));
        assert!(json.contains("user_defined"));
    }

    #[test]
    fn test_set_variable_request_defaults() {
        let json = r#"{"var_name": "test", "var_value": 42}"#;
        let request: SetVariableRequest = serde_json::from_str(json).unwrap();
        assert_eq!(request.var_type, "user_defined");
    }
}
