//! Gateway configuration module.
//!
//! Supports loading configuration from:
//! 1. Config file (TOML, JSON, or YAML)
//! 2. Environment variables (with prefix)
//!
//! Environment variables take precedence over config file values.

use serde::{Deserialize, Serialize};
use std::path::Path;

/// Main gateway configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct GatewayConfig {
    /// Server configuration
    pub server: ServerConfig,
    /// NoETL backend configuration
    pub noetl: NoetlConfig,
    /// NATS messaging configuration
    pub nats: NatsConfig,
    /// CORS configuration
    pub cors: CorsConfig,
    /// Authentication playbook paths
    pub auth_playbooks: AuthPlaybooksConfig,
    /// Transport configuration (SSE/WebSocket)
    pub transport: TransportConfig,
}

/// Server configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ServerConfig {
    /// Server port (default: 8090)
    pub port: u16,
    /// Bind address (default: "0.0.0.0")
    pub bind: String,
    /// Public URL for external access
    pub public_url: Option<String>,
}

/// NoETL backend configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct NoetlConfig {
    /// NoETL base URL (default: "http://localhost:8082")
    pub base_url: String,
    /// Request timeout in seconds (default: 120)
    pub timeout_secs: u64,
}

/// NATS configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct NatsConfig {
    /// NATS server URL (default: "nats://127.0.0.1:4222")
    pub url: String,
    /// Username for NATS authentication
    pub username: Option<String>,
    /// Password for NATS authentication
    pub password: Option<String>,
    /// Subject prefix for execution updates (default: "playbooks.executions.")
    pub updates_subject_prefix: String,
    /// Subject prefix for callbacks (default: "noetl.callbacks")
    pub callback_subject_prefix: String,
    /// K/V bucket name for session cache (default: "sessions")
    pub session_bucket: String,
    /// Session cache TTL in seconds (default: 300 = 5 minutes)
    pub session_cache_ttl_secs: u64,
    /// K/V bucket name for pending requests (default: "requests")
    pub request_bucket: String,
    /// Request TTL in seconds (default: 1800 = 30 minutes)
    pub request_ttl_secs: u64,
}

/// Transport configuration for SSE/WebSocket
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct TransportConfig {
    /// Enable SSE transport (default: true)
    pub sse_enabled: bool,
    /// Enable WebSocket transport (default: false, Phase 2)
    pub ws_enabled: bool,
    /// Heartbeat interval in seconds (default: 30)
    pub heartbeat_interval_secs: u64,
    /// Connection idle timeout in seconds (default: 300)
    pub connection_timeout_secs: u64,
}

/// CORS configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct CorsConfig {
    /// Allowed origins (comma-separated or array)
    pub allowed_origins: Vec<String>,
    /// Allow credentials (default: true)
    pub allow_credentials: bool,
}

/// Authentication playbook paths configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AuthPlaybooksConfig {
    /// Login playbook path (default: "api_integration/auth0/auth0_login")
    pub login: String,
    /// Session validation playbook path (default: "api_integration/auth0/auth0_validate_session")
    pub validate_session: String,
    /// Access check playbook path (default: "api_integration/auth0/check_playbook_access")
    pub check_access: String,
    /// Playbook execution timeout in seconds (default: 60)
    pub timeout_secs: u64,
}

// Default implementations

impl Default for GatewayConfig {
    fn default() -> Self {
        Self {
            server: ServerConfig::default(),
            noetl: NoetlConfig::default(),
            nats: NatsConfig::default(),
            cors: CorsConfig::default(),
            auth_playbooks: AuthPlaybooksConfig::default(),
            transport: TransportConfig::default(),
        }
    }
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            port: 8090,
            bind: "0.0.0.0".to_string(),
            public_url: None,
        }
    }
}

impl Default for NoetlConfig {
    fn default() -> Self {
        Self {
            base_url: "http://localhost:8082".to_string(),
            timeout_secs: 120,
        }
    }
}

