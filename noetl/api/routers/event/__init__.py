"""
Event API package containing logically separated modules for event management.
"""

from fastapi import APIRouter
# broker router moved to noetl.server.api.broker
from .context import router as context_router
from .events import router as events_router
from .executions import router as executions_router
from .service import get_event_service, get_event_service_dependency, EventService
from .processing import (
    evaluate_broker_for_execution,
    check_and_process_completed_loops,
    check_and_process_completed_child_executions,
    _check_distributed_loop_completion,
)
from ..broker import encode_task_for_queue

# Create main router that includes all sub-routers
router = APIRouter()
router.include_router(context_router)
router.include_router(events_router)
router.include_router(executions_router)

# Export commonly used functions and classes
__all__ = [
    'router',
    'EventService',
    'get_event_service',
    'get_event_service_dependency',
    # Processing functions
    'evaluate_broker_for_execution',
    'check_and_process_completed_loops',
    'check_and_process_completed_child_executions',
    '_check_distributed_loop_completion',
    # Helpers
    'encode_task_for_queue',
]
