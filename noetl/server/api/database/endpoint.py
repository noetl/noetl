"""
NoETL Database API Endpoints - FastAPI routes for database operations.

Provides REST endpoints for:
- PostgreSQL query execution
- Stored procedure calls
- Custom database queries (example: weather alerts)
"""

from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from noetl.core.logger import setup_logger
from .schema import (
    PostgresExecuteRequest,
    PostgresExecuteResponse,
    WeatherAlertSummaryResponse
)
from .service import DatabaseService

logger = setup_logger(__name__)
router = APIRouter()


# ============================================================================
# PostgreSQL Execution Endpoints
# ============================================================================

@router.post("/postgres/execute", response_model=PostgresExecuteResponse)
async def execute_postgres(request: PostgresExecuteRequest) -> PostgresExecuteResponse:
    """
    Execute a PostgreSQL query or stored procedure.
    
    **Request Body**:
    ```json
    {
        "query": "SELECT * FROM users WHERE id = 1",
        "connection_string": "postgresql://user:pass@localhost/db"
    }
    ```
    
    Or for stored procedures:
    ```json
    {
        "procedure": "CALL my_procedure(%s, %s)",
        "parameters": ["value1", "value2"]
    }
    ```
    
    **Response**:
    ```json
    {
        "status": "ok",
        "result": [
            {"id": 1, "name": "John", "email": "john@example.com"}
        ]
    }
    ```
    
    **Query Parameters**:
    - `query`: SQL query to execute
    - `query_base64`: Base64-encoded query (alternative)
    - `procedure`: Stored procedure to call
    - `parameters`: Query/procedure parameters
    - `schema`: Database schema to use
    - `connection_string`: Custom connection string
    
    **Note**: Either `query` or `procedure` is required.
    """
    try:
        return await DatabaseService.execute_postgres(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in execute_postgres endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/postgres/weather_alert_summary/{execution_id}/last",
    response_model=WeatherAlertSummaryResponse
)
async def get_last_weather_alert_summary(
    execution_id: str
) -> WeatherAlertSummaryResponse:
    """
    Get the last weather alert summary row for a given execution.
    
    **Example endpoint** showing how to query specific tables for custom use cases.
    
    **Path Parameters**:
    - `execution_id`: Execution ID to filter by
    
    **Example**:
    ```
    GET /postgres/weather_alert_summary/123456789/last
    ```
    
    **Response**:
    ```json
    {
        "status": "ok",
        "row": {
            "id": "987654321",
            "alert_cities": ["New York", "Boston"],
            "alert_count": 5,
            "execution_id": "123456789",
            "created_at": "2025-10-12T10:00:00Z"
        }
    }
    ```
    
    **Use Case**: This endpoint demonstrates querying the `public.weather_alert_summary`
    table to retrieve aggregated weather alert data for a specific playbook execution.
    """
    try:
        return await DatabaseService.get_last_weather_alert_summary(execution_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in weather alert summary endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Legacy JSON Request Support (for backward compatibility)
# ============================================================================

@router.post("/postgres/execute/legacy", response_class=JSONResponse)
async def execute_postgres_legacy(
    request: Request,
    query: Optional[str] = None,
    query_base64: Optional[str] = None,
    procedure: Optional[str] = None,
    parameters: Any = None,
    schema: Optional[str] = None,
    connection_string: Optional[str] = None
):
    """
    Legacy endpoint that accepts raw JSON or query parameters.
    
    **Deprecated**: Use POST /postgres/execute with typed request instead.
    
    This endpoint maintains backward compatibility with existing clients that
    send either JSON body or query parameters.
    """
    try:
        # Try to parse JSON body first
        try:
            body = await request.json()
        except Exception:
            body = {}
        
        # Merge query params with body (query params take precedence)
        typed_request = PostgresExecuteRequest(
            query=query or body.get("query"),
            query_base64=query_base64 or body.get("query_base64"),
            procedure=procedure or body.get("procedure"),
            parameters=parameters or body.get("parameters"),
            db_schema=schema or body.get("schema"),
            connection_string=connection_string or body.get("connection_string")
        )
        
        response = await DatabaseService.execute_postgres(typed_request)
        
        # Return as plain JSON for legacy compatibility
        return JSONResponse(content=response.model_dump())
        
    except HTTPException as e:
        return JSONResponse(
            content={"status": "error", "error": e.detail},
            status_code=e.status_code
        )
    except Exception as e:
        logger.exception(f"Error in legacy database endpoint: {e}")
        return JSONResponse(
            content={"status": "error", "error": str(e)},
            status_code=500
        )
