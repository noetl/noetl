from fastapi import APIRouter, Depends
from noetl.util import setup_logger
from appctx.app_context import get_app_context, AppContext
from noetl.api.schemas.catalog import RegisterRequest
from noetl.api.services.catalog import CatalogService

logger = setup_logger(__name__, include_location=True)
router = APIRouter(prefix="/catalog")


def get_catalog_service():
    return CatalogService()

@router.post("/register")
async def register_resource(
        request: RegisterRequest,
        context: AppContext = Depends(get_app_context)
):
    content_base64 = request.content_base64
    logger.info(f"Received request to register resource.", extra={"content_base64": content_base64 })
    return await CatalogService.register_entry(
        content_base64=content_base64,
        event_type="REGISTERED",
        context=context
    )
