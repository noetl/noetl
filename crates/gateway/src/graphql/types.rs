use async_graphql::{InputObject, Json, SimpleObject, ID};

// ============================================================================
// EXECUTION TYPES
// ============================================================================

/// Result of executing a playbook.
#[derive(SimpleObject, Clone, Debug)]
pub struct ExecuteResult {
    /// New execution ID.
    pub execution_id: String,
    /// Playbook name/path.
    pub name: Option<String>,
    /// Initial status.
    pub status: Option<String>,
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
