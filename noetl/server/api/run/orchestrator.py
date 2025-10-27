"""
Execution Orchestrator - Event-driven workflow coordination.

Architecture:
1. Worker executes task → Reports result as EVENT via /api/v1/event/emit
2. Event endpoint triggers orchestrator.evaluate_execution()
3. Orchestrator reconstructs state from events
4. Orchestrator publishes next actionable tasks to QUEUE
5. Workers pick up tasks from queue and repeat cycle

Flow:
- Initial: Dispatch first workflow step to queue
- In Progress: Analyze events, evaluate transitions, publish next steps to queue
- Completed: Mark execution finished

Pure event sourcing - NO business logic in events, orchestrator decides everything.
"""

from typing import Optional, Dict, Any
from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def evaluate_execution(
    execution_id: str,
    trigger_event_type: Optional[str] = None,
    trigger_event_id: Optional[str] = None
) -> None:
    """
    Main orchestrator - analyzes events and publishes actionable tasks to queue.
    
    Called by:
    - /api/v1/event/emit endpoint after worker reports results
    - Initial execution start (from /api/v1/run)
    
    Workflow:
    1. Read all events for execution_id from event table
    2. Reconstruct current execution state
    3. Determine what tasks are needed next
    4. Publish tasks to queue table for workers
    
    Args:
        execution_id: Execution to orchestrate
        trigger_event_type: Event type that triggered this call
        trigger_event_id: Event ID that triggered this call
    
    Event triggers:
        - execution_start: Publish first step to queue
        - step_end/action_completed: Analyze results, publish next steps
        - error/failed: Handle failures
    """
    # Convert execution_id to int for database queries
    try:
        exec_id = int(execution_id)
    except (ValueError, TypeError):
        logger.error(f"Invalid execution_id format: {execution_id}")
        return
    
    logger.info(
        f"ORCHESTRATOR: Evaluating execution_id={exec_id}, "
        f"trigger={trigger_event_type}, event_id={trigger_event_id}"
    )
    
    # Ignore progress marker events - they don't trigger orchestration
    if trigger_event_type in ('step_started', 'step_running'):
        logger.debug(f"ORCHESTRATOR: Ignoring progress marker event {trigger_event_type}")
        return
    
    try:
        # Check for failure states
        if await _has_failed(exec_id):
            logger.info(f"ORCHESTRATOR: Execution {exec_id} has failed, stopping orchestration")
            return
        
        # Reconstruct execution state from events
        state = await _get_execution_state(exec_id)
        logger.debug(f"ORCHESTRATOR: Execution {exec_id} state={state}")
        
        if state == 'initial':
            # No progress yet - dispatch first workflow step
            logger.info(f"ORCHESTRATOR: Dispatching initial step for execution {exec_id}")
            await _dispatch_first_step(exec_id)
            
        elif state == 'in_progress':
            # Steps are running - process completions and transitions
            # Only process transitions for actionable events
            if trigger_event_type in ('action_completed', 'step_result', 'step_end'):
                logger.info(f"ORCHESTRATOR: Processing transitions for execution {exec_id}")
                await _process_transitions(exec_id)
            else:
                logger.debug(f"ORCHESTRATOR: No transition processing needed for {trigger_event_type}")
            
            # Check for iterator completions (child executions)
            if trigger_event_type in ('execution_complete', 'execution_end', 'action_completed'):
                logger.debug(f"ORCHESTRATOR: Checking iterator completions for execution {exec_id}")
                await _check_iterator_completions(exec_id)
        
        elif state == 'completed':
            logger.debug(f"ORCHESTRATOR: Execution {exec_id} already completed, no action needed")
        
        logger.debug(f"ORCHESTRATOR: Evaluation complete for execution {exec_id}")
        
    except Exception as e:
        logger.error(f"ORCHESTRATOR: Error evaluating execution {exec_id}: {e}", exc_info=True)
        # Don't re-raise - orchestrator errors shouldn't break the system


