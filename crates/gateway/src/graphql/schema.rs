//! Simplified GraphQL schema for gateway.
//!
//! The gateway acts as an authenticated proxy. Most API calls should go through
//! the REST proxy at /noetl/* which forwards directly to NoETL server.
//!
//! This GraphQL schema provides:
//! - Health check
//! - executePlaybook mutation (used by auth module for login/validate playbooks)
//! - proxyRequest mutation (generic API proxy for clients preferring GraphQL)

use async_graphql::{Context, EmptySubscription, Json, Object, Result as GqlResult, Schema};
use std::sync::Arc;
use uuid::Uuid;

use super::types::*;
use crate::noetl_client::NoetlClient;
use crate::request_store::{PendingRequest, RequestStore};
use crate::config::GatewayConfig;

pub type AppSchema = Schema<QueryRoot, MutationRoot, EmptySubscription>;

// ============================================================================
// QUERY ROOT
// ============================================================================

pub struct QueryRoot;

#[Object]
impl QueryRoot {
    /// Health check endpoint.
    async fn health(&self) -> &str {
        "ok"
    }

    /// Gateway version info.
    async fn version(&self) -> &str {
        env!("CARGO_PKG_VERSION")
    }
}

// ============================================================================
// MUTATION ROOT
// ============================================================================

pub struct MutationRoot;

#[Object]
impl MutationRoot {
    /// Execute a playbook by path.
    ///
    /// For async callbacks (real-time results via SSE):
    /// 1. Connect to SSE endpoint first: GET /events?session_token=xxx
    /// 2. Use the returned client_id when calling this mutation
    /// 3. Results will be pushed via SSE as `playbook/result` notifications
    ///
    /// For simple fire-and-forget (no real-time results):
    /// - Omit client_id parameter
    /// - Poll NoETL API for execution status
    async fn execute_playbook(
        &self,
        ctx: &Context<'_>,
        #[graphql(desc = "Playbook path")] name: String,
        #[graphql(desc = "Execution variables")] variables: Option<Json<serde_json::Value>>,
        #[graphql(desc = "Client ID from SSE connection (for async callbacks)")] client_id: Option<String>,
    ) -> GqlResult<ExecuteResult> {
        let client = ctx.data::<Arc<NoetlClient>>()?;
        let mut args = variables.map(|j| j.0).unwrap_or(serde_json::json!({}));

        // If client_id is provided, set up async callback
        let request_id = if let Some(cid) = client_id.as_ref() {
            // Try to get request store and config from context
            let request_store = ctx.data::<Arc<RequestStore>>().ok();
            let config = ctx.data::<Arc<GatewayConfig>>().ok();

            if let Some(store) = request_store {
                let rid = Uuid::new_v4().to_string();

                // Get gateway URL for callbacks
                let gateway_url = config
                    .and_then(|c| c.server.public_url.clone())
                    .unwrap_or_else(|| "http://gateway.gateway.svc.cluster.local:8090".to_string());

                // Inject callback info into playbook args
                if let serde_json::Value::Object(ref mut map) = args {
                    map.insert("request_id".to_string(), serde_json::json!(rid));
                    map.insert("gateway_url".to_string(), serde_json::json!(gateway_url));
                }

                // We'll store the pending request after we get the execution_id
                Some((rid, cid.clone(), store.clone()))
            } else {
                tracing::warn!("Request store not available, async callbacks disabled");
                None
            }
        } else {
            None
        };

        let result = client
            .execute_playbook(&name, args)
            .await
            .map_err(|e| async_graphql::Error::new(e.to_string()))?;

        // Store pending request for callback routing
        let final_request_id = if let Some((rid, cid, store)) = request_id {
            // Get session token from context if available
            let session_token = ctx
                .data::<String>()
                .map(|s| s.clone())
                .unwrap_or_default();

            let pending = PendingRequest {
                client_id: cid,
                session_token,
                execution_id: result.execution_id.clone(),
                playbook_path: name.clone(),
                created_at: chrono::Utc::now().timestamp(),
            };

            if let Err(e) = store.put(&rid, &pending).await {
                tracing::error!("Failed to store pending request: {}", e);
            } else {
                tracing::debug!(
                    "Pending request stored: request_id={}, execution_id={}",
                    &rid[..8.min(rid.len())],
                    &result.execution_id[..8.min(result.execution_id.len())]
                );
            }

            Some(rid)
        } else {
            None
        };

        Ok(ExecuteResult {
            id: result.execution_id.clone(),
            execution_id: result.execution_id,
            request_id: final_request_id,
            name: result.name.or(Some(name)),
            status: result.status,
            text_output: None, // Results delivered via SSE callback
        })
    }

    /// Generic proxy for any NoETL API call via GraphQL.
    /// This allows clients to make any API request through GraphQL if they prefer
    /// that over the REST proxy at /noetl/*.
    ///
    /// Example:
    /// ```graphql
    /// mutation {
    ///   proxyRequest(input: {
    ///     method: "POST",
    ///     endpoint: "/api/catalog/list",
    ///     body: { "resource_type": "Playbook" }
    ///   }) {
    ///     success
    ///     data
    ///     error
    ///   }
    /// }
    /// ```
    async fn proxy_request(
        &self,
        ctx: &Context<'_>,
        #[graphql(desc = "Proxy request parameters")] input: ProxyRequestInput,
    ) -> GqlResult<ProxyResponse> {
        let client = ctx.data::<Arc<NoetlClient>>()?;

        let body = input.body.map(|j| j.0);

        match client.api_call(&input.method, &input.endpoint, body).await {
            Ok(data) => Ok(ProxyResponse {
                success: true,
                data: Some(Json(data)),
                error: None,
            }),
            Err(e) => Ok(ProxyResponse {
                success: false,
                data: None,
                error: Some(e.to_string()),
            }),
        }
    }
}
