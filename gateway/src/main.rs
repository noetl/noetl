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
    http::header::{AUTHORIZATION, CONTENT_TYPE},
    http::{HeaderName, Method},
};
use dotenvy::dotenv;
use tower_http::cors::{Any, CorsLayer};
use tracing_subscriber::EnvFilter;

mod auth;
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

    let schema: AppSchema = Schema::build(QueryRoot, MutationRoot, async_graphql::EmptySubscription)
        .data(noetl_arc.clone())
        .finish();

    // CORS configuration for Auth0 + local development
    // Cannot use wildcards with credentials=true, so specify allowed origins
    let allowed_origins = [
        "http://localhost:8080".parse().unwrap(),
        "http://localhost:3000".parse().unwrap(),
    ];
    
    let cors = CorsLayer::new()
        .allow_origin(allowed_origins)
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers([
            CONTENT_TYPE,
            AUTHORIZATION,
            HeaderName::from_static("x-session-id"),
            HeaderName::from_static("x-user-id"),
        ])
        .allow_credentials(true);

    // Public routes (no auth required)
    let public_routes = Router::new()
        .route("/health", get(health_check))
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

    // Main gateway app - pure API routes only
    let app = Router::new()
        .merge(public_routes)
        .merge(protected_routes)
        .layer(cors);

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!(%addr, noetl_base, "starting gateway server http://localhost:{}", port);
    tracing::info!("Auth endpoints: POST /api/auth/login, POST /api/auth/validate, POST /api/auth/check-access");
    tracing::info!("Protected GraphQL: POST /graphql (requires authentication)");
    
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .log("Failed to bind to address")?;
    axum::serve(listener, app).await.log("Failed to serve app")?;
    Ok(())
}

async fn health_check() -> &'static str {
    "ok"
}

async fn graphiql(State(()): State<()>) -> Html<String> {
    let html = playground_source(async_graphql::http::GraphQLPlaygroundConfig::new("/graphql"));
    Html(html)
}
