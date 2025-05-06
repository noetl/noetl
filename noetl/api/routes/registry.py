from fastapi import APIRouter, Depends, HTTPException

from noetl.ctx.app_context import AppContext,get_app_context
from noetl.api.services.registry import RegistryService
from noetl.api.schemas.registry import RegistryRequest, RegistryResponse

router = APIRouter(prefix="/registry")

def get_registry_service(context: AppContext = Depends(get_app_context)) -> RegistryService:
    return RegistryService(context)

@router.post("/register", response_model=RegistryResponse, status_code=201)
async def register_registry_entry(
    registry_data: RegistryRequest,
    registry_service: RegistryService = Depends(get_registry_service)
):
    try:
        registry_entry = await registry_service.register(registry_data)
        return registry_entry
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register registry entry: {e}")