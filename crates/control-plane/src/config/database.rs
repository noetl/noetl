//! Database configuration for PostgreSQL connection.

use serde::Deserialize;
use sqlx::postgres::PgConnectOptions;

/// Database configuration loaded from environment variables.
///
/// Environment variables are prefixed with `POSTGRES_`:
/// - `POSTGRES_HOST`: Database host (default: "localhost")
/// - `POSTGRES_PORT`: Database port (default: "5432")
/// - `POSTGRES_USER`: Database user
/// - `POSTGRES_PASSWORD`: Database password
/// - `POSTGRES_DATABASE`: Database name (default: "noetl")
///
/// Additional configuration:
/// - `NOETL_SCHEMA`: Database schema (default: "noetl")
/// - `DATABASE_URL`: Full connection URL (overrides individual settings)
#[derive(Debug, Clone, Deserialize)]
pub struct DatabaseConfig {
    /// Database host
    #[serde(default = "default_host")]
    pub host: String,

    /// Database port
    #[serde(default = "default_port")]
    pub port: String,

    /// Database user
    #[serde(default = "default_user")]
    pub user: String,

    /// Database password
    #[serde(default)]
    pub password: String,

    /// Database name
    #[serde(default = "default_database")]
    pub database: String,

    /// Maximum connections in the pool
    #[serde(default = "default_max_connections")]
    pub max_connections: u32,

    /// Minimum connections in the pool
    #[serde(default = "default_min_connections")]
    pub min_connections: u32,

    /// Connection acquire timeout in seconds
    #[serde(default = "default_acquire_timeout")]
    pub acquire_timeout: u64,
}

fn default_host() -> String {
    "localhost".to_string()
}

fn default_port() -> String {
    "5432".to_string()
}

fn default_user() -> String {
    "noetl".to_string()
}

fn default_database() -> String {
    "noetl".to_string()
}

fn default_max_connections() -> u32 {
    10
}

fn default_min_connections() -> u32 {
    1
}

fn default_acquire_timeout() -> u64 {
    30
}

/// Schema configuration loaded separately.
#[derive(Debug, Clone, Deserialize)]
#[allow(dead_code)]
pub struct SchemaConfig {
    /// Database schema
    #[serde(default = "default_schema")]
    pub schema: String,
}

fn default_schema() -> String {
    "noetl".to_string()
}

impl DatabaseConfig {
    /// Load configuration from environment variables.
    ///
    /// Environment variables are prefixed with `POSTGRES_`.
    pub fn from_env() -> Result<Self, envy::Error> {
        envy::prefixed("POSTGRES_").from_env::<DatabaseConfig>()
    }

    /// Get PostgreSQL connection options.
    pub fn connect_options(&self) -> PgConnectOptions {
        let port: u16 = self.port.parse().unwrap_or(5432);

        PgConnectOptions::new()
            .host(&self.host)
            .port(port)
            .username(&self.user)
            .password(&self.password)
            .database(&self.database)
    }

    /// Get the connection URL string.
    pub fn connection_url(&self) -> String {
        format!(
            "postgres://{}:{}@{}:{}/{}",
            self.user, self.password, self.host, self.port, self.database
        )
    }
}

impl SchemaConfig {
    /// Load schema configuration from environment variables.
    ///
    /// Environment variables are prefixed with `NOETL_`.
    #[allow(dead_code)]
    pub fn from_env() -> Result<Self, envy::Error> {
        envy::prefixed("NOETL_").from_env::<SchemaConfig>()
    }
}

impl Default for DatabaseConfig {
    fn default() -> Self {
        Self {
            host: default_host(),
            port: default_port(),
            user: default_user(),
            password: String::new(),
            database: default_database(),
            max_connections: default_max_connections(),
            min_connections: default_min_connections(),
            acquire_timeout: default_acquire_timeout(),
        }
    }
}

impl Default for SchemaConfig {
    fn default() -> Self {
        Self {
            schema: default_schema(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = DatabaseConfig::default();
        assert_eq!(config.host, "localhost");
        assert_eq!(config.port, "5432");
        assert_eq!(config.database, "noetl");
    }

    #[test]
    fn test_connection_url() {
        let mut config = DatabaseConfig::default();
        config.password = "secret".to_string();
        assert_eq!(
            config.connection_url(),
            "postgres://noetl:secret@localhost:5432/noetl"
        );
    }
}
