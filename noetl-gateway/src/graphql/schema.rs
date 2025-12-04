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
    async fn execute_playbook(
        &self,
        ctx: &Context<'_>,
        name: String,
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
