//! Credential database queries.

use crate::db::models::CredentialEntry;
use crate::db::DbPool;
use crate::error::AppResult;

/// Insert a new credential.
pub async fn insert_credential(
    pool: &DbPool,
    name: &str,
    credential_type: &str,
    data: &[u8],
    meta: Option<&serde_json::Value>,
    tags: Option<&[String]>,
    description: Option<&str>,
) -> AppResult<i64> {
    let result: (i64,) = sqlx::query_as(
        r#"
        INSERT INTO noetl.credential (name, type, data, meta, tags, description)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        "#,
    )
    .bind(name)
    .bind(credential_type)
    .bind(data)
    .bind(meta)
    .bind(tags)
    .bind(description)
    .fetch_one(pool)
    .await?;

    Ok(result.0)
}

/// Update an existing credential.
pub async fn update_credential(
    pool: &DbPool,
    id: i64,
    credential_type: &str,
    data: &[u8],
    meta: Option<&serde_json::Value>,
    tags: Option<&[String]>,
    description: Option<&str>,
) -> AppResult<()> {
    sqlx::query(
        r#"
        UPDATE noetl.credential
        SET type = $2, data = $3, meta = $4, tags = $5, description = $6, updated_at = NOW()
        WHERE id = $1
        "#,
    )
    .bind(id)
    .bind(credential_type)
    .bind(data)
    .bind(meta)
    .bind(tags)
    .bind(description)
    .execute(pool)
    .await?;

    Ok(())
}

/// Get a credential by ID.
pub async fn get_credential_by_id(pool: &DbPool, id: i64) -> AppResult<Option<CredentialEntry>> {
    let entry = sqlx::query_as::<_, CredentialEntry>(
        r#"
        SELECT id, name, type, data, meta, tags, description, created_at, updated_at
        FROM noetl.credential
        WHERE id = $1
        "#,
    )
    .bind(id)
    .fetch_optional(pool)
    .await?;

    Ok(entry)
}

/// Get a credential by name.
pub async fn get_credential_by_name(
    pool: &DbPool,
    name: &str,
) -> AppResult<Option<CredentialEntry>> {
    let entry = sqlx::query_as::<_, CredentialEntry>(
        r#"
        SELECT id, name, type, data, meta, tags, description, created_at, updated_at
        FROM noetl.credential
        WHERE name = $1
        "#,
    )
    .bind(name)
    .fetch_optional(pool)
    .await?;

    Ok(entry)
}

/// List credentials with optional filtering.
pub async fn list_credentials(
    pool: &DbPool,
    credential_type: Option<&str>,
    search: Option<&str>,
) -> AppResult<Vec<CredentialEntry>> {
    let entries = match (credential_type, search) {
        (Some(t), Some(q)) => {
            let pattern = format!("%{}%", q);
            sqlx::query_as::<_, CredentialEntry>(
                r#"
                SELECT id, name, type, data, meta, tags, description, created_at, updated_at
                FROM noetl.credential
                WHERE type = $1 AND (name ILIKE $2 OR description ILIKE $2)
                ORDER BY created_at DESC
                "#,
            )
            .bind(t)
            .bind(&pattern)
            .fetch_all(pool)
            .await?
        }
        (Some(t), None) => {
            sqlx::query_as::<_, CredentialEntry>(
                r#"
                SELECT id, name, type, data, meta, tags, description, created_at, updated_at
                FROM noetl.credential
                WHERE type = $1
                ORDER BY created_at DESC
                "#,
            )
            .bind(t)
            .fetch_all(pool)
            .await?
        }
        (None, Some(q)) => {
            let pattern = format!("%{}%", q);
            sqlx::query_as::<_, CredentialEntry>(
                r#"
                SELECT id, name, type, data, meta, tags, description, created_at, updated_at
                FROM noetl.credential
                WHERE name ILIKE $1 OR description ILIKE $1
                ORDER BY created_at DESC
                "#,
            )
            .bind(&pattern)
            .fetch_all(pool)
            .await?
        }
        (None, None) => {
            sqlx::query_as::<_, CredentialEntry>(
                r#"
                SELECT id, name, type, data, meta, tags, description, created_at, updated_at
                FROM noetl.credential
                ORDER BY created_at DESC
                "#,
            )
            .fetch_all(pool)
            .await?
        }
    };

    Ok(entries)
}

/// Delete a credential by ID.
pub async fn delete_credential_by_id(pool: &DbPool, id: i64) -> AppResult<bool> {
    let result = sqlx::query(
        r#"
        DELETE FROM noetl.credential
        WHERE id = $1
        "#,
    )
    .bind(id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Delete a credential by name.
pub async fn delete_credential_by_name(pool: &DbPool, name: &str) -> AppResult<bool> {
    let result = sqlx::query(
        r#"
        DELETE FROM noetl.credential
        WHERE name = $1
        "#,
    )
    .bind(name)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}
