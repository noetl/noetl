from __future__ import annotations

import os
from typing import Any, Optional

from psycopg.rows import dict_row
from psycopg.types.json import Json

from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger
from noetl.core.messaging import NATSEventPublisher
from noetl.core.outbox import enqueue_outbox, publish_outbox_batch

from .ports import EventRecord, ExpectedVersionConflict

logger = setup_logger(__name__, include_location=True)
_event_store_subject_publisher: NATSEventPublisher | None = None


def _event_mirror_enabled() -> bool:
    return os.getenv("NOETL_EVENT_MIRROR_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _event_store_subject(event: dict[str, Any]) -> str:
    global _event_store_subject_publisher
    if _event_store_subject_publisher is None:
        _event_store_subject_publisher = NATSEventPublisher()
    return _event_store_subject_publisher.subject_for_event(event)


async def _enqueue_event_store_outbox(cur: Any, event: dict[str, Any]) -> None:
    if not _event_mirror_enabled():
        return
    await enqueue_outbox(cur, event, subject=_event_store_subject(event))


async def _drain_event_store_outbox() -> None:
    if not _event_mirror_enabled():
        return
    try:
        limit = int(os.getenv("NOETL_EVENT_STORE_OUTBOX_DRAIN_LIMIT", "100"))
        await publish_outbox_batch(limit=limit)
    except Exception as exc:
        logger.warning("Event-store outbox drain failed: %s", exc)


class PostgresEventStore:
    """Postgres `noetl.event` reference event-store adapter."""

    async def _next_event_id(self, cur: Any) -> int:
        await cur.execute("SELECT noetl.snowflake_id() AS snowflake_id")
        row = await cur.fetchone()
        if not row:
            raise RuntimeError("Failed to generate snowflake ID from database")
        return int(row.get("snowflake_id") if isinstance(row, dict) else row[0])

    async def _current_version(self, cur: Any, stream_id: str) -> int:
        await cur.execute(
            "SELECT COALESCE(max(stream_version), 0) AS version FROM noetl.event WHERE stream_id = %s",
            (stream_id,),
        )
        row = await cur.fetchone()
        return int((row or {}).get("version") or 0)

    async def append(
        self,
        stream_id: str,
        events: list[EventRecord],
        *,
        expected_version: Optional[int] = None,
    ) -> int:
        if not events:
            return expected_version or 0

        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (stream_id,))
                current_version = await self._current_version(cur, stream_id)
                if expected_version is not None and current_version != expected_version:
                    raise ExpectedVersionConflict(
                        stream_id=stream_id,
                        expected_version=expected_version,
                        actual_version=current_version,
                    )

                next_version = current_version
                for record in events:
                    next_version += 1
                    event_id = await self._next_event_id(cur)
                    envelope = record.envelope(stream_version=next_version, event_id=event_id)
                    await cur.execute(
                        """
                        INSERT INTO noetl.event (
                            event_id, execution_id, event_type, node_name, status,
                            result, meta, tenant_id, organization_id, stream_id,
                            stream_version, aggregate_id, aggregate_type, schema_name,
                            schema_version, event_time, ingest_time, producer,
                            causation_id, correlation_id, idempotency_key, payload_ref,
                            envelope_checksum, created_at
                        )
                        VALUES (
                            %(event_id)s, %(execution_id)s, %(event_type)s,
                            %(node_name)s, %(status)s, %(result)s, %(meta)s,
                            %(tenant_id)s, %(organization_id)s, %(stream_id)s,
                            %(stream_version)s, %(aggregate_id)s, %(aggregate_type)s,
                            %(schema_name)s, %(schema_version)s, %(event_time)s, now(),
                            %(producer)s, %(causation_id)s, %(correlation_id)s,
                            %(idempotency_key)s, %(payload_ref)s,
                            %(envelope_checksum)s, now()
                        )
                        """,
                        {
                            **envelope,
                            "result": Json(envelope.get("result") or {}),
                            "meta": Json(envelope.get("meta") or {}),
                            "payload_ref": Json(envelope["payload_ref"]) if envelope.get("payload_ref") else None,
                        },
                    )
                    await _enqueue_event_store_outbox(cur, envelope)

                await conn.commit()
                await _drain_event_store_outbox()
                return next_version

    async def read(
        self,
        stream_id: str,
        *,
        from_version: int = 1,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT event_id, event_type, stream_id, stream_version,
                           tenant_id, organization_id, execution_id, aggregate_id,
                           aggregate_type, schema_name, schema_version, event_time,
                           ingest_time, producer, causation_id, correlation_id,
                           idempotency_key, payload_ref, envelope_checksum,
                           result, meta, status, node_name
                    FROM noetl.event
                    WHERE stream_id = %s
                      AND stream_version >= %s
                    ORDER BY stream_version ASC
                    LIMIT %s
                    """,
                    (stream_id, from_version, limit),
                )
                rows = await cur.fetchall()
        return [dict(row) for row in rows]
