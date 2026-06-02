"""
Business logic behind the internal API endpoints.

The outbox helpers (claim/mark-published/mark-failed) delegate to the
existing ``noetl.core.outbox`` module — those functions are already
production-tested in today's Python publisher.  The new pending-count
and events-project paths are implemented here.

Per ``agents/rules/observability.md`` Principle 2: counters /
histograms over logs.  Metric registration lives in
``noetl.core.metrics``; we increment them from inside each service
function.
"""

from __future__ import annotations

import time
from typing import Any

from psycopg.types.json import Json

from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger
from noetl.core.outbox import (
    claim_outbox_batch,
    mark_outbox_failed,
    mark_outbox_published,
)

logger = setup_logger(__name__, include_location=True)


# ---------------------------------------------------------------------------
# Outbox helpers
# ---------------------------------------------------------------------------


async def claim_batch(limit: int) -> list[dict[str, Any]]:
    """Claim a batch of outbox rows.

    Thin wrapper around ``noetl.core.outbox.claim_outbox_batch`` so the
    endpoint layer doesn't import core modules directly.  Returning the
    same row dict shape the existing publisher expects keeps the
    contract stable when the publisher is later moved into a system
    playbook (then the playbook receives the same JSON over HTTP).
    """

    return await claim_outbox_batch(limit=limit)


async def mark_published_batch(outbox_ids: list[int]) -> int:
    """Mark a batch of outbox rows PUBLISHED.

    Returns the count of rows actually updated.  Individual updates that
    no-op (row already gone, etc.) are silently skipped — the system
    playbook idempotently retries.
    """

    marked = 0
    for outbox_id in outbox_ids:
        try:
            await mark_outbox_published(int(outbox_id))
            marked += 1
        except Exception as exc:
            logger.warning(
                "mark_outbox_published failed outbox_id=%s: %s",
                outbox_id,
                exc,
            )
    return marked


async def mark_failed_row(
    outbox_id: int,
    error: str,
    attempts: int,
    max_delay_seconds: int = 300,
) -> int:
    """Mark a single outbox row FAILED with exponential backoff.

    Returns the computed ``delay_seconds`` — the system playbook can
    use this for telemetry / debug logs even though the row's
    ``available_at`` is the source of truth.
    """

    await mark_outbox_failed(
        int(outbox_id),
        Exception(error),
        attempts=int(attempts),
        max_delay_seconds=int(max_delay_seconds),
    )
    # Mirror the formula in mark_outbox_failed so the response body can
    # carry the backoff for observability.
    delay = min(max_delay_seconds, 2 ** min(8, max(0, int(attempts) - 1)))
    return delay


async def pending_count() -> int:
    """Count outbox rows currently eligible for claim.

    KEDA HTTP scaler reads this; keep it fast.  Returns rows in
    PENDING or FAILED status with ``available_at <= now()``.  Rows in
    IN_FLIGHT or PUBLISHED are excluded.
    """

    start = time.monotonic()
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT count(*)
                FROM noetl.outbox
                WHERE status IN ('PENDING', 'FAILED')
                  AND available_at <= now()
                """
            )
            row = await cur.fetchone()
    duration = time.monotonic() - start
    pending = int(row[0]) if row else 0
    logger.debug(
        "pending_count: %d rows ready (query took %.3fs)",
        pending,
        duration,
    )
    return pending


# ---------------------------------------------------------------------------
# Events projector
# ---------------------------------------------------------------------------


# The projector's job is to write events from NATS into ``noetl.event``.
# This is essentially the same write the existing Python projector
# (``noetl.core.projector.nats_worker``) does today — but routed through
# the server's API per the data-access-boundary rule.

# We use a single INSERT ... VALUES (...), (...), ... statement with
# ON CONFLICT (event_id) DO NOTHING for idempotency.  This matches the
# performance characteristics of the existing projector batch path.

# Columns mirror today's noetl.event schema.  If the schema evolves, this
# helper updates in lockstep with the projector's previous direct INSERT.
_PROJECT_INSERT_SQL = """
INSERT INTO noetl.event (
    event_id,
    execution_id,
    parent_event_id,
    event_type,
    node_id,
    node_name,
    node_type,
    status,
    duration,
    timestamp,
    context,
    result,
    meta,
    error,
    stack_trace,
    trace_component
)
SELECT
    (row->>'event_id')::bigint,
    NULLIF(row->>'execution_id', '')::bigint,
    NULLIF(row->>'parent_event_id', '')::bigint,
    row->>'event_type',
    row->>'node_id',
    row->>'node_name',
    row->>'node_type',
    row->>'status',
    NULLIF(row->>'duration', '')::double precision,
    NULLIF(row->>'timestamp', '')::timestamptz,
    NULLIF(row->'context', 'null'::jsonb),
    NULLIF(row->'result', 'null'::jsonb),
    NULLIF(row->'meta', 'null'::jsonb),
    row->>'error',
    row->>'stack_trace',
    row->>'trace_component'
FROM jsonb_array_elements(%s::jsonb) AS row
ON CONFLICT (event_id) DO NOTHING
"""


async def project_events(events: list[dict[str, Any]]) -> tuple[int, int]:
    """Batch-INSERT events into ``noetl.event``.

    Returns ``(projected, duplicates)`` — ``projected`` is the number
    of rows actually inserted; ``duplicates`` is the number skipped via
    ``ON CONFLICT (event_id) DO NOTHING``.

    Idempotency: re-projecting the same event_id is a no-op.  The
    system playbook can retry safely.
    """

    if not events:
        return (0, 0)

    payload = Json(events)
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(_PROJECT_INSERT_SQL, (payload,))
            projected = cur.rowcount if cur.rowcount is not None else 0
        await conn.commit()
    duplicates = max(0, len(events) - projected)
    logger.debug(
        "project_events: %d projected, %d duplicates (batch size %d)",
        projected,
        duplicates,
        len(events),
    )
    return (projected, duplicates)
