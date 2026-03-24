"""
Periodic cleanup for executions that have gone inactive without a terminal event.

This targets abnormal situations where an execution is left RUNNING but no new
events arrive for a long period. In that state the execution can continue to
feed queue churn via orphaned claims and publish recovery even though it is no
longer making forward progress.

Environment variables:
  NOETL_STUCK_EXECUTION_REAPER_ENABLED           - true/false (default: true)
  NOETL_STUCK_EXECUTION_REAPER_INTERVAL_SECONDS  - scan frequency (default: 300)
  NOETL_STUCK_EXECUTION_REAPER_INACTIVITY_MINUTES
                                                 - inactivity window before cancel
                                                   (default: 120)
  NOETL_STUCK_EXECUTION_REAPER_MAX_PER_RUN       - max executions cancelled per cycle
                                                   (default: 25)
"""

from __future__ import annotations

import os
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json

from noetl.core.common import get_snowflake_id
from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

_STUCK_EXECUTION_REAPER_ENABLED = os.getenv(
    "NOETL_STUCK_EXECUTION_REAPER_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}
_STUCK_EXECUTION_REAPER_INTERVAL_SECONDS = max(
    30.0, float(os.getenv("NOETL_STUCK_EXECUTION_REAPER_INTERVAL_SECONDS", "300"))
)
_STUCK_EXECUTION_REAPER_INACTIVITY_MINUTES = max(
    15, int(os.getenv("NOETL_STUCK_EXECUTION_REAPER_INACTIVITY_MINUTES", "120"))
)
_STUCK_EXECUTION_REAPER_MAX_PER_RUN = max(
    1, int(os.getenv("NOETL_STUCK_EXECUTION_REAPER_MAX_PER_RUN", "25"))
)

_TERMINAL_EXECUTION_EVENT_TYPES = [
    "playbook.completed",
    "workflow.completed",
    "playbook.failed",
    "workflow.failed",
    "execution.cancelled",
]


def is_stuck_execution_reaper_enabled() -> bool:
    return _STUCK_EXECUTION_REAPER_ENABLED


def get_stuck_execution_reaper_interval_seconds() -> float:
    return _STUCK_EXECUTION_REAPER_INTERVAL_SECONDS


async def _find_inactive_executions(
    inactivity_minutes: int,
    max_executions: int,
) -> list[dict[str, Any]]:
    async with get_pool_connection(timeout=5.0) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                WITH candidate_exec AS (
                    SELECT DISTINCT e.execution_id
                    FROM noetl.event e
                    WHERE e.event_type = 'playbook.initialized'
                      AND e.created_at < NOW() - (%s * INTERVAL '1 minute')
                ),
                stale AS (
                    SELECT
                        c.execution_id,
                        started.first_event_at,
                        latest.catalog_id,
                        latest.last_event_at
                    FROM candidate_exec c
                    JOIN LATERAL (
                        SELECT MIN(e.created_at) AS first_event_at
                        FROM noetl.event e
                        WHERE e.execution_id = c.execution_id
                          AND e.event_type = 'playbook.initialized'
                    ) AS started ON TRUE
                    JOIN LATERAL (
                        SELECT
                            e.catalog_id,
                            e.created_at AS last_event_at
                        FROM noetl.event e
                        WHERE e.execution_id = c.execution_id
                        ORDER BY e.event_id DESC
                        LIMIT 1
                    ) AS latest ON TRUE
                    WHERE latest.last_event_at < NOW() - (%s * INTERVAL '1 minute')
                )
                SELECT
                    stale.execution_id,
                    stale.catalog_id,
                    stale.first_event_at,
                    stale.last_event_at
                FROM stale
                WHERE stale.catalog_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM noetl.event terminal
                      WHERE terminal.execution_id = stale.execution_id
                        AND terminal.event_type = ANY(%s)
                  )
                ORDER BY stale.last_event_at ASC, stale.execution_id ASC
                LIMIT %s
                """,
                (
                    inactivity_minutes,
                    inactivity_minutes,
                    _TERMINAL_EXECUTION_EVENT_TYPES,
                    max_executions,
                ),
            )
            rows = await cur.fetchall()
    return list(rows or [])


async def cleanup_inactive_executions_once(
    inactivity_minutes: int | None = None,
    max_executions: int | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not is_stuck_execution_reaper_enabled():
        return {
            "cancelled_count": 0,
            "execution_ids": [],
            "dry_run": dry_run,
            "disabled": True,
        }
    if inactivity_minutes is None:
        inactivity_minutes = int(_STUCK_EXECUTION_REAPER_INACTIVITY_MINUTES)
    else:
        inactivity_minutes = int(inactivity_minutes)
    if max_executions is None:
        max_executions = int(_STUCK_EXECUTION_REAPER_MAX_PER_RUN)
    else:
        max_executions = int(max_executions)
    if inactivity_minutes <= 0 or max_executions <= 0:
        return {
            "cancelled_count": 0,
            "candidate_count": 0,
            "execution_ids": [],
            "dry_run": dry_run,
            "invalid_params": True,
        }
    candidates = await _find_inactive_executions(
        inactivity_minutes=inactivity_minutes,
        max_executions=max_executions,
    )
    execution_ids = [str(row["execution_id"]) for row in candidates]
    if dry_run or not candidates:
        return {
            "cancelled_count": 0,
            "candidate_count": len(execution_ids),
            "execution_ids": execution_ids,
            "dry_run": dry_run,
        }

    async with get_pool_connection(timeout=5.0) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            for row in candidates:
                event_id = int(get_snowflake_id())
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        execution_id, catalog_id, event_id, event_type,
                        node_id, node_name, status, result, meta, created_at
                    ) VALUES (
                        %s, %s, %s, 'execution.cancelled',
                        %s, %s, 'CANCELLED', %s, %s, NOW()
                    )
                    """,
                    (
                        row["execution_id"],
                        row["catalog_id"],
                        event_id,
                        "workflow",
                        "workflow",
                        Json(
                            {
                                "kind": "data",
                                "data": {
                                    "reason": (
                                        "Auto-cancelled after execution inactivity "
                                        f"for {inactivity_minutes} minutes"
                                    ),
                                    "auto_cancelled": True,
                                    "stuck_execution_reaper": True,
                                },
                            }
                        ),
                        Json(
                            {
                                "actionable": False,
                                "informative": True,
                                "stuck_execution_reaper": True,
                                "inactivity_minutes": inactivity_minutes,
                            }
                        ),
                    ),
                )
            await conn.commit()

    logger.warning(
        "[STUCK-REAPER] Cancelled %d inactive execution(s) after %d minute inactivity: %s",
        len(execution_ids),
        inactivity_minutes,
        ", ".join(execution_ids),
    )
    return {
        "cancelled_count": len(execution_ids),
        "candidate_count": len(execution_ids),
        "execution_ids": execution_ids,
        "dry_run": False,
    }
