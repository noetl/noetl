from fastapi import APIRouter

from .api import events as events_api
from .api import catalog as catalog_api
from .api import credentials as credentials_api
from .api import db as db_api
from .api import runtime as runtime_api
from .api import dashboard as dashboard_api

router = APIRouter()

router.include_router(events_api.router)
router.include_router(catalog_api.router)
router.include_router(credentials_api.router)
router.include_router(db_api.router)
router.include_router(runtime_api.router)
router.include_router(dashboard_api.router)
