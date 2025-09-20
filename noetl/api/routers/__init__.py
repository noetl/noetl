"""
NoETL API Routers - All FastAPI router definitions.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

# Import routers from local modules
from . import queue
from . import event
from . import catalog
from . import credential
from . import database
from . import runtime
from . import dashboard
from . import system
from . import aggregate
from . import broker

router = APIRouter()

@router.get("/health", response_class=JSONResponse)
async def api_health():
    return {"status": "ok"}

# Include all sub-routers
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

__all__ = [
    "router", 
    "queue", "event", "catalog", "credential", 
    "database", "runtime", "dashboard", "system", 
    "aggregate", "broker"
]
