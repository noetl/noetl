"""
Event dispatcher - routes events to appropriate handlers.

Single entry point for all event processing.
"""

from typing import Any, Dict
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def route_event(event: Dict[str, Any]) -> bool:
    """
    Route an event to the appropriate handler.
    
    Returns True if handled, False otherwise.
    """
    try:
        et = str(event.get('event_type') or '').lower()
        execution_id = event.get('execution_id')
        
        if not execution_id:
            logger.debug(f"DISPATCHER: Event {et} has no execution_id, skipping")
            return False
        
        # Normalize event type aliases
        if et == 'execution_started':
            et = 'execution_start'
        if et == 'execution_completed':
            et = 'execution_complete'
        
        logger.debug(f"DISPATCHER: Routing event_type={et} for execution={execution_id}")
        
        # Route to core broker for evaluation
        from .core import evaluate_execution
        await evaluate_execution(execution_id, trigger_event_type=et, trigger_event=event)
        
        return True
        
    except Exception as e:
        logger.error(f"DISPATCHER: Error routing event: {e}", exc_info=True)
        return False
