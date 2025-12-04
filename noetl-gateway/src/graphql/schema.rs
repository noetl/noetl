use async_graphql::{Context, EmptySubscription, ID, Json, Object, Result as GqlResult, Schema};

use super::types::Execution;
use crate::{noetl_client::NoetlClient, result_ext::ResultExt};

pub type AppSchema = Schema<QueryRoot, MutationRoot, EmptySubscription>;

pub struct QueryRoot;

#[Object]
impl QueryRoot {
    async fn health(&self) -> &str {
        "ok"
    }
}

pub struct MutationRoot;

#[Object]
impl MutationRoot {
    /// Execute a NoETL playbook workflow.
    ///
    /// Triggers execution of a registered playbook in the NoETL catalog. The playbook
    /// is queued for processing by available workers in the distributed execution environment.
    /// # Example
    ///
    /// ```graphql
    /// mutation ExecuteAmadeus($name: String!, $vars: JSON) {
    ///   executePlaybook(name: $name, variables: $vars) {
    ///     id
    ///     name
    ///     status
    ///   }
    /// }
    /// ```
    /// ```json
    /// {
    ///   "name": "api_integration/amadeus_ai_api",
    ///   "vars": {
    ///     "query": "I want a one-way flight from SFO to JFK on March 15, 2026 for 1 adult"
    ///   }
    /// }
    /// ```
    async fn execute_playbook(
        &self,
        ctx: &Context<'_>,
        #[graphql(name = "name", desc = "The playbook name as registered in the NoETL catalog")] name: String,
        #[graphql(
            name = "variables",
            desc = "Optional workflow variables merged with playbook's workload section"
        )]
        variables: Option<Json<serde_json::Value>>,
    ) -> GqlResult<Execution> {
        let client = ctx.data::<NoetlClient>()?;
        let vars = variables.map(|j| j.0).unwrap_or(serde_json::Value::Null);
        let resp = client.execute_playbook(&name, vars).await.log("execute playbook")?;
        Ok(Execution {
            id: ID(resp.execution_id.clone()),
            name: resp.name.unwrap_or(name),
            status: resp.status,
        })
    }
}
