from __future__ import annotations

from typing import Any, Dict
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def handle_loop_event(event: Dict[str, Any], et: str) -> None:
    try:
        execution_id = event.get('execution_id')
        if not execution_id:
            return
        if et in {'loop_completed', 'end_loop'}:
            # Process loop completion and enqueue next steps when ready
            from ..processing import check_and_process_completed_loops
            await check_and_process_completed_loops(str(execution_id))
        elif et == 'loop_iteration':
            # Iteration on-going; no immediate action required beyond trackers
            return
    except Exception:
        logger.debug("LOOP_CONTROL: Failed handling loop event", exc_info=True)
