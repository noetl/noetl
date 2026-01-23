//! Catalog database queries.

use crate::db::models::CatalogEntry;
use crate::db::DbPool;
use crate::error::AppResult;

/// Get the next version number for a path.
pub async fn get_next_version(pool: &DbPool, path: &str) -> AppResult<i32> {
    let result: Option<(i32,)> = sqlx::query_as(
        r#"
        SELECT COALESCE(MAX(version), 0) + 1
        FROM noetl.catalog
        WHERE path = $1
        "#,
    )
    .bind(path)
    .fetch_optional(pool)
    .await?;

    Ok(result.map(|(v,)| v).unwrap_or(1))
}

/// Insert a new catalog entry.
#[allow(clippy::too_many_arguments)]
pub async fn insert_catalog_entry(
    pool: &DbPool,
    path: &str,
    kind: &str,
    version: i32,
    content: &str,
    layout: Option<&serde_json::Value>,
    payload: Option<&serde_json::Value>,
    meta: Option<&serde_json::Value>,
) -> AppResult<i64> {
    let result: (i64,) = sqlx::query_as(
        r#"
        INSERT INTO noetl.catalog (path, kind, version, content, layout, payload, meta)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        "#,
    )
    .bind(path)
    .bind(kind)
    .bind(version)
    .bind(content)
    .bind(layout)
    .bind(payload)
    .bind(meta)
    .fetch_one(pool)
    .await?;

    Ok(result.0)
}

/// Get a catalog entry by ID.
pub async fn get_catalog_by_id(pool: &DbPool, id: i64) -> AppResult<Option<CatalogEntry>> {
    let entry = sqlx::query_as::<_, CatalogEntry>(
        r#"
        SELECT id, path, kind, version, content, layout, payload, meta, created_at
        FROM noetl.catalog
        WHERE id = $1
        "#,
    )
    .bind(id)
    .fetch_optional(pool)
    .await?;

    Ok(entry)
}

/// Get a catalog entry by path and version.
pub async fn get_catalog_by_path_version(
    pool: &DbPool,
    path: &str,
    version: i32,
) -> AppResult<Option<CatalogEntry>> {
    let entry = sqlx::query_as::<_, CatalogEntry>(
        r#"
        SELECT id, path, kind, version, content, layout, payload, meta, created_at
        FROM noetl.catalog
        WHERE path = $1 AND version = $2
        "#,
    )
    .bind(path)
    .bind(version)
    .fetch_optional(pool)
    .await?;

    Ok(entry)
}

/// Get the latest catalog entry by path.
pub async fn get_catalog_latest(pool: &DbPool, path: &str) -> AppResult<Option<CatalogEntry>> {
    let entry = sqlx::query_as::<_, CatalogEntry>(
        r#"
        SELECT id, path, kind, version, content, layout, payload, meta, created_at
        FROM noetl.catalog
        WHERE path = $1
        ORDER BY version DESC
        LIMIT 1
        "#,
    )
    .bind(path)
    .fetch_optional(pool)
    .await?;

    Ok(entry)
}

/// List all catalog entries, optionally filtered by kind.
pub async fn list_catalog_entries(
    pool: &DbPool,
    kind: Option<&str>,
) -> AppResult<Vec<CatalogEntry>> {
    let entries = if let Some(k) = kind {
        sqlx::query_as::<_, CatalogEntry>(
            r#"
            SELECT id, path, kind, version, content, layout, payload, meta, created_at
            FROM noetl.catalog
            WHERE kind = $1
            ORDER BY created_at DESC
            "#,
        )
        .bind(k)
        .fetch_all(pool)
        .await?
    } else {
        sqlx::query_as::<_, CatalogEntry>(
            r#"
            SELECT id, path, kind, version, content, layout, payload, meta, created_at
            FROM noetl.catalog
            ORDER BY created_at DESC
            "#,
        )
        .fetch_all(pool)
        .await?
    };

    Ok(entries)
}

/// Get all versions of a catalog entry by path.
pub async fn get_catalog_all_versions(pool: &DbPool, path: &str) -> AppResult<Vec<CatalogEntry>> {
    let entries = sqlx::query_as::<_, CatalogEntry>(
        r#"
        SELECT id, path, kind, version, content, layout, payload, meta, created_at
        FROM noetl.catalog
        WHERE path = $1
        ORDER BY version DESC
        "#,
    )
    .bind(path)
    .fetch_all(pool)
    .await?;

    Ok(entries)
}
