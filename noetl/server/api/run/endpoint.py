from fastapi import APIRouter, HTTPException, Request
from noetl.core.logger import setup_logger
from .schema import ExecutionRequest, ExecutionResponse
from .service import execute_request


logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/playbook/run", response_model=ExecutionResponse)
async def execute_playbook(request: Request, payload: ExecutionRequest):
    """
    Execute a playbook/tool/model using unified request schema.
    
    **Supported Lookup Strategies:**
    - `catalog_id`: Direct catalog entry lookup (highest priority)
    - `path` + `version`: Version-controlled path-based lookup
    - `playbook_id`: Legacy identifier (treated as path, backward compatible)
    
    **Request Body:**
    - **Identifiers** (at least one required):
      - `catalog_id`: Direct catalog entry ID
      - `path`: Catalog path for playbook/tool/model
      - `playbook_id`: Legacy playbook identifier (alias for path)
      - `version`: Version identifier (default: "latest")
    
    - **Configuration**:
      - `type`: Execution type - playbook, tool, model, workflow (default: playbook)
      - `parameters`: Input parameters for execution
      - `merge`: Merge parameters with existing workload (default: false)
      - `sync_to_postgres`: Persist execution state (default: true)
    
    - **Context** (for nested executions):
      - `context`: Nested context object
      - OR flat fields: `parent_execution_id`, `parent_event_id`, `parent_step`
    
    **Returns:**
    - Execution response with execution_id, path, version, and status
    
    **MCP Compatibility:**
    This endpoint supports Model Context Protocol (MCP) for executing
    playbooks, tools, and models with a unified interface.
    """
    try:
        # Capture requestor details from HTTP request
        requestor_info = {
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "timestamp": None,  # Will be set during execution
        }
        
        logger.debug(f"EXECUTE: Received request: {payload.model_dump()}")
        return await execute_request(payload, requestor_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute", response_model=ExecutionResponse)
async def execute_playbook_by_path_version(request: Request, payload: ExecutionRequest):
    """
    Execute a playbook/tool/model using unified request schema (alias for /executions/run).
    
    This endpoint is identical to /executions/run and provides the same functionality.
    Both endpoints now use the unified ExecutionRequest schema supporting:
    
    **Supported Lookup Strategies:**
    - `catalog_id`: Direct catalog entry lookup (highest priority)
    - `path` + `version`: Version-controlled path-based lookup  
    - `playbook_id`: Legacy identifier (treated as path, backward compatible)
    
    **Request Body:**
    - **Identifiers** (at least one required):
      - `catalog_id`: Direct catalog entry ID
      - `path`: Catalog path for playbook/tool/model
      - `playbook_id`: Legacy playbook identifier (alias for path)
      - `version`: Version identifier (default: "latest")
    
    - **Configuration**:
      - `type`: Execution type - playbook, tool, model, workflow (default: playbook)
      - `parameters`: Input parameters for execution
      - `merge`: Merge parameters with existing workload (default: false)
      - `sync_to_postgres`: Persist execution state (default: true)
    
    - **Context** (for nested executions):
      - `context`: Nested context object
      - OR flat fields: `parent_execution_id`, `parent_event_id`, `parent_step`
    
    **Returns:**
    - Execution response with execution_id, path, version, and status
    
    **MCP Compatibility:**
    This endpoint supports Model Context Protocol (MCP) for executing
    playbooks, tools, and models with a unified interface.
    """
    try:
        # Capture requestor details from HTTP request
        requestor_info = {
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "timestamp": None,  # Will be set during execution
        }
        
        logger.debug(f"EXECUTE: Received request: {payload.model_dump()}")
        return await execute_request(payload, requestor_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

