from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from noetl.shared import setup_logger
from noetl.shared.context import app_context, AppContext
from noetl.schemas.catalog_schema import RegisterRequest, CatalogEntryRequest, CatalogEntryResponse
from noetl.services.catalog_service import CatalogService

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


def get_catalog_service():
    return CatalogService()

@router.post("/register")
async def register_resource(
        request: RegisterRequest,
        context: AppContext = Depends(app_context)
):
    logger.info(f"Received request to register resource.")
    return await CatalogService.register_entry(
        content_base64=request.content_base64,
        event_type="REGISTERED",
        context=context
    )
