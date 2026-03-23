"""
Periodic command reaper for orphaned or unpublished commands.

When a worker is OOMKilled or otherwise crashes ungracefully, it cannot emit
command.completed / command.failed events. Its NATS messages were already ACKed
at claim time, so no automatic redelivery occurs. Without intervention, those
commands stay in RUNNING state indefinitely.

This module provides a background task that:
1. Periodically finds commands claimed by workers that are now offline or
   have a stale heartbeat.
2. Re-publishes a NATS notification for each such command.
3. A healthy worker picks up the notification, calls claim_command, and the
   existing decide_reclaim_for_existing_claim() logic detects the dead worker
   and reclaims the command transparently.

It also recovers pending commands that were persisted as `command.issued` but
never claimed, for example when the server lost its NATS publisher connection
after committing the event.

Environment variables:
  NOETL_COMMAND_REAPER_ENABLED          - true/false (default: true)
  NOETL_COMMAND_REAPER_INTERVAL_SECONDS - scan frequency (default: 60)
  NOETL_COMMAND_REAPER_WORKER_STALE_SECONDS
                                        - heartbeat age to treat worker as dead
                                          (default: 60; should be >= sweep_interval
                                           so sweeper marks worker offline first)
  NOETL_COMMAND_REAPER_MAX_PER_RUN      - max commands re-published per cycle
                                          (default: 100)
  NOETL_COMMAND_REAPER_LOOKBACK_HOURS   - how far back to scan for issued commands
                                          (default: 24)
"""

from __future__ import annotations

import asyncio
import os

from psycopg.rows import dict_row

from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger
from noetl.core.urls import normalize_server_base_url

logger = setup_logger(__name__, include_location=True)

_REAPER_ENABLED = os.getenv("NOETL_COMMAND_REAPER_ENABLED", "true").strip().lower() in {
    "1", "true", "yes", "on"
}
_REAPER_INTERVAL_SECONDS = max(
    10.0, float(os.getenv("NOETL_COMMAND_REAPER_INTERVAL_SECONDS", "60"))
)
_REAPER_WORKER_STALE_SECONDS = max(
    30.0, float(os.getenv("NOETL_COMMAND_REAPER_WORKER_STALE_SECONDS", "60"))
)
_REAPER_MAX_PER_RUN = max(
    1, int(os.getenv("NOETL_COMMAND_REAPER_MAX_PER_RUN", "100"))
)
_REAPER_LOOKBACK_HOURS = max(
    1, int(os.getenv("NOETL_COMMAND_REAPER_LOOKBACK_HOURS", "24"))
)
_REAPER_PENDING_RETRY_SECONDS = max(
    15.0, float(os.getenv("NOETL_COMMAND_REAPER_PENDING_RETRY_SECONDS", "60"))
)


def get_reaper_interval_seconds() -> float:
    return _REAPER_INTERVAL_SECONDS


async def _find_orphaned_commands(
    stale_seconds: float,
    lookback_hours: int,
    max_commands: int,
) -> list[dict]:
    """
    Return commands that are claimed but not terminal, where the claiming
    worker is offline or has a stale heartbeat.

    Each row: {event_id, execution_id, command_id, step}
    """
    async with get_pool_connection(timeout=5.0) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                WITH latest_claims AS (
                    -- Most recent command.claimed event per command_id
                    SELECT DISTINCT ON (
                        COALESCE(meta->>'command_id', result->'data'->>'command_id')
                    )
                        COALESCE(meta->>'command_id', result->'data'->>'command_id') AS command_id,
                        worker_id,
                        execution_id
                    FROM noetl.event
                    WHERE event_type = 'command.claimed'
                      AND COALESCE(meta->>'command_id', result->'data'->>'command_id') IS NOT NULL
                      AND created_at > NOW() - (%s * INTERVAL '1 hour')
                    ORDER BY
                        COALESCE(meta->>'command_id', result->'data'->>'command_id'),
                        event_id DESC
                )
                SELECT
                    issued.event_id,
                    issued.execution_id,
                    claims.command_id,
                    issued.node_name AS step
                FROM latest_claims claims
                JOIN noetl.event issued
                    ON  issued.event_type = 'command.issued'
                    AND issued.execution_id = claims.execution_id
                    AND issued.meta->>'command_id' = claims.command_id
                LEFT JOIN noetl.runtime r
                    ON  r.name = claims.worker_id
                    AND r.kind = 'worker_pool'
                WHERE
                    -- Worker is gone or heartbeat is stale
                    (   r.name IS NULL
                        OR r.status != 'ready'
                        OR r.heartbeat < NOW() - (%s * INTERVAL '1 second')
                    )
                    -- Command has not reached a terminal state
                    AND NOT EXISTS (
                        SELECT 1 FROM noetl.event t
                        WHERE t.execution_id = issued.execution_id
                          AND t.event_type IN ('command.completed', 'command.failed')
                          AND (
                              t.meta->>'command_id' = claims.command_id
                              OR t.result->'data'->>'command_id' = claims.command_id
                          )
                    )
                    -- Execution is not cancelled
                    AND NOT EXISTS (
                        SELECT 1 FROM noetl.event x
                        WHERE x.execution_id = issued.execution_id
                          AND x.event_type = 'execution.cancelled'
                    )
                ORDER BY issued.event_id
                LIMIT %s
                """,
                (lookback_hours, stale_seconds, max_commands),
            )
            rows = await cur.fetchall()
    return list(rows or [])


async def _find_unclaimed_pending_commands(
    pending_retry_seconds: float,
    lookback_hours: int,
    max_commands: int,
) -> list[dict]:
    """
    Return commands that were issued but never claimed nor completed.

    These commands can be stranded when command.issued was committed but the
    NATS publish failed before workers were notified.
    """
    async with get_pool_connection(timeout=5.0) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                    issued.event_id,
                    issued.execution_id,
                    issued.meta->>'command_id' AS command_id,
                    issued.node_name AS step
                FROM noetl.event issued
                WHERE issued.event_type = 'command.issued'
                  AND issued.meta->>'command_id' IS NOT NULL
                  AND issued.created_at > NOW() - (%s * INTERVAL '1 hour')
                  AND issued.created_at < NOW() - (%s * INTERVAL '1 second')
                  AND NOT EXISTS (
                      SELECT 1 FROM noetl.event claims
                      WHERE claims.execution_id = issued.execution_id
                        AND claims.event_type = 'command.claimed'
                        AND (
                            claims.meta->>'command_id' = issued.meta->>'command_id'
                            OR claims.result->'data'->>'command_id' = issued.meta->>'command_id'
                        )
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM noetl.event terminal
                      WHERE terminal.execution_id = issued.execution_id
                        AND terminal.event_type IN ('command.completed', 'command.failed', 'command.cancelled')
                        AND (
                            terminal.meta->>'command_id' = issued.meta->>'command_id'
                            OR terminal.result->'data'->>'command_id' = issued.meta->>'command_id'
                        )
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM noetl.event x
                      WHERE x.execution_id = issued.execution_id
                        AND x.event_type = 'execution.cancelled'
                  )
                ORDER BY issued.event_id
                LIMIT %s
                """,
                (lookback_hours, pending_retry_seconds, max_commands),
            )
            rows = await cur.fetchall()
    return list(rows or [])


