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
mod config;
mod graphql;
mod noetl_client;
mod proxy;
mod result_ext;

use crate::callbacks::CallbackManager;
use crate::config::GatewayConfig;
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
    // Load configuration from file and/or environment variables
    let config = GatewayConfig::load().log("Failed to load gateway configuration")?;

    // Log configuration summary
    tracing::info!("Gateway configuration loaded:");
    tracing::info!("  Server: {}:{}", config.server.bind, config.server.port);
    tracing::info!("  NoETL: {}", config.noetl.base_url);
    tracing::info!("  NATS: {}", config.nats.url);
    tracing::info!("  Auth playbooks:");
    tracing::info!("    login: {}", config.auth_playbooks.login);
    tracing::info!("    validate_session: {}", config.auth_playbooks.validate_session);
    tracing::info!("    check_access: {}", config.auth_playbooks.check_access);
    tracing::info!("    timeout: {}s", config.auth_playbooks.timeout_secs);

    let noetl = NoetlClient::new(config.noetl.base_url.clone());
    let noetl_arc = Arc::new(noetl);

    // Callback manager using NATS pub/sub
    let callback_manager = Arc::new(CallbackManager::new(Some(config.nats.callback_subject_prefix.clone())));

    // Start NATS callback listener
    callbacks::start_nats_listener(&config.nats.url, callback_manager.clone())
        .await
        .log("Failed to start NATS callback listener")?;

    // Combined auth state with configurable playbook paths
    let auth_state = Arc::new(auth::AuthState {
        noetl: noetl_arc.clone(),
        callbacks: callback_manager.clone(),
        playbook_config: config.auth_playbooks.clone(),
    });

    // Proxy state for forwarding requests to NoETL
    let proxy_state = Arc::new(ProxyState::new(config.noetl.base_url.clone()));

    let schema: AppSchema = Schema::build(QueryRoot, MutationRoot, async_graphql::EmptySubscription)
        .data(noetl_arc.clone())
        .data(proxy_state.clone())
        .finish();

    // CORS configuration
    let cors_origins_str = config.cors_origins_string();
    let allowed_origins: Vec<axum::http::HeaderValue> = config.cors.allowed_origins
        .iter()
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
        .allow_credentials(config.cors.allow_credentials);

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

    let addr = SocketAddr::from(([0, 0, 0, 0], config.server.port));
    tracing::info!(%addr, noetl_base = %config.noetl.base_url, "starting gateway server http://localhost:{}", config.server.port);
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
