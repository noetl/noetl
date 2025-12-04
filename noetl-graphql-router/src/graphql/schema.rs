use std::pin::Pin;

use async_graphql::{Context, Object, Schema, Subscription, Result as GqlResult, EmptyMutation, EmptySubscription, ID, Json};
use futures::{Stream, StreamExt};

use crate::noetl_client::NoetlClient;
use crate::nats::Nats;
use super::types::{Execution, JsonValue};

pub type AppSchema = Schema<QueryRoot, MutationRoot, SubscriptionRoot>;

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
        let resp = client.execute_playbook(&name, vars).await?;
        Ok(Execution {
            id: ID(resp.execution_id.clone()),
            name: resp.name.unwrap_or(name),
            status: resp.status,
        })
    }
}

pub struct SubscriptionRoot;

#[Subscription]
impl SubscriptionRoot {
    async fn playbook_updates(
        &self,
        ctx: &Context<'_>,
        execution_id: ID,
    ) -> GqlResult<impl Stream<Item = JsonValue>> {
        let nats = ctx.data::<Nats>()?.clone();
        let prefix = ctx.data::<String>()?.clone();
        let subject = format!("{}{}.events", prefix, execution_id.as_str());
        let stream = nats.subscribe_json(subject).await?;
        Ok(stream.map(|val| Json(val)))
    }
}
