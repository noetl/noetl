"""
NoETL API package - Top-level API routers and schemas.

Refactored from noetl.server.api to provide better organization
and separation of concerns.
"""

"""
NoETL API Routers - All FastAPI router definitions.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

# Import routers from local modules
from . import execution, credential, queue, aggregate, catalog, runtime, event, dashboard, system, metrics, broker, \
    database, context
from noetl.api import resource

router = APIRouter()

@router.get("/health", response_class=JSONResponse)
async def api_health():
    return {"status": "ok"}

# Include all sub-routers
router.include_router(context.router)
router.include_router(event.router)
router.include_router(catalog.router)
router.include_router(credential.router)
router.include_router(database.router)
router.include_router(runtime.router)
router.include_router(dashboard.router)
router.include_router(system.router)
router.include_router(queue.router)
router.include_router(aggregate.router)
router.include_router(broker.router)
router.include_router(metrics.router)
router.include_router(execution.router)
router.include_router(resource.router)

__all__ = [
    "router",
    "context", "queue", "event", "catalog", "credential",
    "database", "runtime", "dashboard", "system",
    "aggregate", "broker", "metrics", "execution", "resource"
]
