from __future__ import annotations

from typing import Any, Optional

from psycopg.rows import dict_row
from psycopg.types.json import Json

from noetl.core.db.pool import get_pool_connection

from .ports import ProjectionQuery, ProjectionRecord, ProjectionSnapshot


_PROJECTION_DDL = """
CREATE TABLE IF NOT EXISTS noetl.projection (
    projection_id TEXT PRIMARY KEY,
    projection_type TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    organization_id TEXT NOT NULL DEFAULT 'default',
    execution_id BIGINT,
    version BIGINT NOT NULL,
    source_event_id BIGINT,
    state JSONB NOT NULL,
    checksum TEXT NOT NULL,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projection_tenant_type
    ON noetl.projection (tenant_id, organization_id, projection_type);
CREATE INDEX IF NOT EXISTS idx_projection_execution
    ON noetl.projection (execution_id, projection_type)
    WHERE execution_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS noetl.projection_snapshot (
    aggregate_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    organization_id TEXT NOT NULL DEFAULT 'default',
    version BIGINT NOT NULL,
    snapshot JSONB NOT NULL,
    checksum TEXT NOT NULL,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, organization_id, aggregate_type, aggregate_id)
);

CREATE INDEX IF NOT EXISTS idx_projection_snapshot_type
    ON noetl.projection_snapshot (tenant_id, organization_id, aggregate_type, version DESC);
"""


class PostgresProjectionStore:
    """Postgres reference adapter for replayable projections and snapshots."""

    async def ensure_schema(self) -> None:
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_PROJECTION_DDL)
            await conn.commit()

    async def save_projection(self, record: ProjectionRecord) -> bool:
        checksum = record.resolved_checksum()
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.projection (
                        projection_id, projection_type, tenant_id, organization_id,
                        execution_id, version, source_event_id, state, checksum, meta
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (projection_id) DO UPDATE
                    SET projection_type = EXCLUDED.projection_type,
                        tenant_id = EXCLUDED.tenant_id,
                        organization_id = EXCLUDED.organization_id,
                        execution_id = EXCLUDED.execution_id,
                        version = EXCLUDED.version,
                        source_event_id = EXCLUDED.source_event_id,
                        state = EXCLUDED.state,
                        checksum = EXCLUDED.checksum,
                        meta = EXCLUDED.meta,
                        updated_at = now()
                    WHERE noetl.projection.version <= EXCLUDED.version
                    RETURNING xmax = 0 AS inserted
                    """,
                    (
                        record.projection_id,
                        record.projection_type,
                        record.tenant_id,
                        record.organization_id,
                        record.execution_id,
                        record.version,
                        record.source_event_id,
                        Json(record.state),
                        checksum,
                        Json(record.meta),
                    ),
                )
                changed = await cur.fetchone()
            await conn.commit()
        return changed is not None

    async def load_projection(self, projection_id: str) -> Optional[ProjectionRecord]:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT projection_id, projection_type, tenant_id, organization_id,
                           execution_id, version, source_event_id, state, checksum, meta
                    FROM noetl.projection
                    WHERE projection_id = %s
                    """,
                    (projection_id,),
                )
                row = await cur.fetchone()
        if not row:
            return None
        return ProjectionRecord(**dict(row))

    async def query_projections(self, query: ProjectionQuery) -> list[ProjectionRecord]:
        predicates: list[str] = []
        params: list[Any] = []
        if query.tenant_id is not None:
            predicates.append("tenant_id = %s")
            params.append(query.tenant_id)
        if query.organization_id is not None:
            predicates.append("organization_id = %s")
            params.append(query.organization_id)
        if query.projection_type is not None:
            predicates.append("projection_type = %s")
            params.append(query.projection_type)
        if query.execution_id is not None:
            predicates.append("execution_id = %s")
            params.append(int(query.execution_id))

        where_clause = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        params.append(max(1, int(query.limit or 100)))

        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""
                    SELECT projection_id, projection_type, tenant_id, organization_id,
                           execution_id, version, source_event_id, state, checksum, meta
                    FROM noetl.projection
                    {where_clause}
                    ORDER BY updated_at DESC, projection_id ASC
                    LIMIT %s
                    """,
                    params,
                )
                rows = await cur.fetchall()
        return [ProjectionRecord(**dict(row)) for row in rows]

    async def save_snapshot(self, snapshot: ProjectionSnapshot) -> bool:
        checksum = snapshot.resolved_checksum()
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.projection_snapshot (
                        aggregate_id, aggregate_type, tenant_id, organization_id,
                        version, snapshot, checksum, meta
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, organization_id, aggregate_type, aggregate_id)
                    DO UPDATE
                    SET version = EXCLUDED.version,
                        snapshot = EXCLUDED.snapshot,
                        checksum = EXCLUDED.checksum,
                        meta = EXCLUDED.meta,
                        updated_at = now()
                    WHERE noetl.projection_snapshot.version <= EXCLUDED.version
                    RETURNING xmax = 0 AS inserted
                    """,
                    (
                        snapshot.aggregate_id,
                        snapshot.aggregate_type,
                        snapshot.tenant_id,
                        snapshot.organization_id,
                        snapshot.version,
                        Json(snapshot.snapshot),
                        checksum,
                        Json(snapshot.meta),
                    ),
                )
                changed = await cur.fetchone()
            await conn.commit()
        return changed is not None

    async def load_snapshot(
        self,
        aggregate_id: str,
        *,
        aggregate_type: Optional[str] = None,
    ) -> Optional[ProjectionSnapshot]:
        predicate = "aggregate_id = %s"
        params: list[Any] = [aggregate_id]
        if aggregate_type:
            predicate += " AND aggregate_type = %s"
            params.append(aggregate_type)

        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""
                    SELECT aggregate_id, aggregate_type, tenant_id, organization_id,
                           version, snapshot, checksum, meta
                    FROM noetl.projection_snapshot
                    WHERE {predicate}
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    params,
                )
                row = await cur.fetchone()
        if not row:
            return None
        return ProjectionSnapshot(**dict(row))
