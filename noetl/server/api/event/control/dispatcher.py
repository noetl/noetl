from __future__ import annotations

from typing import Any, Dict
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def route_event(event: Dict[str, Any]) -> bool:
    """Route a just-persisted event to the appropriate controller.

    Returns True if a controller handled orchestration for this event.
    """
    try:
        et = str(event.get('event_type') or '').lower()
        nt = str(event.get('node_type') or '').lower()
        # Normalize common aliases
        if et == 'execution_started':
            et = 'execution_start'
        if et == 'execution_completed':
            et = 'execution_complete'

        # Dispatch map by event_type first
        if et in {'execution_start', 'execution_complete'}:
            from .playbook import handle_playbook_event
            await handle_playbook_event(event, et)
            return True

        if et in {'step_started', 'step_completed'}:
            from .step import handle_step_event
            await handle_step_event(event, et)
            return True

        if et in {'loop_iteration', 'loop_completed', 'end_loop'}:
            from .loop import handle_loop_event
            await handle_loop_event(event, et)
            return True

        if et in {'action_started', 'action_completed', 'action_error', 'result'}:
            from .action import handle_action_event
            await handle_action_event(event, et)
            return True

        # Workbook-specific events could be added later (e.g., workbook_started/completed)
        if nt == 'workbook':
            from .workbook import handle_workbook_event
            await handle_workbook_event(event, et)
            return True

        logger.debug(f"DISPATCHER: No specific handler for event_type={et} node_type={nt}")
        return False
    except Exception:
        logger.debug("DISPATCHER: Route event failed", exc_info=True)
        return False

