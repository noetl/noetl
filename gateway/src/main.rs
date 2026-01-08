#![allow(dead_code, unused_imports, unused_variables)]

use std::net::SocketAddr;
use std::sync::Arc;

use async_graphql::http::playground_source;
use async_graphql::{EmptySubscription, Schema};
use async_graphql_axum::GraphQL;
use axum::{
    middleware,
    Router,
    extract::State,
    response::Html,
    routing::{get, post},
};
use dotenvy::dotenv;
use sqlx::postgres::PgPoolOptions;
use tower_http::{
    cors::{Any, CorsLayer},
    services::ServeDir,
};
use tracing_subscriber::EnvFilter;

mod auth;
mod config;
mod db;
mod get_val;
mod graphql;
mod noetl_client;
mod result_ext;

use crate::graphql::schema::{AppSchema, MutationRoot, QueryRoot};
use crate::noetl_client::NoetlClient;
use crate::result_ext::ResultExt;

#[ctor::ctor]
fn init() {
    dotenv().ok();
    tracing_subscriber::fmt()
        .with_thread_ids(true)
        .with_file(true)
        .with_line_number(true)
        .with_target(true)
        .init();
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let port: u16 = std::env::var("ROUTER_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8090);
    let noetl_base = std::env::var("NOETL_BASE_URL").unwrap_or_else(|_| "http://localhost:8083".to_string());
    let nats_url = std::env::var("NATS_URL").unwrap_or_else(|_| "nats://127.0.0.1:4222".to_string());
    let subject_prefix =
        std::env::var("NATS_UPDATES_SUBJECT_PREFIX").unwrap_or_else(|_| "playbooks.executions.".to_string());

    let noetl = NoetlClient::new(noetl_base.clone());
    let noetl_arc = Arc::new(noetl);
    
    let pg_cfg = config::PostgresqlEnv::from_env()?;
    tracing::info!("connecting to database");
    let pool: sqlx::Pool<sqlx::Postgres> = PgPoolOptions::new()
        .max_connections(5)
        .connect_with(pg_cfg.get_pg_options())
        .await
        .log("PgPoolOptions")?;
    tracing::info!("connected to database");

    let schema: AppSchema = Schema::build(QueryRoot, MutationRoot, async_graphql::EmptySubscription)
        .data(noetl_arc.clone())
        .data(pool.clone())
        .finish();

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any)
        .allow_credentials(true);

    // Public routes (no auth required)
    let public_routes = Router::new()
        .route("/api/auth/login", post(auth::login))
        .route("/api/auth/validate", post(auth::validate_session))
        .route("/api/auth/check-access", post(auth::check_access))
        .with_state(noetl_arc.clone());

    // Protected GraphQL routes (auth required)
    let protected_routes = Router::new()
        .route("/graphql", get(graphiql).post_service(GraphQL::new(schema.clone())))
        .route_layer(middleware::from_fn_with_state(
            noetl_arc.clone(),
            auth::middleware::auth_middleware,
        ))
        .with_state(());

    // Main app with static file serving
    let app = Router::new()
        .route("/", get(serve_index))
        .merge(public_routes)
        .merge(protected_routes)
        .nest_service("/static", ServeDir::new("gateway/static"))
        .layer(cors);

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!(%addr, noetl_base, "starting gateway server http://localhost:{}", port);
    tracing::info!("Auth endpoints: POST /api/auth/login, POST /api/auth/validate, POST /api/auth/check-access");
    tracing::info!("Protected GraphQL: POST /graphql (requires authentication)");
    tracing::info!("Static files: /static/* and / (index.html)");
    
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .log("Failed to bind to address")?;
    axum::serve(listener, app).await.log("Failed to serve app")?;
    Ok(())
}

async fn serve_index() -> Html<String> {
    // Serve index.html from gateway/static/index.html
    let html = tokio::fs::read_to_string("gateway/static/index.html")
        .await
        .unwrap_or_else(|_| "<html><body><h1>Error loading index.html</h1></body></html>".to_string());
    Html(html)
}


async fn graphiql(State(()): State<()>) -> Html<String> {
    let html = playground_source(async_graphql::http::GraphQLPlaygroundConfig::new("/graphql"));
    Html(html)
}
