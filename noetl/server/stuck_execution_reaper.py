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
                WITH stale AS (
                    SELECT
                        e.execution_id,
                        MIN(e.catalog_id) FILTER (WHERE e.catalog_id IS NOT NULL) AS catalog_id,
                        MIN(e.created_at) AS first_event_at,
                        MAX(e.created_at) AS last_event_at
                    FROM noetl.event e
                    GROUP BY e.execution_id
                    HAVING MAX(e.created_at) < NOW() - (%s * INTERVAL '1 minute')
                )
                SELECT
                    stale.execution_id,
                    stale.catalog_id,
                    stale.first_event_at,
                    stale.last_event_at
                FROM stale
                WHERE stale.catalog_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM noetl.event started
                      WHERE started.execution_id = stale.execution_id
                        AND started.event_type = 'playbook.initialized'
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM noetl.event terminal
                      WHERE terminal.execution_id = stale.execution_id
                        AND terminal.event_type = ANY(%s)
                  )
                ORDER BY stale.last_event_at ASC, stale.execution_id ASC
                LIMIT %s
                """,
                (inactivity_minutes, _TERMINAL_EXECUTION_EVENT_TYPES, max_executions),
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
    inactivity_minutes = int(inactivity_minutes or _STUCK_EXECUTION_REAPER_INACTIVITY_MINUTES)
    max_executions = int(max_executions or _STUCK_EXECUTION_REAPER_MAX_PER_RUN)
    candidates = await _find_inactive_executions(
        inactivity_minutes=inactivity_minutes,
        max_executions=max_executions,
    )
    execution_ids = [str(row["execution_id"]) for row in candidates]
    if dry_run or not candidates:
        return {
            "cancelled_count": 0 if dry_run is False else len(execution_ids),
            "execution_ids": execution_ids,
            "dry_run": dry_run,
        }

    async with get_pool_connection(timeout=5.0) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            for row in candidates:
                event_id = int(await get_snowflake_id())
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
        "execution_ids": execution_ids,
        "dry_run": False,
    }
