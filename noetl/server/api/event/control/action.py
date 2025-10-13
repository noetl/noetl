from __future__ import annotations

from typing import Any, Dict
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def handle_action_event(event: Dict[str, Any], et: str) -> None:
    try:
        execution_id = event.get('execution_id')
        if not execution_id:
            return
        # Action lifecycle should advance workflow
        from ..processing import evaluate_broker_for_execution
        trig = str(event.get('trigger_event_id') or event.get('event_id') or '') or None
        await evaluate_broker_for_execution(str(execution_id), trigger_event_id=trig)
    except Exception:
        logger.debug("ACTION_CONTROL: Failed handling action event", exc_info=True)
