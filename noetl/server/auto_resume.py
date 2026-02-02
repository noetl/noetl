"""
Auto-resume interrupted playbook executions.

When NoETL server restarts (e.g., pod restart in Kubernetes), this module
checks for interrupted executions and automatically resumes them using event replay.
"""

import asyncio
from typing import Optional, List, Dict, Any
from psycopg.rows import dict_row

from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def get_execution_status(execution_id: int) -> str:
    """
    Determine execution status by analyzing events.

    Returns:
        - "completed": playbook finished successfully
        - "failed": playbook failed with error
        - "running": execution in progress (or interrupted)
    """
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Check for completion/failure events
            await cur.execute("""
                SELECT event_type, status
                FROM noetl.event
                WHERE execution_id = %s
                  AND event_type IN ('playbook.completed', 'playbook.failed')
                ORDER BY created_at DESC
                LIMIT 1
            """, (execution_id,))

            row = await cur.fetchone()
            if row:
                if row['event_type'] == 'playbook.completed':
                    return "completed"
                if row['event_type'] == 'playbook.failed':
                    return "failed"

            # Check if there are any FAILED status events
            await cur.execute("""
                SELECT 1
                FROM noetl.event
                WHERE execution_id = %s
                  AND status = 'FAILED'
                LIMIT 1
            """, (execution_id,))

            if await cur.fetchone():
                return "failed"

            # Otherwise, it's running (or interrupted)
            return "running"


async def get_last_execution_per_playbook() -> List[Dict[str, Any]]:
    """
    Get the most recent execution for each unique playbook (path).

    Returns list of {execution_id, path, catalog_id, created_at}
    """
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                WITH latest_executions AS (
                    SELECT
                        execution_id,
                        catalog_id,
                        created_at,
                        ROW_NUMBER() OVER (PARTITION BY catalog_id ORDER BY created_at DESC) as rn
                    FROM noetl.event
                    WHERE event_type = 'playbook.initialized'
                )
                SELECT
                    le.execution_id,
                    c.path,
                    le.catalog_id,
                    le.created_at
                FROM latest_executions le
                JOIN noetl.catalog c ON c.catalog_id = le.catalog_id
                WHERE le.rn = 1
                ORDER BY le.created_at DESC
            """)

            return await cur.fetchall()


async def resume_execution(execution_id: int, path: str, catalog_id: int) -> bool:
    """
    Resume an interrupted execution by restarting the playbook.

    For interrupted executions (pod restart), we simply restart the playbook
    from the beginning. This is simpler and more reliable than trying to
    resume from the middle, especially for workflows with loops and iterators.

    Args:
        execution_id: The interrupted execution ID (for logging)
        path: Playbook path
        catalog_id: Catalog ID of the playbook

    Returns:
        True if restart was triggered successfully, False otherwise
    """
    try:
        # Import here to avoid circular dependency
        from noetl.server.api.v2 import execute, ExecuteRequest

        logger.info(f"[AUTO-RESUME] Restarting interrupted execution {execution_id} for playbook: {path}")

        # Create execute request
        request = ExecuteRequest(
            path=path,
            payload={}  # Use default workload from playbook
        )

        # Restart the playbook from the beginning
        # This is simpler than trying to resume from the middle
        result = await execute(request)

        logger.info(f"[AUTO-RESUME] Successfully restarted playbook {path} with new execution {result.execution_id}")
        return True

    except Exception as e:
        logger.error(f"[AUTO-RESUME] Failed to restart playbook {path}: {e}", exc_info=True)
        return False


async def resume_interrupted_executions():
    """
    Check for interrupted executions and automatically resume them.

    This is called on server startup to recover from pod restarts.
    Only resumes the LAST execution of each playbook if it's in 'running' state.
    """
    try:
        logger.info("[AUTO-RESUME] Checking for interrupted executions...")

        # Get last execution for each playbook
        executions = await get_last_execution_per_playbook()

        if not executions:
            logger.info("[AUTO-RESUME] No executions found")
            return

        logger.info(f"[AUTO-RESUME] Found {len(executions)} unique playbooks with executions")

        resumed_count = 0
        skipped_count = 0

        for exec_info in executions:
            execution_id = exec_info['execution_id']
            path = exec_info['path']

            # Check execution status
            status = await get_execution_status(execution_id)

            logger.debug(f"[AUTO-RESUME] Execution {execution_id} ({path}): status={status}")

            if status == "running":
                # This execution was interrupted - restart it
                catalog_id = exec_info['catalog_id']
                success = await resume_execution(execution_id, path, catalog_id)
                if success:
                    resumed_count += 1
                else:
                    skipped_count += 1
            else:
                # Already completed or failed - skip
                logger.debug(f"[AUTO-RESUME] Skipping execution {execution_id} ({path}): {status}")
                skipped_count += 1

        logger.info(f"[AUTO-RESUME] Completed: {resumed_count} resumed, {skipped_count} skipped")

    except Exception as e:
        logger.error(f"[AUTO-RESUME] Critical error during auto-resume: {e}", exc_info=True)
