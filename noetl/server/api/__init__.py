"""
Server API routers aggregated from local modules.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

# Import routers from local package (migrated from noetl.api)
from . import event as event_api
from . import catalog as catalog_api
from . import credential as credential_api
from . import database as db_api
from . import runtime as runtime_api
from . import dashboard as dashboard_api
from . import system as system_api
from . import queue as queue_api
from . import aggregate as aggregate_api

router = APIRouter()


@router.get("/health", response_class=JSONResponse)
async def api_health():
    return {"status": "ok"}


router.include_router(event_api.router)
router.include_router(catalog_api.router)
router.include_router(credential_api.router)
router.include_router(db_api.router)
router.include_router(runtime_api.router)
router.include_router(dashboard_api.router)
router.include_router(system_api.router, prefix="/sys")
router.include_router(queue_api.router)
router.include_router(aggregate_api.router)

__all__ = ["router"]
