import json
from fastapi import APIRouter, HTTPException, Request, Path
from fastapi.openapi.models import Example
from noetl.core.logger import setup_logger
from .schema import ExecutionRequest, ExecutionResponse, ResourceType


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
    
    **DEPRECATED**: This endpoint is deprecated and redirects to /api/execute.
    Use /api/execute directly for new integrations.
    
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
      - `args`: Input arguments for execution (mapped to 'payload' in V2)
      - `merge`: Merge args with existing workload (default: false) [IGNORED in V2]
    
    - **Context** (for nested executions):
      - `context`: Nested context object
      - OR flat fields: `parent_execution_id`, `parent_event_id`, `parent_step`
    
    **Returns:**
    - Execution response with execution_id, path, version, and status
    
    **Examples:**
    - Execute playbook: `POST /api/run/playbook`
    """
    try:
        logger.debug(f"[RUN] Incoming request: path={payload.path}, version={payload.version}, catalog_id={payload.catalog_id}")

        # Lazy import to avoid circular imports
        from noetl.server.api.v2 import start_execution, StartExecutionRequest

        # Convert old API request to V2 format
        # Parse version if provided (can be string like "1" or "latest")
        version_int = None
        if payload.version and payload.version != "latest":
            try:
                version_int = int(payload.version)
            except ValueError:
                pass  # Keep None for non-numeric versions

        logger.debug(f"[RUN] Parsed version: '{payload.version}' -> version_int={version_int}")

        v2_request = StartExecutionRequest(
            path=payload.path,
            catalog_id=int(payload.catalog_id) if payload.catalog_id else None,
            version=version_int,
            payload=payload.args or {},
            parent_execution_id=int(payload.context.parent_execution_id) if payload.context and payload.context.parent_execution_id else None
        )

        logger.debug(f"[RUN] V2 request: path={v2_request.path}, version={v2_request.version}, catalog_id={v2_request.catalog_id}")

        # Call V2 API
        v2_response = await start_execution(v2_request)
        
        # Convert V2 response to old API format
        return ExecutionResponse(
            execution_id=v2_response.execution_id,
            path=payload.path,
            version=payload.version or "latest",
            status="running",
            message=f"Execution started with {v2_response.commands_generated} initial commands"
        )
        
    except ValueError as e:
        logger.error(f"Validation error executing resource: {e}")
        raise HTTPException(status_code=400, detail={
            "code": "validation_error",
            "error": e.args[0] if len(e.args) > 0 else None,
            "place": e.args[1] if len(e.args) > 1 else None
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
