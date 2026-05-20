"""Replay event-reader ports and reference storage adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol

from psycopg.rows import dict_row

from noetl.core.db.pool import get_pool_connection

from .types import ReplayCutoff, ReplaySnapshotSeed

ENVELOPE_COLUMNS = (
    "tenant_id",
    "organization_id",
    "stream_id",
    "stream_version",
    "aggregate_id",
    "aggregate_type",
    "schema_name",
    "schema_version",
    "event_time",
    "ingest_time",
    "producer",
    "causation_id",
    "correlation_id",
    "idempotency_key",
    "payload_ref",
    "stage_id",
    "frame_id",
    "command_id",
    "envelope_checksum",
)


class ReplayEventReader(Protocol):
    """Storage-neutral read port for canonical replay inputs."""

    async def load_events(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        cutoff: ReplayCutoff,
        limit: int,
        after_event_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Load canonical events in replay order."""

    async def load_snapshot_seed(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        projection: str,
        cutoff: ReplayCutoff,
    ) -> Optional[ReplaySnapshotSeed]:
        """Load the latest safe replay snapshot seed, when available."""


class PostgresReplayEventReader:
    """Postgres-backed reference adapter for replay input reads."""

    @staticmethod
    async def _event_columns(conn: Any) -> set[str]:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'noetl'
                  AND table_name = 'event'
                """
            )
            rows = await cur.fetchall()
        return {
            str(row["column_name"] if isinstance(row, Mapping) else row[0])
            for row in rows
        }

    async def _time_cutoff_event_id(
        self,
        conn: Any,
        *,
        columns: set[str],
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        cutoff: ReplayCutoff,
    ) -> Optional[int]:
        if cutoff.as_of_time is None:
            return None

        predicates = ["execution_id = %s"]
        params: list[Any] = [execution_id]
        if "tenant_id" in columns:
            predicates.append("tenant_id = %s")
            params.append(tenant_id)
        elif tenant_id != "default":
            return None
        if "organization_id" in columns:
            predicates.append("organization_id = %s")
            params.append(organization_id)
        elif organization_id != "default":
            return None

        time_column = "event_time" if "event_time" in columns else "created_at"
        predicates.append(f"{time_column} <= %s")
        params.append(cutoff.as_of_time)

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT MAX(event_id) AS cutoff_event_id
                FROM noetl.event
                WHERE {' AND '.join(predicates)}
                """,
                params,
            )
            row = await cur.fetchone()
        if not row:
            return None
        value = row.get("cutoff_event_id") if isinstance(row, Mapping) else row[0]
        return int(value) if value is not None else None

    async def load_events(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        cutoff: ReplayCutoff,
        limit: int,
        after_event_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        async with get_pool_connection() as conn:
            columns = await self._event_columns(conn)
            predicates = ["execution_id = %s"]
            params: list[Any] = [execution_id]
            if "tenant_id" in columns:
                predicates.append("tenant_id = %s")
                params.append(tenant_id)
            elif tenant_id != "default":
                return []
            if "organization_id" in columns:
                predicates.append("organization_id = %s")
                params.append(organization_id)
            elif organization_id != "default":
                return []

            cutoff_event_id = cutoff.as_of_event_id or cutoff.as_of_position
            if after_event_id is not None:
                predicates.append("event_id > %s")
                params.append(int(after_event_id))
            if cutoff_event_id is not None:
                predicates.append("event_id <= %s")
                params.append(int(cutoff_event_id))
            if cutoff.as_of_time is not None:
                time_column = "event_time" if "event_time" in columns else "created_at"
                predicates.append(f"{time_column} <= %s")
                params.append(cutoff.as_of_time)
            params.append(limit)

            select_columns = [
                "event_id",
                "event_type",
                "status",
                "node_name",
                "result",
                "meta",
            ]
            select_columns.extend(column for column in ENVELOPE_COLUMNS if column in columns)

            query = f"""
                SELECT {', '.join(select_columns)}
                FROM noetl.event
                WHERE {' AND '.join(predicates)}
                ORDER BY event_id ASC
                LIMIT %s
            """

            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()

        events = [dict(row) for row in rows]
        for event in events:
            event.setdefault("tenant_id", tenant_id)
            event.setdefault("organization_id", organization_id)
            for column in ENVELOPE_COLUMNS:
                event.setdefault(column, None)
        return events

    async def load_snapshot_seed(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        projection: str,
        cutoff: ReplayCutoff,
    ) -> Optional[ReplaySnapshotSeed]:
        cutoff_event_id = cutoff.as_of_event_id or cutoff.as_of_position

        aggregate_id = f"execution/{execution_id}/{projection}"
        aggregate_type = "replay_state"
        predicates = [
            "tenant_id = %s",
            "organization_id = %s",
            "aggregate_type = %s",
            "aggregate_id = %s",
        ]
        params: list[Any] = [tenant_id, organization_id, aggregate_type, aggregate_id]
        if cutoff_event_id is not None:
            predicates.append("version <= %s")
            params.append(int(cutoff_event_id))

        try:
            async with get_pool_connection() as conn:
                if cutoff.as_of_time is not None:
                    columns = await self._event_columns(conn)
                    cutoff_event_id = await self._time_cutoff_event_id(
                        conn,
                        columns=columns,
                        tenant_id=tenant_id,
                        organization_id=organization_id,
                        execution_id=execution_id,
                        cutoff=cutoff,
                    )
                    if cutoff_event_id is None:
                        return None
                    predicates.append("version <= %s")
                    params.append(cutoff_event_id)

                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        f"""
                        SELECT aggregate_id, aggregate_type, version, snapshot, checksum, meta
                        FROM noetl.projection_snapshot
                        WHERE {' AND '.join(predicates)}
                        ORDER BY version DESC
                        LIMIT 1
                        """,
                        params,
                    )
                    row = await cur.fetchone()
        except Exception:
            return None
        if not row:
            return None
        snapshot = row["snapshot"] if isinstance(row["snapshot"], dict) else {}
        meta = row["meta"] if isinstance(row["meta"], dict) else {}
        return ReplaySnapshotSeed(
            aggregate_id=str(row["aggregate_id"]),
            aggregate_type=str(row["aggregate_type"]),
            version=int(row["version"]),
            checksum=str(row["checksum"]),
            state=snapshot,
            meta=meta,
        )
