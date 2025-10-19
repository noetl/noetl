"""
Core broker logic - main execution evaluator.

Analyzes execution state and decides what to do next:
- Initial dispatch: Start first step
- Step completion: Evaluate transitions and enqueue next steps
- Error handling: Stop on failures
"""

from typing import Dict, Any, Optional
from noetl.core.common import get_async_db_connection
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def evaluate_execution(
    execution_id: str,
    trigger_event_type: Optional[str] = None,
    trigger_event: Optional[Dict[str, Any]] = None,
    trigger_event_id: Optional[str] = None  # Legacy parameter from event_service.py
) -> None:
    """
    Main broker entry point - evaluates execution state and takes appropriate action.
    
    Args:
        execution_id: Execution to evaluate
        trigger_event_type: Type of event that triggered this evaluation
        trigger_event: The event data that triggered this evaluation
        trigger_event_id: Event ID that triggered this evaluation (legacy)
    """
    # If only event_id was provided, fetch event type from database
    if trigger_event_id and not trigger_event_type:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT event_type FROM noetl.event WHERE event_id = %s",
                    (trigger_event_id,)
                )
                row = await cur.fetchone()
                if row:
                    trigger_event_type = row[0]
    
    logger.info(f"BROKER: Evaluating execution={execution_id} triggered_by={trigger_event_type}")
    
    # Ignore step_started events - they're progress markers, not orchestration triggers
    if trigger_event_type == 'step_started':
        logger.debug(f"BROKER: Ignoring step_started event for {execution_id} (progress marker only)")
        return
    
    try:
        # Check for failure states
        if await _has_failed(execution_id):
            logger.info(f"BROKER: Execution {execution_id} has failed, stopping")
            return
        
        # Determine execution state and take action
        state = await _get_execution_state(execution_id)
        
        if state == 'initial':
            # No progress yet - dispatch first step
            from .initial import dispatch_first_step
            await dispatch_first_step(execution_id)
            
        elif state == 'in_progress':
            # Steps have completed - process transitions
            # NOTE: Don't process transitions on step_completed since it's emitted AFTER transitions
            logger.info(f"BROKER: FIXED CODE - checking trigger_event_type={trigger_event_type}")
            if trigger_event_type in ('action_completed', 'step_result'):
                logger.info(f"BROKER: FIXED CODE - processing transitions for {trigger_event_type}")
                # Extract trigger event_id to pass as parent for step_completed
                trigger_evt_id = None
                if trigger_event:
                    trigger_evt_id = trigger_event.get('event_id')
                if not trigger_evt_id and trigger_event_id:
                    trigger_evt_id = trigger_event_id
                    
                from .transitions import process_completed_steps
                await process_completed_steps(execution_id, trigger_event_id=trigger_evt_id)
            else:
                logger.info(f"BROKER: FIXED CODE - skipping transitions for {trigger_event_type}")
            
            # Check for completed iterator child executions
            if trigger_event_type in ('execution_complete', 'action_completed'):
                from .iterators import check_iterator_completions
                await check_iterator_completions(execution_id)
        
        elif state == 'completed':
            logger.debug(f"BROKER: Execution {execution_id} already completed")
            
        logger.debug(f"BROKER: Evaluation complete for {execution_id}")
        
    except Exception as e:
        logger.error(f"BROKER: Error evaluating {execution_id}: {e}", exc_info=True)


async def _has_failed(execution_id: str) -> bool:
    """Check if execution has encountered failure."""
    from ..event_log import EventLog
    dao = EventLog()
    statuses = await dao.get_statuses(execution_id)
    
    for status in [str(s or '').lower() for s in statuses]:
        if 'failed' in status or 'error' in status:
            return True
    return False


async def _get_execution_state(execution_id: str) -> str:
    """
    Determine execution state.
    
    Returns: 'initial', 'in_progress', or 'completed'
    """
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            # Check for execution_complete
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %s AND event_type = 'execution_complete'
                LIMIT 1
                """,
                (execution_id,)
            )
            if await cur.fetchone():
                return 'completed'
            
            # Check for any action_completed events
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %s AND event_type = 'action_completed'
                LIMIT 1
                """,
                (execution_id,)
            )
            if await cur.fetchone():
                return 'in_progress'
            
            # Check for queued/leased jobs
            await cur.execute(
                """
                SELECT 1 FROM noetl.queue
                WHERE execution_id = %s AND status IN ('queued', 'leased')
                LIMIT 1
                """,
                (execution_id,)
            )
            if await cur.fetchone():
                return 'in_progress'
            
            return 'initial'
