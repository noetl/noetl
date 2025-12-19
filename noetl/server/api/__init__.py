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
from . import credential, aggregate, catalog, runtime, dashboard, system, broker, \
    database, context, run, execution, vars, keychain

router = APIRouter()

@router.get("/health", response_class=JSONResponse)
async def api_health():
    return {"status": "ok"}

# Include all sub-routers
router.include_router(context.router)
# DISABLED: Legacy v1 event endpoint - replaced by /api/v2/events
# router.include_router(broker.router)  # Event handler (was event package)
router.include_router(catalog.router)
router.include_router(execution.router)
router.include_router(credential.router)
router.include_router(database.router)
router.include_router(runtime.router)
router.include_router(dashboard.router)
router.include_router(system.router)
router.include_router(aggregate.router)
# Note: broker.router already included above as event handler
# Execution endpoints now under run.router (/api/run/playbook, /api/execute, /api/executions/run)
router.include_router(run.router)
# Variable management endpoints
router.include_router(vars.router)
# Keychain management endpoints
router.include_router(keychain.router)

__all__ = [
    "router",
    "context", "broker", "catalog", "credential",
    "database", "runtime", "dashboard", "system",
    "aggregate", "run", "vars", "keychain"
]
