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
    routing::{get, post, put, delete, patch},
    http::header::{AUTHORIZATION, CONTENT_TYPE},
    http::{HeaderName, Method},
};
use dotenvy::dotenv;
use tower_http::cors::{AllowOrigin, CorsLayer};
use tracing_subscriber::EnvFilter;

mod auth;
mod callbacks;
mod graphql;
mod noetl_client;
mod proxy;
mod result_ext;

use crate::callbacks::CallbackManager;
use crate::graphql::schema::{AppSchema, MutationRoot, QueryRoot};
use crate::noetl_client::NoetlClient;
use crate::proxy::ProxyState;
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

    // Callback manager using NATS pub/sub
    let callback_subject_prefix = std::env::var("NATS_CALLBACK_SUBJECT_PREFIX")
        .unwrap_or_else(|_| "noetl.callbacks".to_string());
    let callback_manager = Arc::new(CallbackManager::new(Some(callback_subject_prefix.clone())));

    // Start NATS callback listener
    callbacks::start_nats_listener(&nats_url, callback_manager.clone())
        .await
        .log("Failed to start NATS callback listener")?;

    // Combined auth state
    let auth_state = Arc::new(auth::AuthState {
        noetl: noetl_arc.clone(),
        callbacks: callback_manager.clone(),
    });

    // Proxy state for forwarding requests to NoETL
    let proxy_state = Arc::new(ProxyState::new(noetl_base.clone()));

    let schema: AppSchema = Schema::build(QueryRoot, MutationRoot, async_graphql::EmptySubscription)
        .data(noetl_arc.clone())
        .data(proxy_state.clone())
        .finish();

    // CORS configuration - read allowed origins from env var (comma-separated)
    // Example: CORS_ALLOWED_ORIGINS=http://localhost:8090,http://gateway.mestumre.dev
    let cors_origins_str = std::env::var("CORS_ALLOWED_ORIGINS")
        .unwrap_or_else(|_| "http://localhost:8080,http://localhost:8090,http://localhost:3000".to_string());

    let allowed_origins: Vec<axum::http::HeaderValue> = cors_origins_str
        .split(',')
        .filter_map(|s| s.trim().parse().ok())
        .collect();

    tracing::info!("CORS allowed origins: {:?}", cors_origins_str);

    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::list(allowed_origins))
        .allow_methods([Method::GET, Method::POST, Method::PUT, Method::DELETE, Method::PATCH, Method::OPTIONS])
        .allow_headers([
            CONTENT_TYPE,
            AUTHORIZATION,
            HeaderName::from_static("x-session-id"),
            HeaderName::from_static("x-user-id"),
            HeaderName::from_static("x-request-id"),
        ])
        .allow_credentials(true);

    // Public routes (no auth required)
    let public_routes = Router::new()
        .route("/health", get(health_check))
        .route("/api/auth/login", post(auth::login))
        .route("/api/auth/validate", post(auth::validate_session))
        .route("/api/auth/check-access", post(auth::check_access))
        .with_state(auth_state.clone());

    // Protected GraphQL routes (auth required)
    let graphql_routes = Router::new()
        .route("/graphql", get(graphiql).post_service(GraphQL::new(schema.clone())))
        .route_layer(middleware::from_fn_with_state(
            auth_state.clone(),
            auth::middleware::auth_middleware,
        ))
        .with_state(());

    // Protected proxy routes - forward authenticated requests to NoETL server
    // Route: /noetl/{path} -> NoETL /api/{path}
    let proxy_routes = Router::new()
        .route("/noetl/{*path}", get(proxy::proxy_get))
        .route("/noetl/{*path}", post(proxy::proxy_post))
        .route("/noetl/{*path}", put(proxy::proxy_put))
        .route("/noetl/{*path}", delete(proxy::proxy_delete))
        .route("/noetl/{*path}", patch(proxy::proxy_patch))
        .route_layer(middleware::from_fn_with_state(
            auth_state.clone(),
            auth::middleware::auth_middleware,
        ))
        .with_state(proxy_state);

    // Main gateway app
    let app = Router::new()
        .merge(public_routes)
        .merge(graphql_routes)
        .merge(proxy_routes)
        .layer(cors);

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!(%addr, noetl_base, "starting gateway server http://localhost:{}", port);
    tracing::info!("Auth endpoints: POST /api/auth/login, POST /api/auth/validate, POST /api/auth/check-access");
    tracing::info!("Protected GraphQL: POST /graphql (requires authentication)");
    tracing::info!("Protected Proxy: /noetl/* -> NoETL /api/* (requires authentication)");

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
