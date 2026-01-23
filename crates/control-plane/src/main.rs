//! NoETL Control Plane Server
//!
//! An async Rust server that provides the control plane API for NoETL,
//! handling workflow orchestration, catalog management, and event processing.

use axum::{
    routing::{delete, get, post},
    Router,
};
use std::net::SocketAddr;
use tokio::net::TcpListener;
use tower_http::cors::{Any, CorsLayer};
use tower_http::trace::TraceLayer;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use noetl_control_plane::{
    config::{AppConfig, DatabaseConfig},
    db::{create_pool, DbPool},
    handlers,
    services::{
        CatalogService, CredentialService, ExecutionService, KeychainService, RuntimeService,
    },
    state::AppState,
};

/// Default encryption key for development (should be overridden in production).
const DEFAULT_ENCRYPTION_KEY: &str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";

/// Initialize tracing/logging.
fn init_tracing() {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,noetl_control_plane=debug,tower_http=debug".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();
}

/// Build the application router with all routes.
fn build_router(
    state: AppState,
    db_pool: DbPool,
    catalog_service: CatalogService,
    credential_service: CredentialService,
    keychain_service: KeychainService,
    execution_service: ExecutionService,
    runtime_service: RuntimeService,
) -> Router {
    // CORS configuration - allow all origins for development
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    // Health check routes (no auth required)
    let health_routes = Router::new()
        .route("/health", get(handlers::health_check))
        .route("/api/health", get(handlers::api_health))
        .with_state(state.clone());

    // Catalog routes
    let catalog_routes = Router::new()
        .route("/api/catalog/register", post(handlers::catalog::register))
        .route("/api/catalog/list", post(handlers::catalog::list))
        .route(
            "/api/catalog/resource",
            post(handlers::catalog::get_resource),
        )
        .with_state(catalog_service);

    // Credential routes
    let credential_routes = Router::new()
        .route(
            "/api/credentials",
            post(handlers::credentials::create_or_update),
        )
        .route("/api/credentials", get(handlers::credentials::list))
        .route(
            "/api/credentials/:identifier",
            get(handlers::credentials::get),
        )
        .route(
            "/api/credentials/:identifier",
            delete(handlers::credentials::delete),
        )
        .with_state(credential_service);

    // Keychain routes
    let keychain_routes = Router::new()
        .route(
            "/api/keychain/:catalog_id/:keychain_name",
            get(handlers::keychain::get),
        )
        .route(
            "/api/keychain/:catalog_id/:keychain_name",
            post(handlers::keychain::set),
        )
        .route(
            "/api/keychain/:catalog_id/:keychain_name",
            delete(handlers::keychain::delete),
        )
        .route(
            "/api/keychain/catalog/:catalog_id",
            get(handlers::keychain::list_by_catalog),
        )
        .with_state(keychain_service);

    // Execution routes (v2 event-driven)
    let execution_routes = Router::new()
        .route("/api/execute", post(handlers::execute))
        .route("/api/events", post(handlers::handle_event))
        .route("/api/commands/:event_id", get(handlers::get_command))
        .with_state(state.clone());

    // Execution management routes
    let executions_routes = Router::new()
        .route("/api/executions", get(handlers::executions::list))
        .route(
            "/api/executions/:execution_id",
            get(handlers::executions::get),
        )
        .route(
            "/api/executions/:execution_id/status",
            get(handlers::executions::get_status),
        )
        .route(
            "/api/executions/:execution_id/cancel",
            post(handlers::executions::cancel),
        )
        .route(
            "/api/executions/:execution_id/cancellation-check",
            get(handlers::executions::cancellation_check),
        )
        .route(
            "/api/executions/:execution_id/finalize",
            post(handlers::executions::finalize),
        )
        .with_state(execution_service);

    // Variable routes (transient table)
    let variable_routes = Router::new()
        .route("/api/vars/:execution_id", get(handlers::variables::list))
        .route("/api/vars/:execution_id", post(handlers::variables::set))
        .route(
            "/api/vars/:execution_id",
            delete(handlers::variables::cleanup),
        )
        .route(
            "/api/vars/:execution_id/:var_name",
            get(handlers::variables::get),
        )
        .route(
            "/api/vars/:execution_id/:var_name",
            delete(handlers::variables::delete_var),
        )
        .with_state(db_pool.clone());

    // Runtime/Worker pool routes
    let runtime_routes = Router::new()
        .route(
            "/api/worker/pool/register",
            post(handlers::runtime::register_pool),
        )
        .route(
            "/api/worker/pool/deregister",
            delete(handlers::runtime::deregister_pool),
        )
        .route(
            "/api/worker/pool/heartbeat",
            post(handlers::runtime::heartbeat),
        )
        .route("/api/worker/pools", get(handlers::runtime::list_pools))
        .route("/api/runtimes", get(handlers::runtime::list_all))
        .with_state(runtime_service);

    // Database routes
    let database_routes = Router::new()
        .route(
            "/api/postgres/execute",
            post(handlers::database::execute_postgres),
        )
        .route("/api/db/init", post(handlers::database::init_database))
        .route(
            "/api/db/validate",
            get(handlers::database::validate_database),
        )
        .with_state(db_pool.clone());

    // System monitoring routes
    let system_routes = Router::new()
        .route("/api/status", get(handlers::system::get_status))
        .route("/api/threads", get(handlers::system::get_threads))
        .route(
            "/api/profiler/status",
            get(handlers::system::get_profiler_status),
        )
        .route(
            "/api/profiler/memory/start",
            post(handlers::system::start_memory_profiler),
        )
        .route(
            "/api/profiler/memory/stop",
            post(handlers::system::stop_memory_profiler),
        )
        .with_state(state);

    // Dashboard routes
    let dashboard_routes = Router::new()
        .route("/api/dashboard/stats", get(handlers::dashboard::get_stats))
        .route(
            "/api/dashboard/widgets",
            get(handlers::dashboard::get_widgets),
        )
        .with_state(db_pool);

    // Combine all routes
    Router::new()
        .merge(health_routes)
        .merge(catalog_routes)
        .merge(credential_routes)
        .merge(keychain_routes)
        .merge(execution_routes)
        .merge(executions_routes)
        .merge(variable_routes)
        .merge(runtime_routes)
        .merge(database_routes)
        .merge(system_routes)
        .merge(dashboard_routes)
        .layer(TraceLayer::new_for_http())
        .layer(cors)
}

