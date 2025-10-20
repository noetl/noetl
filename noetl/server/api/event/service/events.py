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
    ctx: Dict[str, Any],
    parent_event_id: str = None
) -> str:
    """
    Emit step_started event if not already emitted.
    
    Returns:
        event_id of the emitted step_started event
    """
    
    # Check if already emitted
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT event_id FROM noetl.event
                WHERE execution_id = %s AND node_name = %s AND event_type = 'step_started'
                LIMIT 1
                """,
                (execution_id, step_name)
            )
            row = await cur.fetchone()
            if row:
                logger.debug(f"EVENTS: step_started already emitted for {step_name}")
                return str(row[0])
    
    # Emit event
    try:
        event_data = {
            'execution_id': execution_id,
            'event_type': 'step_started',
            'node_name': step_name,
            'node_type': 'step',
            'status': 'RUNNING',
            'context': ctx
        }
        if parent_event_id:
            event_data['parent_event_id'] = parent_event_id
            
        result = await get_event_service().emit(event_data)
        event_id = result.get('event_id')
        logger.info(f"EVENTS: Emitted step_started for {step_name}, event_id={event_id}")
        return event_id
    except Exception as e:
        logger.warning(f"EVENTS: Failed to emit step_started for {step_name}: {e}")
        return None


async def emit_step_completed(
    execution_id: str,
    step_name: str,
    parent_event_id: str = None
) -> str:
    """
    Emit step_completed event if not already emitted.
    
    Args:
        execution_id: Execution ID
        step_name: Step name
        parent_event_id: Parent event ID (typically action_completed or step_result)
        
    Returns:
        event_id of the emitted or existing step_completed event
    """
    
    # Check if already emitted
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT event_id FROM noetl.event
                WHERE execution_id = %s AND node_name = %s AND event_type = 'step_completed'
                LIMIT 1
                """,
                (execution_id, step_name)
            )
            existing_row = await cur.fetchone()
            if existing_row:
                logger.debug(f"EVENTS: step_completed already emitted for {step_name}")
                return existing_row[0]
            
            # If no parent_event_id provided, query for it (fallback)
            if not parent_event_id:
                await cur.execute(
                    """
                    SELECT event_id FROM noetl.event
                    WHERE execution_id = %s 
                      AND node_name = %s 
                      AND event_type IN ('action_completed', 'step_result')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (execution_id, step_name)
                )
                row = await cur.fetchone()
                if row:
                    parent_event_id = row[0]
    
    # Emit event
    try:
        event_data = {
            'execution_id': execution_id,
            'event_type': 'step_completed',
            'node_name': step_name,
            'node_type': 'step',
            'status': 'COMPLETED',
            'context': {'step_name': step_name}
        }
        if parent_event_id:
            event_data['parent_event_id'] = parent_event_id
            
        result = await get_event_service().emit(event_data)
        emitted_event_id = result.get('event_id') if result else None
        logger.info(f"EVENTS: Emitted step_completed for {step_name} with parent={parent_event_id}, event_id={emitted_event_id}")
        return emitted_event_id
    except Exception as e:
        logger.warning(f"EVENTS: Failed to emit step_completed for {step_name}: {e}")
        return None

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
