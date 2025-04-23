from fastapi import APIRouter, HTTPException, Depends
from noetl.shared import setup_logger
from noetl.schemas.catalog_schema import CatalogEntryRequest, CatalogEntryResponse
from noetl.services.catalog_service import CatalogService

logger = setup_logger(__name__, include_location=True)
router = APIRouter()

def get_catalog_service():
    return CatalogService()

@router.post("/catalog/{resource}/register", response_model=CatalogEntryResponse)
async def register_resource(
    resource: str,
    request: CatalogEntryRequest,  # Validate input with a schema
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    try:
        result = await catalog_service.register_resource(resource, request.dict())
        return CatalogEntryRequest(message=result["message"])
    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
