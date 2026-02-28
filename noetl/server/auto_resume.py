"""
Auto-resume interrupted playbook executions.

When NoETL server restarts (e.g., pod restart in Kubernetes), this module
checks for interrupted executions and automatically resumes them using event replay.
"""

import asyncio
from typing import Optional, List, Dict, Any
from psycopg.rows import dict_row
from psycopg.types.json import Json

from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def get_execution_status(execution_id: int) -> str:
    """
    Determine execution status by analyzing events.

    Returns:
        - "completed": playbook finished successfully
        - "failed": playbook failed with error
        - "cancelled": playbook was cancelled by user
        - "running": execution in progress (or interrupted)
    """
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Check for terminal events (completion, failure, cancellation)
            await cur.execute("""
                SELECT event_type, status
                FROM noetl.event
                WHERE execution_id = %s
                  AND event_type IN ('playbook.completed', 'playbook.failed', 'execution.cancelled')
                ORDER BY created_at DESC
                LIMIT 1
            """, (execution_id,))

            row = await cur.fetchone()
            if row:
                if row['event_type'] == 'playbook.completed':
                    return "completed"
                if row['event_type'] == 'playbook.failed':
                    return "failed"
                if row['event_type'] == 'execution.cancelled':
                    return "cancelled"

            # Check if there are any FAILED or CANCELLED status events
            await cur.execute("""
                SELECT status
                FROM noetl.event
                WHERE execution_id = %s
                  AND status IN ('FAILED', 'CANCELLED')
                ORDER BY created_at DESC
                LIMIT 1
            """, (execution_id,))

            row = await cur.fetchone()
            if row:
                if row['status'] == 'FAILED':
                    return "failed"
                if row['status'] == 'CANCELLED':
                    return "cancelled"

            # Otherwise, it's running (or interrupted)
            return "running"


async def get_last_execution() -> Optional[Dict[str, Any]]:
    """
    Get the most recent execution that might be interrupted (within last 5 minutes).

    Only returns executions from the last 5 minutes to avoid restarting old jobs.
    Returns: {execution_id, path, catalog_id, created_at}
    """
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT
                    e.execution_id,
                    c.path,
                    e.catalog_id,
                    e.created_at
                FROM noetl.event e
                JOIN noetl.catalog c ON c.catalog_id = e.catalog_id
                WHERE e.event_type = 'playbook.initialized'
                  AND e.created_at > NOW() - INTERVAL '5 minutes'
                ORDER BY e.created_at DESC
                LIMIT 1
            """)

            return await cur.fetchone()


async def mark_execution_cancelled(execution_id: int, reason: str = "Server restart") -> bool:
    """
    Mark an execution as cancelled due to server interruption.

    Args:
        execution_id: The execution to cancel
        reason: Cancellation reason

    Returns:
        True if marked successfully, False otherwise
    """
    try:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT catalog_id
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id ASC
                    LIMIT 1
                    """,
                    (execution_id,),
                )
                row = await cur.fetchone()
                if not row or not row.get("catalog_id"):
                    logger.warning(
                        "[AUTO-RESUME] Could not resolve catalog_id for execution %s; skipping cancel marker",
                        execution_id,
                    )
                    return False

                event_id = await get_snowflake_id()
                cancel_payload = {"reason": reason, "auto_cancelled": True}
                cancel_meta = {
                    "actionable": False,
                    "informative": True,
                    "auto_resume": True,
                }
                await cur.execute("""
                    INSERT INTO noetl.event (
                        execution_id, catalog_id, event_id, event_type,
                        node_id, node_name, status, result, meta, created_at
                    ) VALUES (
                        %s, %s, %s, 'execution.cancelled',
                        %s, %s, 'CANCELLED', %s, %s, NOW()
                    )
                """, (
                    execution_id,
                    row["catalog_id"],
                    int(event_id),
                    "workflow",
                    "workflow",
                    Json({"kind": "data", "data": cancel_payload}),
                    Json(cancel_meta),
                ))
                await conn.commit()

        logger.info(f"[AUTO-RESUME] Marked execution {execution_id} as CANCELLED")
        return True

    except Exception as e:
        logger.error(f"[AUTO-RESUME] Failed to mark execution {execution_id} as cancelled: {e}")
        return False


async def resume_execution(execution_id: int, path: str, catalog_id: int) -> bool:
    """
    Resume an interrupted execution by marking it cancelled and optionally restarting.

    IMPORTANT: We do NOT automatically restart playbooks anymore. Instead, we mark
    interrupted executions as CANCELLED to clean up the state. Users can manually
    restart if needed.

    Args:
        execution_id: The interrupted execution ID
        path: Playbook path
        catalog_id: Catalog ID of the playbook

    Returns:
        True if cancellation was successful, False otherwise
    """
    try:
        logger.info(f"[AUTO-RESUME] Marking interrupted execution {execution_id} ({path}) as CANCELLED")

        # Mark the old execution as cancelled instead of leaving it stuck
        success = await mark_execution_cancelled(
            execution_id,
            reason="Server restart - execution was interrupted"
        )

        if success:
            logger.info(f"[AUTO-RESUME] Successfully cancelled interrupted execution {execution_id}")
        else:
            logger.warning(f"[AUTO-RESUME] Failed to cancel interrupted execution {execution_id}")

        return success

    except Exception as e:
        logger.error(f"[AUTO-RESUME] Failed to handle interrupted execution {execution_id}: {e}", exc_info=True)
        return False


async def resume_interrupted_executions():
    """
    Clean up interrupted executions on server restart.

    This is called on server startup to recover from pod restarts.
    Checks the most recent execution (within last 5 minutes) - if it's in 'running' state,
    marks it as CANCELLED to prevent stuck executions.

    NOTE: Playbooks are NOT automatically restarted. Users must manually re-execute
    if needed. This prevents duplicate executions and state confusion.
    """
    try:
        logger.info("[AUTO-RESUME] Checking for interrupted executions (last 5 minutes)...")

        # Get the most recent execution (within 5 minutes)
        last_execution = await get_last_execution()

        if not last_execution:
            logger.info("[AUTO-RESUME] No recent executions found (last 5 minutes)")
            return

        execution_id = last_execution['execution_id']
        path = last_execution['path']
        catalog_id = last_execution['catalog_id']

        # Check execution status
        status = await get_execution_status(execution_id)

        logger.info(f"[AUTO-RESUME] Last execution {execution_id} ({path}): status={status}")

        if status == "running":
            # This execution was interrupted - mark it as cancelled
            logger.info(f"[AUTO-RESUME] Cancelling interrupted execution {execution_id}")
            success = await resume_execution(execution_id, path, catalog_id)
            if success:
                logger.info("[AUTO-RESUME] Successfully cancelled interrupted execution")
            else:
                logger.warning("[AUTO-RESUME] Failed to cancel interrupted execution")
        else:
            # Already completed or failed - nothing to do
            logger.info(f"[AUTO-RESUME] Last execution already {status}, no action needed")

    except Exception as e:
        logger.error(f"[AUTO-RESUME] Critical error during auto-resume: {e}", exc_info=True)
