from fastapi import APIRouter, HTTPException, Request, Path
from fastapi.openapi.models import Example
from noetl.core.logger import setup_logger
from .schema import ExecutionRequest, ExecutionResponse, ResourceType
from .service import ExecutionService


logger = setup_logger(__name__, include_location=True)
router = APIRouter(tags=["execution"])


@router.post("/run/{resource_type}", response_model=ExecutionResponse)
async def execute_resource(
    request: Request,
    payload: ExecutionRequest,
    resource_type: ResourceType = Path(
        ...,
        description="Type of resource to execute (currently supported: playbook)",
        openapi_examples={
            "playbook": Example(
                summary="Playbook execution",
                value="playbook"
            )
        }
    )
):
    """
    Execute a resource (playbook, tool, model, workflow) using unified request schema.
    
    **Path Parameters:**
    - `resource_type`: Type of resource to execute (currently supported: playbook)
    
    **Supported Lookup Strategies:**
    - `catalog_id`: Direct catalog entry lookup (highest priority)
    - `path` + `version`: Version-controlled path-based lookup
    
    **Request Body:**
    - **Identifiers** (at least one required):
      - `catalog_id`: Direct catalog entry ID
      - `path`: Catalog path for resource
      - `version`: Version identifier (default: "latest")
    
    - **Configuration**:
      - `args`: Input arguments for execution
      - `merge`: Merge args with existing workload (default: false)
    
    - **Context** (for nested executions):
      - `context`: Nested context object
      - OR flat fields: `parent_execution_id`, `parent_event_id`, `parent_step`
    
    **Returns:**
    - Execution response with execution_id, path, version, and status
    
    **Execution Flow:**
    1. Resolve catalog entry (path/version or catalog_id)
    2. Validate resource content
    3. Build execution plan (workflow, transitions, workbook)
    4. Merge workload data
    5. Persist to database (workload, event, workflow, transition tables)
    6. Publish initial steps to queue for worker processing
    7. Return execution response with tracking details
    
    **Examples:**
    - Execute playbook: `POST /api/v1/run/playbook`
    """
    try:
        # Capture requestor details from HTTP request
        requestor_info = {
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "timestamp": None,  # Will be set during execution
        }
        
        logger.debug(f"EXECUTE: resource_type={resource_type}, request: {payload.model_dump()}")
        
        # Set resource type in payload for tracking
        # (Currently all resources go through the same execution flow)
        
        return await ExecutionService.execute(payload, requestor_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