async def _has_failed(execution_id: int) -> bool:
    """
    Check if execution has encountered failure by examining event log.
    
    Args:
        execution_id: Execution to check
        
    Returns:
        True if any failure/error events exist
    """
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND (
                    LOWER(status) LIKE '%%failed%%'
                    OR LOWER(status) LIKE '%%error%%'
                    OR event_type = 'error'
                  )
                LIMIT 1
                """,
                {"execution_id": execution_id}
            )
            return await cur.fetchone() is not None


async def _get_execution_state(execution_id: int) -> str:
    """
    Reconstruct execution state from event log.
    
    State reconstruction logic:
    1. Check for execution_complete/execution_end events -> 'completed'
    2. Check for any action_completed events -> 'in_progress'
    3. Check for queued/leased jobs -> 'in_progress'
    4. Otherwise -> 'initial'
    
    Args:
        execution_id: Execution to check
        
    Returns:
        State: 'initial', 'in_progress', or 'completed'
    """
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            # Check for completion
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('execution_complete', 'execution_end')
                LIMIT 1
                """,
                {"execution_id": execution_id}
            )
            if await cur.fetchone():
                return 'completed'
            
            # Check for any completed actions
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('action_completed', 'step_end')
                LIMIT 1
                """,
                {"execution_id": execution_id}
            )
            if await cur.fetchone():
                return 'in_progress'
            
            # Check for active queue items
            await cur.execute(
                """
                SELECT 1 FROM noetl.queue
                WHERE execution_id = %(execution_id)s
                  AND status IN ('queued', 'leased')
                LIMIT 1
                """,
                {"execution_id": execution_id}
            )
            if await cur.fetchone():
                return 'in_progress'
            
            return 'initial'


async def _dispatch_first_step(execution_id: str) -> None:
    """
    Publish first workflow step to queue for worker execution.
    
    Process:
    1. Query workflow table for step where step_name = 'start'
    2. Create actionable task (job) in queue table
    3. Worker will pick it up, execute, and report result via event endpoint
    
    TODO: Implement workflow query and queue publishing
    """
    logger.info(f"Dispatching first step for execution {execution_id}")
    # TODO: Query workflow table to find 'start' step
    # TODO: Use QueuePublisher to publish step to queue
    # Workers will execute and report results back via /api/v1/event/emit
    pass


async def _process_transitions(execution_id: str) -> None:
    """
    Analyze completed steps and publish next actionable tasks to queue.
    
    Process:
    1. Query events to find completed steps
    2. Query transition table for matching step completions
    3. Evaluate Jinja2 conditions in transitions
    4. Publish next steps to queue table as actionable tasks
    5. Workers execute and report results back via events
    
    TODO: Implement transition evaluation and queue publishing
    """
    logger.info(f"Processing transitions for execution {execution_id}")
    # TODO: Query events for step_end/action_completed events
    # TODO: Query transition table for next steps
    # TODO: Evaluate Jinja2 'when' conditions
    # TODO: Publish next steps to queue
    # Workers will execute and report results back via /api/v1/event/emit
    pass


async def _check_iterator_completions(execution_id: str) -> None:
    """
    Aggregate child execution results and continue parent workflow.
    
    Process:
    1. Find parent iterator execution relationships
    2. Count completed child executions vs total expected
    3. When all children complete, aggregate results
    4. Publish parent's next step to queue
    5. Worker executes parent continuation and reports via events
    
    TODO: Implement child execution aggregation and parent continuation
    """
    logger.info(f"Checking iterator completions for execution {execution_id}")
    # TODO: Find iterator parent-child relationships
    # TODO: Count child execution completions
    # TODO: Aggregate results when all children done
    # TODO: Publish parent next step to queue
    # Workers will execute parent continuation and report via /api/v1/event/emit
    pass


__all__ = ["evaluate_execution"]
