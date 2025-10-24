"""FastAPI endpoint for resource execution."""

from fastapi import APIRouter

from noetl.server.api.resource.schema import ResourceRunRequest, ResourceRunResponse
from noetl.server.api.resource.service import ResourceExecutionService

router = APIRouter(prefix="/resource", tags=["resource"])


@router.post("/run", response_model=ResourceRunResponse)
async def run_resource(request: ResourceRunRequest) -> ResourceRunResponse:
    """Kick off a playbook execution directly from the catalog."""
    return await ResourceExecutionService.run(request)
