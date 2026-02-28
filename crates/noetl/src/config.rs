use anyhow::{Context as AnyhowContext, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Context {
    pub server_url: String,
    /// Default runtime mode: local, distributed, or auto
    #[serde(default = "default_runtime")]
    pub runtime: String,
    /// Cached gateway session token for authenticated /noetl/* proxy calls.
    #[serde(default)]
    pub gateway_session_token: Option<String>,
    /// Default Auth0 domain for gateway login command.
    #[serde(default)]
    pub gateway_auth0_domain: Option<String>,
    /// Auth0 application client_id used to construct the browser authorization URL.
    #[serde(default)]
    pub gateway_auth0_client_id: Option<String>,
    /// Auth0 redirect URI — the URL Auth0 sends the token to after login.
    #[serde(default)]
    pub gateway_auth0_redirect_uri: Option<String>,
    /// Auth0 client_secret for password grant (stored locally, used by 'noetl auth login --password').
    #[serde(default)]
    pub gateway_auth0_client_secret: Option<String>,
}

fn default_runtime() -> String {
    "auto".to_string()
}

impl Context {
    pub fn new(server_url: String) -> Self {
        Self {
            server_url,
            runtime: default_runtime(),
            gateway_session_token: None,
            gateway_auth0_domain: None,
            gateway_auth0_client_id: None,
            gateway_auth0_redirect_uri: None,
            gateway_auth0_client_secret: None,
        }
    }
    
    pub fn with_runtime(mut self, runtime: String) -> Self {
        self.runtime = runtime;
        self
    }

    pub fn with_gateway_auth0_domain(mut self, domain: Option<String>) -> Self {
        self.gateway_auth0_domain = domain;
        self
    }

    pub fn with_gateway_auth0_client_id(mut self, client_id: Option<String>) -> Self {
        self.gateway_auth0_client_id = client_id;
        self
    }

    pub fn with_gateway_auth0_redirect_uri(mut self, redirect_uri: Option<String>) -> Self {
        self.gateway_auth0_redirect_uri = redirect_uri;
        self
    }

    pub fn with_gateway_auth0_client_secret(mut self, client_secret: Option<String>) -> Self {
        self.gateway_auth0_client_secret = client_secret;
        self
    }
}

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct Config {
    pub current_context: Option<String>,
    pub contexts: HashMap<String, Context>,
}

impl Config {
    pub fn load() -> Result<Self> {
        let config_path = Self::get_config_path()?;
        if !config_path.exists() {
            return Ok(Config::default());
        }
        let content = fs::read_to_string(&config_path)?;
        let config: Config = serde_yaml::from_str(&content)?;
        Ok(config)
    }

    pub fn save(&self) -> Result<()> {
        let config_path = Self::get_config_path()?;
        if let Some(parent) = config_path.parent() {
            fs::create_dir_all(parent)?;
        }
        let content = serde_yaml::to_string(self)?;
        fs::write(config_path, content)?;
        Ok(())
    }

    fn get_config_path() -> Result<PathBuf> {
        let home = dirs::home_dir().context("Could not find home directory")?;
        Ok(home.join(".noetl").join("config.yaml"))
    }

    pub fn get_current_context(&self) -> Option<(&String, &Context)> {
        self.current_context
            .as_ref()
            .and_then(|name| self.contexts.get(name).map(|ctx| (name, ctx)))
    }
}
