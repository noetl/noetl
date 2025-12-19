use async_graphql::{Context, EmptySubscription, ID, Json, Object, Result as GqlResult, Schema};
use tokio::time::sleep;
use tracing::event;

use super::types::Execution;
use crate::{
    db::get_events_by_execution_id, get_val::get_val_string, noetl_client::NoetlClient, result_ext::ResultExt,
};
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
        let pool = ctx.data::<sqlx::Pool<sqlx::Postgres>>()?;
        let vars = variables.map(|j| j.0).unwrap_or(serde_json::Value::Null);
        let resp = client.execute_playbook(&name, vars).await.log("execute playbook")?;
        let event = get_events_by_execution_id(&pool, &resp.execution_id)
            .await
            .log("get events by execution id")?;
        sleep(std::time::Duration::from_secs(10)).await;
        let event = event.ok_or_else(|| async_graphql::Error::new("No event found for execution id"))?;
        // println!("Fetched event: {}", serde_json::to_string_pretty(&event).unwrap());
        let md_ecoded = get_val_string(
            event.output_data.as_ref().unwrap_or(&serde_json::Value::Null),
            &["response_base64"],
            "",
        );
        // let md_ecoded = get_val_string(
        //     event.input_data.as_ref().unwrap_or(&serde_json::Value::Null),
        //     &["amadeus_response_base64"],
        //     "",
        // );
        // println!("Fetched md_ecoded:\n{}", md_ecoded);
        let decoded_bytes =
            base64::decode(&md_ecoded).map_err(|_| async_graphql::Error::new("No event found for execution id"))?;
        let md_decoded = String::from_utf8_lossy(&decoded_bytes);
        let ai_resp = serde_json::from_str::<serde_json::Value>(&md_decoded)
            .map_err(|_| async_graphql::Error::new("No event found for execution id"))?;
        let md_decoded = get_val_string(&ai_resp, &["choices", "0", "message", "content"], "");
        // println!("Fetched md_decoded:\n{}", md_decoded);
        Ok(Execution {
            id: ID(resp.execution_id.clone()),
            name: resp.name.unwrap_or(name),
            status: resp.status,
            text_output: Some(md_decoded.to_string()),
        })
    }
}