/// Connect to NATS if configured.
async fn connect_nats(config: &AppConfig) -> Option<async_nats::Client> {
    if let Some(ref nats_url) = config.nats_url {
        match async_nats::connect(nats_url).await {
            Ok(client) => {
                tracing::info!(url = %nats_url, "Connected to NATS");
                Some(client)
            }
            Err(e) => {
                tracing::warn!(error = %e, url = %nats_url, "Failed to connect to NATS, continuing without it");
                None
            }
        }
    } else {
        tracing::info!("NATS not configured, running without messaging");
        None
    }
}

/// Get encryption key from environment or use default.
fn get_encryption_key() -> String {
    std::env::var("NOETL_ENCRYPTION_KEY").unwrap_or_else(|_| {
        tracing::warn!("NOETL_ENCRYPTION_KEY not set, using default (not secure for production)");
        DEFAULT_ENCRYPTION_KEY.to_string()
    })
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Load environment variables from .env file if present
    dotenvy::dotenv().ok();

    // Initialize tracing
    init_tracing();

    tracing::info!(
        version = env!("CARGO_PKG_VERSION"),
        "Starting NoETL Control Plane"
    );

    // Load configuration
    let app_config = AppConfig::from_env().unwrap_or_else(|e| {
        tracing::warn!(error = %e, "Failed to load app config, using defaults");
        AppConfig::default()
    });

    let db_config = DatabaseConfig::from_env().unwrap_or_else(|e| {
        tracing::warn!(error = %e, "Failed to load database config, using defaults");
        DatabaseConfig::default()
    });

    tracing::info!(
        host = %app_config.host,
        port = app_config.port,
        debug = app_config.debug,
        "Configuration loaded"
    );

    // Create database connection pool
    let db_pool = create_pool(&db_config).await?;

    // Connect to NATS (optional)
    let nats_client = connect_nats(&app_config).await;

    // Get encryption key
    let encryption_key = get_encryption_key();

    // Create services
    let catalog_service = CatalogService::new(db_pool.clone());
    let credential_service = CredentialService::new(db_pool.clone(), &encryption_key)?;
    let keychain_service = KeychainService::new(db_pool.clone(), &encryption_key)?;
    let execution_service = ExecutionService::new(db_pool.clone());
    let runtime_service = RuntimeService::new(db_pool.clone());

    // Create application state
    let state = AppState::new(db_pool.clone(), app_config.clone(), nats_client);

    // Build the router
    let app = build_router(
        state,
        db_pool,
        catalog_service,
        credential_service,
        keychain_service,
        execution_service,
        runtime_service,
    );

    // Bind to address
    let addr: SocketAddr = app_config.bind_address().parse()?;
    let listener = TcpListener::bind(addr).await?;

    tracing::info!(address = %addr, "Server listening");

    // Run the server with graceful shutdown
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    tracing::info!("Server shutdown complete");

    Ok(())
}

/// Wait for shutdown signal (Ctrl+C or SIGTERM).
async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("Failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("Failed to install SIGTERM handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {
            tracing::info!("Received Ctrl+C, starting graceful shutdown");
        }
        _ = terminate => {
            tracing::info!("Received SIGTERM, starting graceful shutdown");
        }
    }
}
