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
from . import credential, queue, aggregate, catalog, runtime, dashboard, system, metrics, broker, \
    database, context, run

router = APIRouter()

@router.get("/health", response_class=JSONResponse)
async def api_health():
    return {"status": "ok"}

# Include all sub-routers
router.include_router(context.router)
router.include_router(broker.router)  # Event handler (was event package)
router.include_router(catalog.router)
router.include_router(credential.router)
router.include_router(database.router)
router.include_router(runtime.router)
router.include_router(dashboard.router)
router.include_router(system.router)
router.include_router(queue.router)
router.include_router(aggregate.router)
# Note: broker.router already included above as event handler
router.include_router(metrics.router)
# Execution endpoints now under run.router (/api/run/playbook, /api/execute, /api/executions/run)
router.include_router(run.router)

__all__ = [
    "router",
    "context", "queue", "broker", "catalog", "credential",
    "database", "runtime", "dashboard", "system",
    "aggregate", "metrics", "run"
]
