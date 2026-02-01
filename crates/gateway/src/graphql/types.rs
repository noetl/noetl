use async_graphql::{InputObject, Json, SimpleObject, ID};

// ============================================================================
// EXECUTION TYPES
// ============================================================================

/// Result of executing a playbook.
#[derive(SimpleObject, Clone, Debug)]
pub struct ExecuteResult {
    /// Execution ID (alias for GraphQL compatibility).
    pub id: String,
    /// Execution ID (snowflake).
    pub execution_id: String,
    /// Request ID for async callback tracking.
    #[graphql(name = "requestId")]
    pub request_id: Option<String>,
    /// Playbook name/path.
    pub name: Option<String>,
    /// Initial status.
    pub status: Option<String>,
    /// Text output from playbook (populated when available).
    #[graphql(name = "textOutput")]
    pub text_output: Option<String>,
}

// ============================================================================
// PROXY TYPES
// ============================================================================

/// Result of a proxy API request to NoETL.
#[derive(SimpleObject, Clone, Debug)]
pub struct ProxyResponse {
    /// Whether the request was successful.
    pub success: bool,
    /// Response data (JSON).
    pub data: Option<Json<serde_json::Value>>,
    /// Error message if failed.
    pub error: Option<String>,
}

/// Input for proxy API request.
#[derive(InputObject, Clone, Debug)]
pub struct ProxyRequestInput {
    /// HTTP method (GET, POST, PUT, DELETE, PATCH).
    pub method: String,
    /// API endpoint (e.g., "/api/catalog/list").
    pub endpoint: String,
    /// Request body (JSON) - optional for GET/DELETE.
    pub body: Option<Json<serde_json::Value>>,
}
