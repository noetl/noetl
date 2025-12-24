use serde::Deserialize;
use sqlx::postgres::PgConnectOptions;

use crate::result_ext::ResultExt;

#[derive(Deserialize, Debug, Clone)]
pub struct PostgresqlEnv {
    host: String,
    port: String,
    user: String,
    database: String,
    password: String,
}

impl PostgresqlEnv {
    pub fn from_env() -> Result<Self, envy::Error> {
        let data = envy::prefixed("POSTGRES_")
            .from_env::<PostgresqlEnv>()
            .log("Provide missing environment database variables")?;
        Ok(data)
    }

    #[inline]
    pub fn get_pg_options(&self) -> PgConnectOptions {
        let url = format!(
            "postgres:///?host={}&port={}&dbname={}&user={}&password={}",
            self.host, self.port, self.database, self.user, self.password,
        );

        let opt = url.parse::<PgConnectOptions>().expect("get_pg_options parse error");
        opt
    }
}

impl Default for PostgresqlEnv {
    fn default() -> Self {
        serde_json::from_str::<PostgresqlEnv>("{}").expect("unable to initialize default values")
    }
}
