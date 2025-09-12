from __future__ import annotations

from typing import Any, Dict
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def handle_playbook_event(event: Dict[str, Any], et: str) -> None:
    try:
        execution_id = event.get('execution_id')
        if not execution_id:
            return
        if et == 'execution_start':
            # Initial evaluation: enqueue first step, etc.
            from ..processing import evaluate_broker_for_execution
            await evaluate_broker_for_execution(str(execution_id))
        elif et == 'execution_complete':
            # Nothing to schedule by default; future: notify, cleanup, etc.
            logger.info(f"PLAYBOOK_CONTROL: Execution {execution_id} completed")
    except Exception:
        logger.debug("PLAYBOOK_CONTROL: Failed handling playbook event", exc_info=True)

