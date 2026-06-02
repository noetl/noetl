"""
Periodic command reaper for orphaned or stranded NoETL commands.

Background
----------
``noetl.command`` is the source of truth for command lifecycle. Commands move
through PENDING -> CLAIMED -> RUNNING -> COMPLETED/FAILED/CANCELLED. Workers
heartbeat through ``noetl.runtime``.

When a worker dies hard (OOMKill, node eviction, network partition with no
graceful drain), it cannot emit ``command.completed`` / ``command.failed``.
Because NATS JetStream messages are ACKed at claim time, no automatic
redelivery happens. Similarly, the API may successfully insert a PENDING
``noetl.command`` row but fail to publish the NATS notification (publisher
outage, brief disconnect). In both cases the command sits non-terminal
forever and the playbook stalls.

This module periodically scans ``noetl.command`` directly for stale
non-terminal commands whose execution is also non-terminal, and re-publishes
the original NATS command notification. From there the existing claim
endpoint and ``noetl.claim_policy.decide_reclaim_for_existing_claim`` take
over and arbitrate safely. The reaper never forces command completion and
never duplicates the claim policy.

Two recovery categories are covered:

1. **Orphaned active commands** — ``CLAIMED`` / ``RUNNING`` rows whose
   ``worker_id`` is missing from ``noetl.runtime``, marked non-ready, or
   has a stale heartbeat. Healthy workers that have held a claim past the
   hard timeout are also surfaced so the claim policy can take it back.

2. **Stranded pending commands** — ``PENDING`` rows that have aged past the
   retry window without ever being CLAIMED. These typically result from a
   transient NATS publish failure right after the command row was committed.

The loop runs under a ``RuntimeLease`` so only one server instance performs
recovery at a time. See ``noetl.server.runtime_leases``.

Environment variables
---------------------
NOETL_COMMAND_REAPER_ENABLED
    Toggle the reaper entirely (default: ``true``).
NOETL_COMMAND_REAPER_INTERVAL_SECONDS
    Scan frequency (default: ``60``, minimum 10).
NOETL_COMMAND_REAPER_WORKER_STALE_SECONDS
    Worker heartbeat age (s) above which a CLAIMED/RUNNING command is
    considered orphaned (default: ``60``, minimum 30). Should be >=
    ``NOETL_RUNTIME_SWEEP_INTERVAL`` so the runtime_sweeper marks the
    worker offline first.
NOETL_COMMAND_REAPER_HEALTHY_HARD_TIMEOUT_SECONDS
    Maximum lifetime (s) of a CLAIMED/RUNNING command on a still-healthy
    worker before we re-publish anyway to let the claim policy decide
    (default: ``1800``).
NOETL_COMMAND_REAPER_PENDING_RETRY_SECONDS
    Minimum age (s) of a PENDING row before we re-publish it as stranded
    (default: ``60``, minimum 15).
NOETL_COMMAND_REAPER_MAX_PER_RUN
    Maximum commands re-published in a single cycle (default: ``100``).
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from psycopg.rows import dict_row

from noetl.core.db.pool import get_bg_pool_connection
from noetl.core.logger import setup_logger
from noetl.core.urls import normalize_server_base_url

logger = setup_logger(__name__, include_location=True)

# Status values stored on ``noetl.command``.
_ACTIVE_COMMAND_STATUSES = ("CLAIMED", "RUNNING")
_NON_TERMINAL_COMMAND_STATUSES = ("PENDING", "CLAIMED", "RUNNING")

# Execution-level terminal markers. Reaper must not republish commands for
# executions that have already concluded (the playbook has decided one way
# or the other and any stale rows are expected leftovers).
_TERMINAL_EXECUTION_EVENT_TYPES = [
    "playbook.completed",
    "playbook.failed",
    "workflow.completed",
    "workflow.failed",
    "execution.cancelled",
]

# Kept as a module attribute so historical event-based tests can still
# reference it; some auxiliary tooling may also consult it.
_TERMINAL_COMMAND_EVENT_TYPES = [
    "command.completed",
    "command.failed",
    "command.cancelled",
]

_REAPER_ENABLED = os.getenv("NOETL_COMMAND_REAPER_ENABLED", "true").strip().lower() in {
    "1", "true", "yes", "on"
}
_REAPER_INTERVAL_SECONDS = max(
    10.0, float(os.getenv("NOETL_COMMAND_REAPER_INTERVAL_SECONDS", "60"))
)
_REAPER_WORKER_STALE_SECONDS = max(
    30.0, float(os.getenv("NOETL_COMMAND_REAPER_WORKER_STALE_SECONDS", "60"))
)
_REAPER_HEALTHY_HARD_TIMEOUT_SECONDS = max(
    60.0,
    float(os.getenv("NOETL_COMMAND_REAPER_HEALTHY_HARD_TIMEOUT_SECONDS", "1800")),
)
_REAPER_PENDING_RETRY_SECONDS = max(
    15.0, float(os.getenv("NOETL_COMMAND_REAPER_PENDING_RETRY_SECONDS", "60"))
)
_REAPER_MAX_PER_RUN = max(
    1, int(os.getenv("NOETL_COMMAND_REAPER_MAX_PER_RUN", "100"))
)


def get_reaper_interval_seconds() -> float:
    return _REAPER_INTERVAL_SECONDS


def is_reaper_enabled() -> bool:
    return _REAPER_ENABLED


async def _find_stale_active_commands(
    *,
    stale_seconds: float,
    healthy_hard_timeout_seconds: float,
    max_commands: int,
) -> list[dict]:
    """
    Return CLAIMED/RUNNING ``noetl.command`` rows that look orphaned.

    A row is considered orphaned when its execution has not yet reached a
    terminal lifecycle event AND any of the following holds:

    * the ``worker_id`` is missing from ``noetl.runtime`` entirely;
    * the worker's runtime status is not ``ready``;
    * the worker's heartbeat is older than ``stale_seconds``;
    * the claim has lived past ``healthy_hard_timeout_seconds``.

    Each returned row carries the fields needed to republish via NATS:
    ``event_id``, ``execution_id``, ``command_id`` (string), ``step``,
    plus ``tool_kind`` + ``playbook_path`` for pool-routing (see
    noetl/ai-meta#42 + #46 Phase 2.a.2 — without these, re-published
    notifications would route to ``shared`` even for ``system/*``
    playbooks and the wrong pool could claim them).
    """
    async with get_bg_pool_connection(timeout=5.0) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                    c.event_id AS event_id,
                    c.execution_id AS execution_id,
                    c.command_id::text AS command_id,
                    c.step_name AS step,
                    c.tool_kind AS tool_kind,
                    cat.path AS playbook_path
                FROM noetl.command c
                LEFT JOIN noetl.runtime r
                    ON r.kind = 'worker_pool'
                   AND r.name = c.worker_id
                LEFT JOIN noetl.catalog cat
                    ON cat.catalog_id = c.catalog_id
                WHERE c.status = ANY(%s)
                  AND c.worker_id IS NOT NULL
                  AND c.claimed_at IS NOT NULL
                  AND (
                        r.name IS NULL
                     OR r.status IS DISTINCT FROM 'ready'
                     OR r.heartbeat < (NOW() - make_interval(secs => %s))
                     OR c.claimed_at < (NOW() - make_interval(secs => %s))
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM noetl.event et
                      WHERE et.execution_id = c.execution_id
                        AND et.event_type = ANY(%s)
                  )
                ORDER BY c.claimed_at ASC
                LIMIT %s
                """,
                (
                    list(_ACTIVE_COMMAND_STATUSES),
                    stale_seconds,
                    healthy_hard_timeout_seconds,
                    _TERMINAL_EXECUTION_EVENT_TYPES,
                    max_commands,
                ),
            )
            rows = await cur.fetchall()
    return list(rows or [])


async def _find_stranded_pending_commands(
    *,
    pending_retry_seconds: float,
    max_commands: int,
) -> list[dict]:
    """
    Return ``noetl.command`` rows still in PENDING long after they were
    persisted. These are typically commands whose NATS notification was
    lost (publisher disconnect, transient broker outage) right after the
    command row committed.

    Rows for executions that have already terminated are excluded so we
    do not republish work that the playbook has moved past.
    """
    async with get_bg_pool_connection(timeout=5.0) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                    c.event_id AS event_id,
                    c.execution_id AS execution_id,
                    c.command_id::text AS command_id,
                    c.step_name AS step,
                    c.tool_kind AS tool_kind,
                    cat.path AS playbook_path
                FROM noetl.command c
                LEFT JOIN noetl.catalog cat
                    ON cat.catalog_id = c.catalog_id
                WHERE c.status = 'PENDING'
                  AND c.created_at < (NOW() - make_interval(secs => %s))
                  AND NOT EXISTS (
                      SELECT 1 FROM noetl.event et
                      WHERE et.execution_id = c.execution_id
                        AND et.event_type = ANY(%s)
                  )
                ORDER BY c.created_at ASC
                LIMIT %s
                """,
                (
                    pending_retry_seconds,
                    _TERMINAL_EXECUTION_EVENT_TYPES,
                    max_commands,
                ),
            )
            rows = await cur.fetchall()
    return list(rows or [])


async def _get_nats_publisher():
    # Lazy import so unit tests can monkeypatch this attribute without
    # pulling in the NATS publisher singleton at import time.
    from noetl.server.api.core.core import get_nats_publisher

    return await get_nats_publisher()


async def reap_orphaned_commands_once(server_url: str) -> int:
    """
    Run a single reaper sweep: locate orphaned active commands and stranded
    pending commands on ``noetl.command``, then republish each via NATS.

    Returns the number of commands successfully republished. The claim
    endpoint together with ``decide_reclaim_for_existing_claim`` decides
    whether each republished notification translates into a fresh claim or
    is ACKed as a duplicate.
    """
    server_url = normalize_server_base_url(server_url)

    orphaned = await _find_stale_active_commands(
        stale_seconds=_REAPER_WORKER_STALE_SECONDS,
        healthy_hard_timeout_seconds=_REAPER_HEALTHY_HARD_TIMEOUT_SECONDS,
        max_commands=_REAPER_MAX_PER_RUN,
    )
    remaining_capacity = max(0, _REAPER_MAX_PER_RUN - len(orphaned))
    if remaining_capacity > 0:
        stranded = await _find_stranded_pending_commands(
            pending_retry_seconds=_REAPER_PENDING_RETRY_SECONDS,
            max_commands=remaining_capacity,
        )
    else:
        stranded = []

    recovered = orphaned + stranded
    if not recovered:
        logger.debug("[COMMAND-REAPER] No orphaned or stranded commands found")
        return 0

    if orphaned:
        logger.warning(
            "[COMMAND-REAPER] Found %d orphaned active command(s); re-publishing",
            len(orphaned),
        )
    if stranded:
        logger.warning(
            "[COMMAND-REAPER] Found %d stranded pending command(s); re-publishing",
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
                tool_kind=cmd.get("tool_kind"),
                playbook_path=cmd.get("playbook_path"),
            )
            republished += 1
            logger.info(
                "[COMMAND-REAPER] Re-published execution_id=%s command_id=%s step=%s",
                cmd["execution_id"],
                cmd["command_id"],
                cmd["step"],
            )
        except Exception as pub_err:
            logger.error(
                "[COMMAND-REAPER] Failed to re-publish execution_id=%s event_id=%s command_id=%s: %s",
                cmd.get("execution_id"),
                cmd.get("event_id"),
                cmd.get("command_id"),
                pub_err,
                exc_info=True,
            )

    logger.info(
        "[COMMAND-REAPER] Re-published %d/%d recovered commands",
        republished,
        len(recovered),
    )
    return republished


async def run_command_reaper(
    *,
    stop_event: asyncio.Event,
    server_url: str,
    lease,
) -> None:
    """
    Background task: periodically sweep ``noetl.command`` for stale
    non-terminal rows and republish their NATS notification.

    A ``RuntimeLease`` (see :mod:`noetl.server.runtime_leases`) is required
    so that exactly one server instance performs recovery even when several
    API replicas are running. ``lease`` must expose
    ``try_acquire_or_renew()`` returning an object with an ``acquired``
    boolean attribute and an async ``release()`` method.

    The loop exits cleanly when ``stop_event`` is set or the task is
    cancelled.
    """
    if not _REAPER_ENABLED:
        logger.info("[COMMAND-REAPER] Disabled via NOETL_COMMAND_REAPER_ENABLED=false")
        return

    logger.info(
        "[COMMAND-REAPER] Started (interval=%.0fs, worker_stale=%.0fs, hard_timeout=%.0fs, "
        "pending_retry=%.0fs, max_per_run=%d)",
        _REAPER_INTERVAL_SECONDS,
        _REAPER_WORKER_STALE_SECONDS,
        _REAPER_HEALTHY_HARD_TIMEOUT_SECONDS,
        _REAPER_PENDING_RETRY_SECONDS,
        _REAPER_MAX_PER_RUN,
    )

    try:
        while not stop_event.is_set():
            try:
                lease_state = await lease.try_acquire_or_renew()
                if getattr(lease_state, "acquired", False):
                    try:
                        await reap_orphaned_commands_once(server_url)
                    except asyncio.CancelledError:
                        raise
                    except Exception as scan_err:
                        logger.error(
                            "[COMMAND-REAPER] Scan failed: %s",
                            scan_err,
                            exc_info=True,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as outer_err:
                logger.exception("[COMMAND-REAPER] Loop error: %s", outer_err)

            try:
                await asyncio.sleep(_REAPER_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                logger.info("[COMMAND-REAPER] Cancelled during sleep; exiting")
                break
    finally:
        try:
            await lease.release()
        except Exception:  # pragma: no cover - best-effort release
            pass