impl Default for NatsConfig {
    fn default() -> Self {
        Self {
            url: "nats://127.0.0.1:4222".to_string(),
            username: None,
            password: None,
            updates_subject_prefix: "playbooks.executions.".to_string(),
            callback_subject_prefix: "noetl.callbacks".to_string(),
            session_bucket: "sessions".to_string(),
            session_cache_ttl_secs: 300, // 5 minutes
            request_bucket: "requests".to_string(),
            request_ttl_secs: 1800, // 30 minutes
        }
    }
}

impl Default for TransportConfig {
    fn default() -> Self {
        Self {
            sse_enabled: true,
            ws_enabled: false, // Phase 2
            heartbeat_interval_secs: 30,
            connection_timeout_secs: 300, // 5 minutes
        }
    }
}

impl Default for CorsConfig {
    fn default() -> Self {
        Self {
            allowed_origins: vec![
                "http://localhost:8080".to_string(),
                "http://localhost:8090".to_string(),
                "http://localhost:3000".to_string(),
            ],
            allow_credentials: true,
        }
    }
}

impl Default for AuthPlaybooksConfig {
    fn default() -> Self {
        Self {
            login: "api_integration/auth0/auth0_login".to_string(),
            validate_session: "api_integration/auth0/auth0_validate_session".to_string(),
            check_access: "api_integration/auth0/check_playbook_access".to_string(),
            timeout_secs: 60,
        }
    }
}

impl GatewayConfig {
    /// Load configuration from file and environment variables.
    /// Environment variables override file values.
    pub fn load() -> anyhow::Result<Self> {
        // Start with defaults
        let mut config = Self::default();

        // Try to load from config file if specified
        if let Ok(config_path) = std::env::var("GATEWAY_CONFIG") {
            config = Self::from_file(&config_path)?;
            tracing::info!("Loaded configuration from: {}", config_path);
        }

        // Override with environment variables
        config.apply_env_overrides();

        Ok(config)
    }

    /// Load configuration from a file (supports TOML, JSON, YAML)
    pub fn from_file<P: AsRef<Path>>(path: P) -> anyhow::Result<Self> {
        let path = path.as_ref();
        let content = std::fs::read_to_string(path)?;

        let extension = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        let config: GatewayConfig = match extension {
            "toml" => toml::from_str(&content)?,
            "json" => serde_json::from_str(&content)?,
            "yaml" | "yml" => serde_yaml::from_str(&content)?,
            _ => {
                // Try to detect format
                if content.trim().starts_with('{') {
                    serde_json::from_str(&content)?
                } else if content.contains("---") || content.contains(": ") {
                    serde_yaml::from_str(&content)?
                } else {
                    toml::from_str(&content)?
                }
            }
        };

        Ok(config)
    }

