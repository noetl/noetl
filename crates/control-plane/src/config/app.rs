//! Application configuration for the NoETL Control Plane server.

use serde::Deserialize;

/// Application configuration loaded from environment variables.
///
/// Environment variables are prefixed with `NOETL_`:
/// - `NOETL_HOST`: Server bind address (default: "0.0.0.0")
/// - `NOETL_PORT`: Server port (default: 8082)
/// - `NOETL_WORKERS`: Number of worker threads (optional)
/// - `NOETL_DEBUG`: Enable debug mode (default: false)
/// - `NOETL_SERVER_NAME`: Server name for identification
#[derive(Debug, Clone, Deserialize)]
pub struct AppConfig {
    /// Server bind address
    #[serde(default = "default_host")]
    pub host: String,

    /// Server port
    #[serde(default = "default_port")]
    pub port: u16,

    /// Number of worker threads (optional, defaults to CPU count)
    pub workers: Option<usize>,

    /// Enable debug mode
    #[serde(default)]
    pub debug: bool,

    /// Server name for identification
    #[serde(default = "default_server_name")]
    pub server_name: String,

    /// NATS URL (optional)
    #[serde(default)]
    pub nats_url: Option<String>,

    /// Enable GCP token API endpoint
    #[serde(default = "default_true")]
    pub enable_gcp_token_api: bool,

    /// Disable metrics endpoint
    #[serde(default)]
    pub disable_metrics: bool,

    /// Auto recreate runtime if missing
    #[serde(default = "default_true")]
    pub auto_recreate_runtime: bool,

    /// Runtime sweep interval in seconds
    #[serde(default = "default_sweep_interval")]
    pub runtime_sweep_interval: u64,

    /// Runtime offline threshold in seconds
    #[serde(default = "default_offline_seconds")]
    pub runtime_offline_seconds: u64,
}

fn default_host() -> String {
    "0.0.0.0".to_string()
}

fn default_port() -> u16 {
    8082
}

fn default_server_name() -> String {
    "noetl-control-plane".to_string()
}

fn default_true() -> bool {
    true
}

fn default_sweep_interval() -> u64 {
    30
}

fn default_offline_seconds() -> u64 {
    60
}

impl AppConfig {
    /// Load configuration from environment variables.
    ///
    /// Environment variables are prefixed with `NOETL_`.
    pub fn from_env() -> Result<Self, envy::Error> {
        envy::prefixed("NOETL_").from_env::<AppConfig>()
    }

    /// Get the server bind address as a string suitable for `TcpListener::bind`.
    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            host: default_host(),
            port: default_port(),
            workers: None,
            debug: false,
            server_name: default_server_name(),
            nats_url: None,
            enable_gcp_token_api: true,
            disable_metrics: false,
            auto_recreate_runtime: true,
            runtime_sweep_interval: default_sweep_interval(),
            runtime_offline_seconds: default_offline_seconds(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = AppConfig::default();
        assert_eq!(config.host, "0.0.0.0");
        assert_eq!(config.port, 8082);
        assert!(!config.debug);
    }

    #[test]
    fn test_bind_address() {
        let config = AppConfig::default();
        assert_eq!(config.bind_address(), "0.0.0.0:8082");
    }
}
