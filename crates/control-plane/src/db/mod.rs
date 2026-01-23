//! Database module for the NoETL Control Plane server.
//!
//! This module provides database connectivity, models, and queries
//! for PostgreSQL using SQLx.

pub mod models;
pub mod pool;
pub mod queries;

pub use pool::{create_pool, DbPool};
