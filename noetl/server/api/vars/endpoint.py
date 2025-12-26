"""
Variable Management API endpoints.

Provides REST API for managing execution-scoped variables:
- GET /api/vars/{execution_id} - List all variables with metadata
- GET /api/vars/{execution_id}/{var_name} - Get specific variable
- POST /api/vars/{execution_id} - Set variables (user_defined type)
- DELETE /api/vars/{execution_id}/{var_name} - Delete variable

These endpoints complement the declarative vars block feature by allowing
external systems to inject, inspect, and manage variables at runtime.
"""

from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Path, Body
from fastapi.responses import JSONResponse

from noetl.worker.transient import TransientVars
from noetl.core.logger import setup_logger
from .schema import (
    VariableListResponse,
    VariableValueResponse,
    SetVariablesRequest,
    SetVariablesResponse,
    DeleteVariableResponse,
    CleanupExecutionResponse,
    VariableMetadata
)

logger = setup_logger(__name__, include_location=True)
router = APIRouter(prefix="/vars", tags=["variables"])


@router.get("/{execution_id}", response_model=VariableListResponse)
async def list_variables(
    execution_id: int = Path(..., description="Execution ID")
) -> VariableListResponse:
    """
    Get all variables for an execution with full metadata.
    
    Returns variable values along with type, source_step, timestamps, and access counts.
    Useful for debugging workflow state and tracking variable usage.
    
    **Does not increment access_count** - this is a bulk read operation.
    """
    try:
        vars_with_metadata = await TransientVars.get_all_vars_with_metadata(execution_id)
        
        # Convert to VariableMetadata models
        variables = {}
        for var_name, metadata in vars_with_metadata.items():
            variables[var_name] = VariableMetadata(
                value=metadata['value'],
                type=metadata['type'],
                source_step=metadata.get('source_step'),
                created_at=metadata['created_at'],
                accessed_at=metadata['accessed_at'],
                access_count=metadata['access_count']
            )
        
        logger.info(f"API: Listed {len(variables)} variables for execution {execution_id}")
        
        return VariableListResponse(
            execution_id=execution_id,
            variables=variables,
            count=len(variables)
        )
        
    except Exception as e:
        logger.error(f"API: Failed to list variables for execution {execution_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve variables: {str(e)}"
        )


@router.get("/{execution_id}/{var_name}", response_model=VariableValueResponse)
async def get_variable(
    execution_id: int = Path(..., description="Execution ID"),
    var_name: str = Path(..., description="Variable name")
) -> VariableValueResponse:
    """
    Get a specific variable with metadata.
    
    **Increments access_count** and updates accessed_at timestamp.
    Use this for individual variable reads during workflow execution or debugging.
    
    Returns 404 if variable not found.
    """
    try:
        cached_var = await TransientVars.get_cached(var_name, execution_id)
        
        if cached_var is None:
            logger.warning(
                f"API: Variable '{var_name}' not found for execution {execution_id}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"Variable '{var_name}' not found for execution {execution_id}"
            )
        
        logger.info(
            f"API: Retrieved variable '{var_name}' for execution {execution_id} "
            f"(access_count={cached_var['access_count']})"
        )
        
        return VariableValueResponse(
            execution_id=execution_id,
            var_name=var_name,
            value=cached_var['value'],
            type=cached_var['type'],
            source_step=cached_var.get('source_step'),
            created_at=cached_var['created_at'],
            accessed_at=cached_var['accessed_at'],
            access_count=cached_var['access_count']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"API: Failed to get variable '{var_name}' for execution {execution_id}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve variable: {str(e)}"
        )


@router.post("/{execution_id}", response_model=SetVariablesResponse)
async def set_variables(
    execution_id: int = Path(..., description="Execution ID"),
    request: SetVariablesRequest = Body(...)
) -> SetVariablesResponse:
    """
    Set multiple variables for an execution.
    
    Variables are stored with the specified var_type (default: 'user_defined').
    This endpoint allows external systems to inject runtime variables that can be
    accessed in workflow steps via {{ vars.var_name }} templates.
    
    Use cases:
    - Injecting configuration values from external systems
    - Setting computed variables from external workflows
    - Manual intervention during workflow execution
    - Pre-populating variables before workflow starts
    
    **Note**: Existing variables with the same name are overwritten.
    """
    try:
        if not request.variables:
            raise HTTPException(
                status_code=400,
                detail="Request body must contain 'variables' dict with at least one variable"
            )
        
        # Validate var_type
        valid_types = {'user_defined', 'step_result', 'computed', 'iterator_state'}
        if request.var_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid var_type '{request.var_type}'. Must be one of: {', '.join(valid_types)}"
            )
        
        count = await TransientVars.set_multiple(
            variables=request.variables,
            execution_id=execution_id,
            var_type=request.var_type,
            source_step=request.source_step
        )
        
        var_names = list(request.variables.keys())
        logger.info(
            f"API: Set {count} variables for execution {execution_id} "
            f"(type={request.var_type}, source={request.source_step})"
        )
        
        return SetVariablesResponse(
            execution_id=execution_id,
            variables_set=count,
            var_names=var_names
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"API: Failed to set variables for execution {execution_id}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to set variables: {str(e)}"
        )


@router.delete("/{execution_id}/{var_name}", response_model=DeleteVariableResponse)
async def delete_variable(
    execution_id: int = Path(..., description="Execution ID"),
    var_name: str = Path(..., description="Variable name to delete")
) -> DeleteVariableResponse:
    """
    Delete a specific variable.
    
    Use cases:
    - Removing stale variables during long-running executions
    - Cleanup after debugging/testing
    - Manual intervention to remove incorrect variables
    
    Returns deleted=true if variable was found and deleted, false if not found.
    """
    try:
        deleted = await TransientVars.delete_var(var_name, execution_id)
        
        if deleted:
            logger.info(
                f"API: Deleted variable '{var_name}' for execution {execution_id}"
            )
        else:
            logger.warning(
                f"API: Variable '{var_name}' not found for deletion (execution {execution_id})"
            )
        
        return DeleteVariableResponse(
            execution_id=execution_id,
            var_name=var_name,
            deleted=deleted
        )
        
    except Exception as e:
        logger.error(
            f"API: Failed to delete variable '{var_name}' for execution {execution_id}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete variable: {str(e)}"
        )


@router.delete("/{execution_id}", response_model=CleanupExecutionResponse)
async def cleanup_execution(
    execution_id: int = Path(..., description="Execution ID")
) -> CleanupExecutionResponse:
    """
    Delete all variables for an execution.
    
    Called when playbook execution completes to clean up execution-scoped variables.
    Also useful for manual cleanup during development/testing.
    
    Returns the number of variables deleted.
    """
    try:
        deleted_count = await TransientVars.cleanup_execution(execution_id)
        
        logger.info(
            f"API: Cleaned up {deleted_count} variables for execution {execution_id}"
        )
        
        return CleanupExecutionResponse(
            execution_id=execution_id,
            deleted_count=deleted_count
        )
        
    except Exception as e:
        logger.error(
            f"API: Failed to cleanup variables for execution {execution_id}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cleanup execution variables: {str(e)}"
        )
