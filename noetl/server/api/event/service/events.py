"""
Event emission utilities.

Centralized event emission with deduplication.
"""

from typing import Dict, Any
from noetl.core.common import get_async_db_connection
from noetl.core.logger import setup_logger
from ..service import get_event_service

logger = setup_logger(__name__, include_location=True)


async def emit_step_started(
    execution_id: str,
    step_name: str,
    ctx: Dict[str, Any]
) -> None:
    """Emit step_started event if not already emitted."""
    
    # Check if already emitted
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %s AND node_name = %s AND event_type = 'step_started'
                LIMIT 1
                """,
                (execution_id, step_name)
            )
            if await cur.fetchone():
                logger.debug(f"EVENTS: step_started already emitted for {step_name}")
                return
    
    # Emit event
    try:
        await get_event_service().emit({
            'execution_id': execution_id,
            'event_type': 'step_started',
            'node_name': step_name,
            'node_type': 'step',
            'status': 'RUNNING',
            'context': ctx
        })
        logger.info(f"EVENTS: Emitted step_started for {step_name}")
    except Exception as e:
        logger.warning(f"EVENTS: Failed to emit step_started for {step_name}: {e}")


async def emit_step_completed(
    execution_id: str,
    step_name: str
) -> None:
    """Emit step_completed event if not already emitted."""
    
    # Check if already emitted
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %s AND node_name = %s AND event_type = 'step_completed'
                LIMIT 1
                """,
                (execution_id, step_name)
            )
            if await cur.fetchone():
                logger.debug(f"EVENTS: step_completed already emitted for {step_name}")
                return
    
    # Emit event
    try:
        await get_event_service().emit({
            'execution_id': execution_id,
            'event_type': 'step_completed',
            'node_name': step_name,
            'node_type': 'step',
            'status': 'COMPLETED',
            'context': {'step_name': step_name}
        })
        logger.info(f"EVENTS: Emitted step_completed for {step_name}")
    except Exception as e:
        logger.warning(f"EVENTS: Failed to emit step_completed for {step_name}: {e}")


async def emit_execution_complete(
    execution_id: str,
    step_name: str,
    result: Any
) -> None:
    """Emit execution_complete event."""
    
    try:
        await get_event_service().emit({
            'execution_id': execution_id,
            'event_type': 'execution_complete',
            'status': 'COMPLETED',
            'node_name': step_name,
            'node_type': 'playbook',
            'result': result,
            'context': {'reason': 'workflow_complete'}
        })
        logger.info(f"EVENTS: Emitted execution_complete")
    except Exception as e:
        logger.error(f"EVENTS: Failed to emit execution_complete: {e}")
