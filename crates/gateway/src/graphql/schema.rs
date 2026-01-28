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

use super::types::*;
use crate::noetl_client::NoetlClient;

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
    /// This is kept for backward compatibility with auth module and simple use cases.
    /// For full API access, use the REST proxy at /noetl/* or proxyRequest mutation.
    async fn execute_playbook(
        &self,
        ctx: &Context<'_>,
        #[graphql(desc = "Playbook path")] name: String,
        #[graphql(desc = "Execution variables")] variables: Option<Json<serde_json::Value>>,
    ) -> GqlResult<ExecuteResult> {
        let client = ctx.data::<Arc<NoetlClient>>()?;
        let args = variables.map(|j| j.0).unwrap_or(serde_json::Value::Null);

        let result = client
            .execute_playbook(&name, args)
            .await
            .map_err(|e| async_graphql::Error::new(e.to_string()))?;

        Ok(ExecuteResult {
            execution_id: result.execution_id,
            name: result.name.or(Some(name)),
            status: result.status,
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
