from fastapi import APIRouter, Depends, HTTPException
from noetl.connectors.hub import ConnectorHub,get_connector_hub
from noetl.api.services.workload import WorkloadService
from noetl.api.schemas.workload import WorkloadRequest, WorkloadResponse
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)

router = APIRouter(prefix="/workload")

def get_registry_service(context: ConnectorHub = Depends(get_connector_hub)) -> WorkloadService:
    return WorkloadService(context)

@router.post("/register", response_model=WorkloadResponse, status_code=201)
async def register_registry_entry(
    payload: WorkloadRequest,
    registry_service: WorkloadService = Depends(get_registry_service)
):
    try:
        logger.info(f"Registering workload entry: {payload.event_id}", extra={"payload":payload.model_dump()})
        registry_entry = await registry_service.register(payload)
        return registry_entry
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register workload entry: {e}")
