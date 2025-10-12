"""
NoETL Aggregate API Endpoints - FastAPI routes for aggregate operations.

Provides REST endpoints for:
- Loop iteration result aggregation
- Event-sourced data retrieval
"""

from typing import Any, Dict
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from noetl.core.logger import setup_logger
from .service import AggregateService

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.get("/aggregate/loop/results", response_class=JSONResponse)
async def get_loop_iteration_results(execution_id: str, step_name: str) -> Dict[str, Any]:
    """
    Return the list of per-iteration results for a given execution and loop step.
    
    This endpoint sources data from event log only (event-sourced server side),
    avoiding any worker-side DB access.
    
    Uses generic loop metadata fields for robust filtering instead of content-specific logic.
    
    **Query Parameters**:
    - `execution_id`: Execution ID to query
    - `step_name`: Loop step name
    
    **Example**:
    ```
    GET /aggregate/loop/results?execution_id=123&step_name=process_cities
    ```
    
    **Response**:
    ```json
    {
        "status": "ok",
        "results": [
            {"city": "New York", "max_temp": 85, "alert": false},
            {"city": "Los Angeles", "max_temp": 92, "alert": true}
        ],
        "count": 2,
        "method": "loop_metadata"
    }
    ```
    
    **Method Types**:
    - `loop_metadata`: Results retrieved using loop metadata fields (preferred)
    - `legacy_content_filter`: Results retrieved using legacy content-based filtering
    
    **Note**: The legacy method includes a `debug` field with additional information
    about the filtering process.
    """
    try:
        result = await AggregateService.get_loop_iteration_results(
            execution_id=execution_id,
            step_name=step_name
        )
        # Convert Pydantic model to dict for JSONResponse
        return result.model_dump(exclude_none=True)
    except Exception as e:
        logger.exception(f"AGGREGATE.API: Failed to fetch loop results: {e}")
        raise HTTPException(status_code=500, detail=str(e))