async def _get_nats_publisher():
    from noetl.server.api.v2 import get_nats_publisher

    return await get_nats_publisher()


async def reap_orphaned_commands_once(server_url: str) -> int:
    """
    Scan once for orphaned commands and re-publish them.

    Returns the number of commands successfully re-published.
    """
    # Reaper notifications must carry base server URL because workers append '/api/...'.
    server_url = normalize_server_base_url(server_url)

    orphaned = await _find_orphaned_commands(
        stale_seconds=_REAPER_WORKER_STALE_SECONDS,
        lookback_hours=_REAPER_LOOKBACK_HOURS,
        max_commands=_REAPER_MAX_PER_RUN,
    )
    stranded = await _find_unclaimed_pending_commands(
        pending_retry_seconds=_REAPER_PENDING_RETRY_SECONDS,
        lookback_hours=_REAPER_LOOKBACK_HOURS,
        max_commands=max(1, _REAPER_MAX_PER_RUN - len(orphaned)),
    )
    recovered = orphaned + stranded

    if not recovered:
        logger.debug("[REAPER] No orphaned or stranded commands found")
        return 0

    if orphaned:
        logger.warning(
            "[REAPER] Found %d orphaned command(s) from dead workers; re-publishing to NATS",
            len(orphaned),
        )
    if stranded:
        logger.warning(
            "[REAPER] Found %d stranded pending command(s) with no claim; re-publishing to NATS",
            len(stranded),
        )

    nats_pub = await _get_nats_publisher()
    republished = 0
    for cmd in recovered:
        try:
            await nats_pub.publish_command(
                execution_id=int(cmd["execution_id"]),
                event_id=int(cmd["event_id"]),
                command_id=str(cmd["command_id"]),
                step=str(cmd["step"]),
                server_url=server_url,
            )
            republished += 1
            logger.info(
                "[REAPER] Re-published command: execution_id=%s command_id=%s step=%s",
                cmd["execution_id"],
                cmd["command_id"],
                cmd["step"],
            )
        except Exception as pub_err:
            logger.error(
                "[REAPER] Failed to re-publish command %s: %s",
                cmd.get("command_id"),
                pub_err,
            )

    logger.info(
        "[REAPER] Re-published %d/%d recovered commands",
        republished,
        len(recovered),
    )
    return republished


async def run_command_reaper(stop_event: asyncio.Event, server_url: str) -> None:
    """
    Background task: scan for orphaned commands and re-publish NATS notifications.

    Designed to run for the lifetime of the server process. Exits cleanly when
    stop_event is set or the task is cancelled.
    """
    if not _REAPER_ENABLED:
        logger.info("[REAPER] Disabled via NOETL_COMMAND_REAPER_ENABLED=false")
        return

    logger.info(
        "[REAPER] Started (interval=%.0fs, stale_threshold=%.0fs, lookback=%dh)",
        _REAPER_INTERVAL_SECONDS,
        _REAPER_WORKER_STALE_SECONDS,
        _REAPER_LOOKBACK_HOURS,
    )

    while not stop_event.is_set():
        try:
            await asyncio.sleep(_REAPER_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("[REAPER] Cancelled during sleep; exiting")
            break

        if stop_event.is_set():
            break

        try:
            await reap_orphaned_commands_once(server_url)

        except asyncio.CancelledError:
            logger.info("[REAPER] Cancelled during scan; exiting")
            break
        except Exception as e:
            logger.error("[REAPER] Scan failed: %s", e, exc_info=True)