    /// Apply environment variable overrides
    fn apply_env_overrides(&mut self) {
        // Server config
        if let Ok(val) = std::env::var("ROUTER_PORT").or_else(|_| std::env::var("GATEWAY_PORT")) {
            if let Ok(port) = val.parse() {
                self.server.port = port;
            }
        }
        if let Ok(val) = std::env::var("GATEWAY_BIND") {
            self.server.bind = val;
        }
        if let Ok(val) = std::env::var("GATEWAY_PUBLIC_URL") {
            self.server.public_url = Some(val);
        }

        // NoETL config
        if let Ok(val) = std::env::var("NOETL_BASE_URL") {
            self.noetl.base_url = val;
        }
        if let Ok(val) = std::env::var("NOETL_TIMEOUT_SECS") {
            if let Ok(secs) = val.parse() {
                self.noetl.timeout_secs = secs;
            }
        }

        // NATS config
        if let Ok(val) = std::env::var("NATS_URL") {
            self.nats.url = val;
        }
        if let Ok(val) = std::env::var("NATS_USERNAME") {
            self.nats.username = Some(val);
        }
        if let Ok(val) = std::env::var("NATS_PASSWORD") {
            self.nats.password = Some(val);
        }
        if let Ok(val) = std::env::var("NATS_UPDATES_SUBJECT_PREFIX") {
            self.nats.updates_subject_prefix = val;
        }
        if let Ok(val) = std::env::var("NATS_CALLBACK_SUBJECT_PREFIX") {
            self.nats.callback_subject_prefix = val;
        }
        if let Ok(val) = std::env::var("NATS_SESSION_BUCKET") {
            self.nats.session_bucket = val;
        }
        if let Ok(val) = std::env::var("NATS_SESSION_CACHE_TTL_SECS") {
            if let Ok(secs) = val.parse() {
                self.nats.session_cache_ttl_secs = secs;
            }
        }
        if let Ok(val) = std::env::var("NATS_REQUEST_BUCKET") {
            self.nats.request_bucket = val;
        }
        if let Ok(val) = std::env::var("NATS_REQUEST_TTL_SECS") {
            if let Ok(secs) = val.parse() {
                self.nats.request_ttl_secs = secs;
            }
        }

        // Transport config
        if let Ok(val) = std::env::var("GATEWAY_SSE_ENABLED") {
            self.transport.sse_enabled = val.parse().unwrap_or(true);
        }
        if let Ok(val) = std::env::var("GATEWAY_WS_ENABLED") {
            self.transport.ws_enabled = val.parse().unwrap_or(false);
        }
        if let Ok(val) = std::env::var("GATEWAY_HEARTBEAT_INTERVAL_SECS") {
            if let Ok(secs) = val.parse() {
                self.transport.heartbeat_interval_secs = secs;
            }
        }
        if let Ok(val) = std::env::var("GATEWAY_CONNECTION_TIMEOUT_SECS") {
            if let Ok(secs) = val.parse() {
                self.transport.connection_timeout_secs = secs;
            }
        }

        // CORS config
        if let Ok(val) = std::env::var("CORS_ALLOWED_ORIGINS") {
            self.cors.allowed_origins = val.split(',').map(|s| s.trim().to_string()).collect();
        }
        if let Ok(val) = std::env::var("CORS_ALLOW_CREDENTIALS") {
            self.cors.allow_credentials = val.parse().unwrap_or(true);
        }

        // Auth playbooks config
        if let Ok(val) = std::env::var("AUTH_PLAYBOOK_LOGIN") {
            self.auth_playbooks.login = val;
        }
        if let Ok(val) = std::env::var("AUTH_PLAYBOOK_VALIDATE_SESSION") {
            self.auth_playbooks.validate_session = val;
        }
        if let Ok(val) = std::env::var("AUTH_PLAYBOOK_CHECK_ACCESS") {
            self.auth_playbooks.check_access = val;
        }
        if let Ok(val) = std::env::var("AUTH_PLAYBOOK_TIMEOUT_SECS") {
            if let Ok(secs) = val.parse() {
                self.auth_playbooks.timeout_secs = secs;
            }
        }
    }

    /// Get CORS allowed origins as comma-separated string
    pub fn cors_origins_string(&self) -> String {
        self.cors.allowed_origins.join(",")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = GatewayConfig::default();
        assert_eq!(config.server.port, 8090);
        assert_eq!(config.noetl.base_url, "http://localhost:8082");
        assert_eq!(config.auth_playbooks.login, "api_integration/auth0/auth0_login");
    }

    #[test]
    fn test_toml_parsing() {
        let toml_content = r#"
[server]
port = 9090
bind = "127.0.0.1"

[noetl]
base_url = "http://noetl:8082"

[auth_playbooks]
login = "custom/login"
"#;
        let config: GatewayConfig = toml::from_str(toml_content).unwrap();
        assert_eq!(config.server.port, 9090);
        assert_eq!(config.noetl.base_url, "http://noetl:8082");
        assert_eq!(config.auth_playbooks.login, "custom/login");
        // Defaults should still be applied for missing fields
        assert_eq!(config.auth_playbooks.validate_session, "api_integration/auth0/auth0_validate_session");
    }
}
