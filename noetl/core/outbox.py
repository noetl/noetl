"""Transactional outbox for mirrored event distribution."""

from __future__ import annotations

import json
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json

from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger
from noetl.core.messaging import NATSEventPublisher
from noetl.core.storage.arrow_ipc import rows_to_arrow_feather

logger = setup_logger(__name__, include_location=True)

OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS noetl.outbox (
    outbox_id BIGSERIAL PRIMARY KEY,
    execution_id BIGINT,
    event_id BIGINT NOT NULL,
    subject TEXT,
    payload JSONB NOT NULL,
    payload_bytes BYTEA,
    payload_codec TEXT NOT NULL DEFAULT 'arrow-feather',
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'IN_FLIGHT', 'PUBLISHED', 'FAILED')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (execution_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_outbox_ready
    ON noetl.outbox (status, available_at, outbox_id)
    WHERE status IN ('PENDING', 'FAILED');

CREATE INDEX IF NOT EXISTS idx_outbox_execution_event
    ON noetl.outbox (execution_id, event_id);
"""


def normalize_outbox_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Return a JSONB-safe event envelope without changing semantic fields."""

    return json.loads(json.dumps(event, default=str, sort_keys=True))


async def ensure_outbox_schema() -> None:
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(OUTBOX_DDL)
        await conn.commit()


async def enqueue_outbox(cur: Any, event: dict[str, Any], *, subject: str | None = None) -> None:
    """Enqueue a mirrored event in the caller's current database transaction.

    The arrow-feather encoded ``payload_bytes`` is best-effort: the JSONB
    ``payload`` column is the source of truth (NATS publishes from it
    directly per ``publish_outbox_batch``), and the projector's NATS
    consumer falls back to JSON when feather bytes are missing.  If the
    feather encode fails — typically a pyarrow type-inference error on
    a deeply nested payload that the safe-table helper still can't
    coerce — we record NULL for payload_bytes + ``payload_codec='json'``
    so direct-table readers know to use the JSONB column.  The outbox
    insert must never fail the surrounding batch transaction over an
    accelerator format that the consumer side already treats as
    optional.  See noetl/ai-meta#36.
    """

    event_id = event.get("event_id")
    if event_id is None:
        raise ValueError("outbox requires event_id")
    payload = normalize_outbox_payload(event)
    try:
        payload_bytes, _schema_digest, _row_count = rows_to_arrow_feather([payload])
        payload_codec = "arrow-feather"
    except Exception as exc:
        logger.warning(
            "[OUTBOX] Arrow-feather encoding failed for event_id=%s execution_id=%s; "
            "falling back to NULL payload_bytes + payload_codec='json'.  Error: %s",
            event_id,
            payload.get("execution_id"),
            exc,
        )
        payload_bytes = None
        payload_codec = "json"
    execution_id = payload.get("execution_id")
    await cur.execute(
        """
        INSERT INTO noetl.outbox (execution_id, event_id, subject, payload, payload_bytes, payload_codec)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (execution_id, event_id) DO NOTHING
        """,
        (
            int(execution_id) if execution_id is not None else None,
            int(event_id),
            subject,
            Json(payload),
            payload_bytes,
            payload_codec,
        ),
    )


async def claim_outbox_batch(*, limit: int = 100) -> list[dict[str, Any]]:
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                WITH ready AS (
                    SELECT outbox_id
                    FROM noetl.outbox
                    WHERE status IN ('PENDING', 'FAILED')
                      AND available_at <= now()
                    ORDER BY outbox_id
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE noetl.outbox o
                SET status = 'IN_FLIGHT',
                    attempts = attempts + 1,
                    locked_at = now(),
                    updated_at = now()
                FROM ready
                WHERE o.outbox_id = ready.outbox_id
                RETURNING o.outbox_id, o.event_id, o.execution_id, o.subject,
                          o.payload, o.payload_bytes, o.payload_codec, o.attempts
                """,
                (max(1, int(limit)),),
            )
            rows = await cur.fetchall()
        await conn.commit()
    return [dict(row) for row in rows]


async def mark_outbox_published(outbox_id: int) -> None:
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE noetl.outbox
                SET status = 'PUBLISHED',
                    published_at = now(),
                    updated_at = now(),
                    last_error = NULL
                WHERE outbox_id = %s
                """,
                (int(outbox_id),),
            )
        await conn.commit()


async def mark_outbox_failed(
    outbox_id: int,
    error: Exception,
    *,
    attempts: int = 1,
    max_delay_seconds: int = 300,
) -> None:
    delay_seconds = min(max_delay_seconds, 2 ** min(8, max(0, int(attempts) - 1)))
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE noetl.outbox
                SET status = 'FAILED',
                    available_at = now() + (%s || ' seconds')::interval,
                    last_error = %s,
                    updated_at = now()
                WHERE outbox_id = %s
                """,
                (delay_seconds, str(error)[:2000], int(outbox_id)),
            )
        await conn.commit()


async def publish_outbox_batch(
    *,
    limit: int = 100,
    publisher: NATSEventPublisher | None = None,
) -> int:
    """Publish one claimed outbox batch to the configured event distribution stream.

    All NATS payloads are published as JSON via ``publish_event``, regardless of
    whether ``payload_bytes`` (arrow-feather) is present in the outbox row.

    Background: ``enqueue_outbox`` always writes an arrow-feather encoded copy of
    the event into ``payload_bytes`` for projector fan-out consumers that read the
    outbox table directly.  The previous code sent those raw bytes over NATS as
    well, which caused the gateway (``src/playbook_state.rs``, ``serde_json::from_slice``)
    to log 438 "Failed to parse lifecycle NATS payload as JSON" warnings and never
    deliver a ``playbook/state`` SSE frame to the SPA.

    The projector's NATS consumer (``noetl/core/projector/nats_worker.py``,
    ``decode_projector_notification``) already handles both JSON and arrow-feather
    (JSON first, feather fallback), so switching to JSON here does not break it.
    The arrow-feather bytes remain available in the ``payload_bytes`` DB column for
    any reader that queries the outbox table directly.

    Fix introduced: kadyapam/outbox-nats-publish-json (2026-05-27).
    Root-cause chain: round-02 of handoff 2026-05-27-itinerary-planner-spa-hang.
    """

    rows = await claim_outbox_batch(limit=limit)
    if not rows:
        return 0
    event_publisher = publisher or NATSEventPublisher()
    published = 0
    for row in rows:
        try:
            payload = row.get("payload") or {}
            # Always publish JSON over NATS. The JSONB ``payload`` column is the
            # source of truth for the event envelope; ``payload_bytes`` stays in
            # the DB for direct-table readers (projector fan-out) only.
            await event_publisher.publish_event(payload)
            await mark_outbox_published(int(row["outbox_id"]))
            published += 1
        except Exception as exc:
            logger.warning(
                "Outbox publish failed outbox_id=%s event_id=%s: %s",
                row.get("outbox_id"),
                row.get("event_id"),
                exc,
            )
            await mark_outbox_failed(
                int(row["outbox_id"]),
                exc,
                attempts=int(row.get("attempts") or 1),
            )
    return published


async def run_outbox_publisher_once(*, limit: int = 100) -> int:
    await ensure_outbox_schema()
    return await publish_outbox_batch(limit=limit)
