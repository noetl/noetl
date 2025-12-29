use anyhow::{Context as AnyhowContext, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Context {
    pub server_url: String,
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
