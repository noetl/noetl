use std::net::SocketAddr;

use anyhow::Context;
use async_graphql::{EmptySubscription, Schema};
use async_graphql_axum::GraphQL;
use async_graphql::http::playground_source;
use axum::{extract::State, routing::get, Router, response::Html};
use dotenvy::dotenv;
use tracing_subscriber::EnvFilter;

mod graphql;
mod noetl_client;

use crate::graphql::schema::{MutationRoot, QueryRoot, AppSchema};
use crate::noetl_client::NoetlClient;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .with_target(false)
        .init();

    let port: u16 = std::env::var("ROUTER_PORT").ok().and_then(|s| s.parse().ok()).unwrap_or(8090);
    let noetl_base = std::env::var("NOETL_BASE_URL").unwrap_or_else(|_| "http://localhost:8082".to_string());
    let nats_url = std::env::var("NATS_URL").unwrap_or_else(|_| "nats://127.0.0.1:4222".to_string());
    let subject_prefix = std::env::var("NATS_UPDATES_SUBJECT_PREFIX").unwrap_or_else(|_| "playbooks.executions.".to_string());

    let noetl = NoetlClient::new(noetl_base.clone());

    let schema: AppSchema = Schema::build(QueryRoot, MutationRoot, async_graphql::EmptySubscription)
        .data(noetl)
        .finish();

    let app = Router::new()
        .route("/", get(playground))
        .route("/graphql", get(graphiql).post_service(GraphQL::new(schema.clone())))
        .with_state(());

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!(%addr, noetl_base, nats_url, "starting noetl-gateway (Phase 1, NATS disabled)");
    axum::Server::bind(&addr).serve(app.into_make_service()).await?;
    Ok(())
}

async fn playground() -> Html<String> {
    let html = playground_source(async_graphql::http::GraphQLPlaygroundConfig::new("/graphql"));
    Html(html)
}

async fn graphiql(State(()): State<()>) -> &'static str {
    "Use POST /graphql for GraphQL and GET / for Playground"
}
