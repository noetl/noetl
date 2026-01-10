use serde::{Deserialize, Serialize};

/// User context extracted from session token
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserContext {
    pub user_id: i32,
    pub email: String,
    pub display_name: String,
    pub session_token: String,
}
