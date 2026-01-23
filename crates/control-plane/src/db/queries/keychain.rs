//! Keychain database queries.

use crate::db::models::KeychainEntry;
use crate::db::DbPool;
use crate::error::AppResult;
use chrono::{DateTime, Utc};

/// Build the cache key for a keychain entry.
pub fn build_cache_key(
    keychain_name: &str,
    catalog_id: i64,
    scope_type: &str,
    execution_id: Option<i64>,
) -> String {
    match scope_type {
        "local" => {
            if let Some(exec_id) = execution_id {
                format!("{}:{}:{}", keychain_name, catalog_id, exec_id)
            } else {
                format!("{}:{}:local", keychain_name, catalog_id)
            }
        }
        "shared" => {
            if let Some(exec_id) = execution_id {
                format!("{}:{}:shared:{}", keychain_name, catalog_id, exec_id)
            } else {
                format!("{}:{}:shared", keychain_name, catalog_id)
            }
        }
        _ => format!("{}:{}:global", keychain_name, catalog_id),
    }
}

/// Insert or update a keychain entry.
#[allow(clippy::too_many_arguments)]
pub async fn upsert_keychain_entry(
    pool: &DbPool,
    cache_key: &str,
    catalog_id: i64,
    keychain_name: &str,
    scope_type: &str,
    execution_id: Option<i64>,
    data: &[u8],
    expires_at: Option<DateTime<Utc>>,
    auto_renew: bool,
    renew_config: Option<&serde_json::Value>,
) -> AppResult<i64> {
    let result: (i64,) = sqlx::query_as(
        r#"
        INSERT INTO noetl.keychain (
            cache_key, catalog_id, keychain_name, scope_type, execution_id,
            data, expires_at, auto_renew, renew_config
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (cache_key) DO UPDATE SET
            data = EXCLUDED.data,
            expires_at = EXCLUDED.expires_at,
            auto_renew = EXCLUDED.auto_renew,
            renew_config = EXCLUDED.renew_config,
            updated_at = NOW()
        RETURNING id
        "#,
    )
    .bind(cache_key)
    .bind(catalog_id)
    .bind(keychain_name)
    .bind(scope_type)
    .bind(execution_id)
    .bind(data)
    .bind(expires_at)
    .bind(auto_renew)
    .bind(renew_config)
    .fetch_one(pool)
    .await?;

    Ok(result.0)
}

/// Get a keychain entry by cache key.
pub async fn get_keychain_by_cache_key(
    pool: &DbPool,
    cache_key: &str,
) -> AppResult<Option<KeychainEntry>> {
    let entry = sqlx::query_as::<_, KeychainEntry>(
        r#"
        SELECT id, cache_key, catalog_id, keychain_name, scope_type, execution_id,
               data, expires_at, auto_renew, renew_config, access_count, accessed_at,
               created_at, updated_at
        FROM noetl.keychain
        WHERE cache_key = $1
        "#,
    )
    .bind(cache_key)
    .fetch_optional(pool)
    .await?;

    Ok(entry)
}

/// Increment access count and update accessed_at.
pub async fn increment_access_count(pool: &DbPool, id: i64) -> AppResult<()> {
    sqlx::query(
        r#"
        UPDATE noetl.keychain
        SET access_count = access_count + 1, accessed_at = NOW()
        WHERE id = $1
        "#,
    )
    .bind(id)
    .execute(pool)
    .await?;

    Ok(())
}

/// Delete a keychain entry by cache key.
pub async fn delete_keychain_by_cache_key(pool: &DbPool, cache_key: &str) -> AppResult<bool> {
    let result = sqlx::query(
        r#"
        DELETE FROM noetl.keychain
        WHERE cache_key = $1
        "#,
    )
    .bind(cache_key)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// List all keychain entries for a catalog.
pub async fn list_keychain_by_catalog(
    pool: &DbPool,
    catalog_id: i64,
) -> AppResult<Vec<KeychainEntry>> {
    let entries = sqlx::query_as::<_, KeychainEntry>(
        r#"
        SELECT id, cache_key, catalog_id, keychain_name, scope_type, execution_id,
               data, expires_at, auto_renew, renew_config, access_count, accessed_at,
               created_at, updated_at
        FROM noetl.keychain
        WHERE catalog_id = $1
        ORDER BY created_at DESC
        "#,
    )
    .bind(catalog_id)
    .fetch_all(pool)
    .await?;

    Ok(entries)
}

/// Delete all expired keychain entries.
pub async fn delete_expired_entries(pool: &DbPool) -> AppResult<u64> {
    let result = sqlx::query(
        r#"
        DELETE FROM noetl.keychain
        WHERE expires_at IS NOT NULL AND expires_at < NOW() AND auto_renew = false
        "#,
    )
    .execute(pool)
    .await?;

    Ok(result.rows_affected())
}

/// Delete all keychain entries for an execution.
pub async fn delete_keychain_by_execution(pool: &DbPool, execution_id: i64) -> AppResult<u64> {
    let result = sqlx::query(
        r#"
        DELETE FROM noetl.keychain
        WHERE execution_id = $1
        "#,
    )
    .bind(execution_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected())
}
