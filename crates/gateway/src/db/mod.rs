use sqlx::PgPool;

use serde::{Deserialize, Serialize};

use chrono::{DateTime, Utc};
use uuid::Uuid;

// Example table schema - commented out for now, gateway is for API only
// CREATE TABLE public.amadeus_ai_events (
// 	id serial4 NOT NULL,
// 	execution_id varchar(64) NULL,
// 	event_type varchar(32) NULL,
// 	api_call_type varchar(32) NULL,
// 	input_data jsonb NULL,
// 	output_data jsonb NULL,
// 	status_code int4 NULL,
// 	event_time timestamp DEFAULT now() NULL,
// 	duration_ms int4 NULL,
// 	details jsonb NULL,
// 	CONSTRAINT amadeus_ai_events_pkey PRIMARY KEY (id)
// );

#[derive(sqlx::FromRow, Debug, Deserialize, Serialize, Clone)]
pub struct AmadeusAiEvent {
    pub id: i32,
    pub execution_id: Option<String>,
    pub event_type: Option<String>,
    pub api_call_type: Option<String>,
    pub input_data: Option<serde_json::Value>,
    pub output_data: Option<serde_json::Value>,
    pub status_code: Option<i32>,
    pub event_time: Option<DateTime<Utc>>,
    pub duration_ms: Option<i32>,
    pub details: Option<serde_json::Value>,
}

// Commented out - requires amadeus_ai_events table
// Re-enable if needed for specific use cases
/*
pub async fn get_events_by_execution_id(
    pool: &PgPool,
    execution_id: &str,
) -> Result<Option<AmadeusAiEvent>, sqlx::Error> {
    let records = sqlx::query_as!(
        AmadeusAiEvent,
        r#"
        SELECT 
            id,
            execution_id,
            event_type,
            api_call_type,
            input_data,
            output_data,
            status_code,
            event_time as "event_time: DateTime<Utc>",
            duration_ms,
            details
        FROM amadeus_ai_events
        WHERE event_type = 'openai_response_translation'
        ORDER BY execution_id DESC
        "#,
        // execution_id
    )
    .fetch_optional(pool)
    .await?;
    Ok(records)
}
*/

#[cfg(test)]
mod tests {
    use crate::{config, result_ext::ResultExt};

    use super::*;
    use sqlx::{PgPool, postgres::PgPoolOptions};
    use tracing::info;

    #[tokio::test]
    async fn test_get_events_by_execution_id() {
        let pg_cfg = config::PostgresqlEnv::from_env().unwrap();
        info!("connecting to database");
        let pool: sqlx::Pool<sqlx::Postgres> = PgPoolOptions::new()
            .max_connections(5)
            .connect_with(pg_cfg.get_pg_options())
            .await
            .log("PgPoolOptions")
            .unwrap();

        let event = get_events_by_execution_id(&pool, "513477980908159207").await.unwrap();

        info!("Found event: {:?}", event);
        // assert!(!events.is_empty());
    }
}
