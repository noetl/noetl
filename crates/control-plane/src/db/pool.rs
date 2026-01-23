//! Database connection pool management.

use crate::config::DatabaseConfig;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::time::Duration;

/// Type alias for the PostgreSQL connection pool.
pub type DbPool = PgPool;

/// Create a new database connection pool.
///
/// # Arguments
///
/// * `config` - Database configuration
///
/// # Returns
///
/// A configured PostgreSQL connection pool.
///
/// # Errors
///
/// Returns an error if the connection pool cannot be created.
pub async fn create_pool(config: &DatabaseConfig) -> Result<DbPool, sqlx::Error> {
    let pool = PgPoolOptions::new()
        .max_connections(config.max_connections)
        .min_connections(config.min_connections)
        .acquire_timeout(Duration::from_secs(config.acquire_timeout))
        .connect_with(config.connect_options())
        .await?;

    tracing::info!(
        host = %config.host,
        port = %config.port,
        database = %config.database,
        max_connections = config.max_connections,
        "Database connection pool created"
    );

    Ok(pool)
}

/// Check if the database connection is healthy.
///
/// # Arguments
///
/// * `pool` - Database connection pool
///
/// # Returns
///
/// `true` if the database is reachable, `false` otherwise.
pub async fn health_check(pool: &DbPool) -> bool {
    sqlx::query("SELECT 1").execute(pool).await.is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pool_type_alias() {
        // Type alias should be PgPool
        fn _assert_type(_: DbPool) {}
    }
}
