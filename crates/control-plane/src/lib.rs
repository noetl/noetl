//! NoETL Control Plane Library
//!
//! This crate provides the control plane server for NoETL, handling:
//!
//! - **Workflow Orchestration**: Execute playbooks and manage workflow state
//! - **Catalog Management**: Register and retrieve playbooks, tools, and resources
//! - **Credential Management**: Securely store and retrieve encrypted credentials
//! - **Event Processing**: Handle worker events and drive workflow execution
//! - **Execution Management**: Track and manage playbook executions
//!
//! ## Architecture
//!
//! The control plane follows an event-sourcing architecture where all state
//! is derived from events stored in PostgreSQL. NATS JetStream is used for
//! command notifications to workers.
//!
//! ## Modules
//!
//! - [`config`]: Configuration loading from environment variables
//! - [`db`]: Database connectivity and models
//! - [`error`]: Custom error types with Axum integration
//! - [`handlers`]: HTTP route handlers
//! - [`state`]: Shared application state
//!
//! ## Example
//!
//! ```ignore
//! use noetl_control_plane::{
//!     config::{AppConfig, DatabaseConfig},
//!     db::create_pool,
//!     state::AppState,
//! };
//!
//! #[tokio::main]
//! async fn main() -> anyhow::Result<()> {
//!     let app_config = AppConfig::from_env()?;
//!     let db_config = DatabaseConfig::from_env()?;
//!     let db_pool = create_pool(&db_config).await?;
//!     let state = AppState::new(db_pool, app_config, None);
//!     // ... build and run server
//!     Ok(())
//! }
//! ```

pub mod config;
pub mod crypto;
pub mod db;
pub mod engine;
pub mod error;
pub mod handlers;
pub mod nats;
pub mod playbook;
pub mod result_ext;
pub mod services;
pub mod state;
pub mod template;

pub use error::{AppError, AppResult};
pub use result_ext::ResultExt;
