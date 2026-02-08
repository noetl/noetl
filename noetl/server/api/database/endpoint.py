"""
NoETL Database API Endpoints - FastAPI routes for database operations.

Provides REST endpoints for:
- PostgreSQL query execution
- Stored procedure calls
- Custom database queries (example: weather alerts)
"""

from fastapi import APIRouter, HTTPException
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
        "database": "noetl"
    }
    ```
    
    Or with credential (schema optional):
    ```json
    {
        "query": "SELECT * FROM auth.users",
        "credential": "pg_auth_user"
    }
    ```
    
    Or with schema parameter (for unqualified table names):
    ```json
    {
        "query": "SELECT * FROM users",
        "credential": "pg_auth_user",
        "schema": "auth"
    }
    ```
    
    Or with full connection string:
    ```json
    {
        "query": "SELECT * FROM users",
        "connection_string": "postgresql://user:pass@localhost/db"
    }
    ```
    
    Or for stored procedures:
    ```json
    {
        "procedure": "CALL my_procedure(%s, %s)",
        "parameters": ["value1", "value2"],
        "database": "demo_noetl"
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
    
    **Request Parameters**:
    - `query`: SQL query to execute (required if procedure not provided)
    - `query_base64`: Base64-encoded query (alternative to query)
    - `procedure`: Stored procedure to call (required if query not provided)
    - `parameters`: Query/procedure parameters (optional)
    - `schema`: Database schema for search_path (optional, not needed if tables are fully qualified)
    - `database`: Database name to connect to (optional, uses NOETL_POSTGRES_DB by default)
    - `credential`: Credential name from credential table (optional)
    - `connection_string`: Full connection string (optional, highest priority)
    
    **Connection Priority**: connection_string > credential > database > default
    
    **Note**: The `schema` parameter sets PostgreSQL's search_path. It's only needed when querying
    tables without schema qualification (e.g., `SELECT * FROM users` instead of `SELECT * FROM auth.users`).
    
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


