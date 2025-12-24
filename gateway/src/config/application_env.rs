use serde::Deserialize;

use crate::result_ext::ResultExt;

#[derive(Deserialize, Debug, Clone)]
pub struct ApplicationEnv {
    #[serde(rename = "bind")]
    pub bind_address: Option<String>,
    // pub url: String,
    pub port: u16,
    pub workers: Option<usize>,
}

fn default_local_development_mode() -> String {
    "false".to_string()
}

impl ApplicationEnv {
    fn prefix() -> String {
        let prefix = "APP_";

        prefix.to_string()
    }

    pub fn from_env() -> Result<Self, envy::Error> {
        let env = envy::prefixed(Self::prefix())
            .from_env::<ApplicationEnv>()
            .log("Provide missing application environment variables")?;
        Ok(env)
    }
}
