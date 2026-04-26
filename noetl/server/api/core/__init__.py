from fastapi import APIRouter
from .core import get_engine, get_nats_publisher
from .models import ExecuteRequest, ExecuteResponse, StartExecutionRequest
from .execution import execute, start_execution
from .execution import router as execution_router
from .commands import router as commands_router
from .events import router as events_router
from .batch import router as batch_router
from .db import router as db_router

router = APIRouter(prefix="", tags=["api"])

router.include_router(execution_router)
router.include_router(commands_router)
router.include_router(events_router)
router.include_router(batch_router)
router.include_router(db_router)


from .batch import ensure_batch_acceptor_started, shutdown_batch_acceptor
from .recovery import shutdown_publish_recovery_tasks
from .metrics import get_batch_metrics_snapshot

__all__ = [
    "router", 
    "get_engine", 
    "get_nats_publisher",
    "ExecuteRequest",
    "ExecuteResponse",
    "StartExecutionRequest",
    "execute",
    "start_execution",
    "ensure_batch_acceptor_started",
    "shutdown_batch_acceptor",
    "shutdown_publish_recovery_tasks",
    "get_batch_metrics_snapshot"
]
