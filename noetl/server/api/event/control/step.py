from __future__ import annotations

from typing import Any, Dict
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def handle_step_event(event: Dict[str, Any], et: str) -> None:
    try:
        execution_id = event.get('execution_id')
        step_name = event.get('node_name')
        if not execution_id or not step_name:
            return
        # For step_started/step_completed we can (re)run a narrow broker evaluation
        from ..processing import evaluate_broker_for_execution
        trig = str(event.get('trigger_event_id') or event.get('event_id') or '') or None
        await evaluate_broker_for_execution(str(execution_id), trigger_event_id=trig)
    except Exception:
        logger.debug("STEP_CONTROL: Failed handling step event", exc_info=True)
