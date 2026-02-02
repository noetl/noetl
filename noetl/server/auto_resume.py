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
    Get the most recent execution overall (across all playbooks).

    Returns the single most recent execution, or None if no executions found.
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
                ORDER BY e.created_at DESC
                LIMIT 1
            """)

            return await cur.fetchone()


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
    Only checks the most recent execution overall - if it's in 'running' state,
    restarts it.
    """
    try:
        logger.info("[AUTO-RESUME] Checking for interrupted executions...")

        # Get the most recent execution
        last_execution = await get_last_execution()

        if not last_execution:
            logger.info("[AUTO-RESUME] No executions found")
            return

        execution_id = last_execution['execution_id']
        path = last_execution['path']
        catalog_id = last_execution['catalog_id']

        # Check execution status
        status = await get_execution_status(execution_id)

        logger.info(f"[AUTO-RESUME] Last execution {execution_id} ({path}): status={status}")

        if status == "running":
            # This execution was interrupted - restart it
            logger.info(f"[AUTO-RESUME] Restarting interrupted execution {execution_id}")
            success = await resume_execution(execution_id, path, catalog_id)
            if success:
                logger.info("[AUTO-RESUME] Successfully restarted interrupted playbook")
            else:
                logger.warning("[AUTO-RESUME] Failed to restart interrupted playbook")
        else:
            # Already completed or failed - nothing to do
            logger.info(f"[AUTO-RESUME] Last execution already {status}, no action needed")

    except Exception as e:
        logger.error(f"[AUTO-RESUME] Critical error during auto-resume: {e}", exc_info=True)
