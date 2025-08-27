
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from noetl.api import event as event_api
from noetl.api import catalog as catalog_api
from noetl.api import credential as credential_api
from noetl.api import database as db_api
from noetl.api import runtime as runtime_api
from noetl.api import dashboard as dashboard_api
from noetl.api import system as system_api
from noetl.api import queue as queue_api

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
