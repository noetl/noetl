use async_graphql::{SimpleObject, ID, Json};
use serde::{Deserialize, Serialize};

#[derive(SimpleObject, Clone, Debug)]
pub struct Execution {
    pub id: ID,
    pub name: String,
    pub status: Option<String>,
}

// Generic JSON passthrough for variables and events
pub type JsonValue = Json<serde_json::Value>;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutePlaybookInput {
    pub name: String,
    #[serde(default)]
    pub variables: serde_json::Value,
}
