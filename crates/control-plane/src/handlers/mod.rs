//! HTTP handlers for the NoETL Control Plane API.
//!
//! This module contains all route handlers organized by domain.

pub mod catalog;
pub mod credentials;
pub mod dashboard;
pub mod database;
pub mod events;
pub mod execute;
pub mod executions;
pub mod health;
pub mod keychain;
pub mod runtime;
pub mod system;
pub mod variables;

pub use events::{get_command, handle_event};
pub use execute::execute;
pub use health::{api_health, health_check};
