"""
NoETL Database API Service - Business logic for database operations.

Handles:
- Query execution
- Stored procedure calls
- Result retrieval and formatting
"""

from typing import Optional, Any
from fastapi import HTTPException
from noetl.core.common import get_async_db_connection
from noetl.core.logger import setup_logger
from psycopg.rows import dict_row
from .schema import (
    PostgresExecuteRequest,
    PostgresExecuteResponse,
    WeatherAlertSummaryResponse,
    WeatherAlertSummaryRow
)

logger = setup_logger(__name__)


class DatabaseService:
    """Service class for database operations."""
    
    @staticmethod
    async def execute_postgres(request: PostgresExecuteRequest) -> PostgresExecuteResponse:
        """
        Execute a PostgreSQL query or stored procedure.
        
        Args:
            request: PostgreSQL execution request
            
        Returns:
            PostgresExecuteResponse with results or error
            
        Raises:
            HTTPException: If validation fails
        """
        # Validate that either query or procedure is provided
        if not request.query and not request.procedure:
            raise HTTPException(
                status_code=400,
                detail="query or procedure is required"
            )
        
        try:
            async with get_async_db_connection(request.connection_string) as conn:
                async with conn.cursor() as cursor:
                    result = None
                    
                    if request.query:
                        await cursor.execute(request.query)
                        try:
                            result = await cursor.fetchall()
                        except Exception:
                            result = None
                    
                    elif request.procedure:
                        if isinstance(request.parameters, (list, tuple)):
                            await cursor.execute(request.procedure, request.parameters)
                        else:
                            await cursor.execute(request.procedure)
                        try:
                            result = await cursor.fetchall()
                        except Exception:
                            result = None
                    
                    # Commit transaction
                    try:
                        await conn.commit()
                        logger.debug("Database API transaction committed successfully")
                    except Exception as e:
                        logger.error(f"Database API commit failed: {e}")
                        raise
            
            return PostgresExecuteResponse(
                status="ok",
                result=result
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error executing database operation: {e}")
            return PostgresExecuteResponse(
                status="error",
                error=str(e)
            )
    
    @staticmethod
    async def get_last_weather_alert_summary(
        execution_id: str
    ) -> WeatherAlertSummaryResponse:
        """
        Get the last weather alert summary row for a given execution.
        
        This is an example endpoint showing how to query specific tables.
        
        Args:
            execution_id: Execution ID to filter by
            
        Returns:
            WeatherAlertSummaryResponse with row data or error
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT id, alert_cities, alert_count, execution_id, created_at
                        FROM public.weather_alert_summary
                        WHERE execution_id = %s
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (execution_id,)
                    )
                    row_dict = await cur.fetchone()
                    
                    if row_dict:
                        row = WeatherAlertSummaryRow(**row_dict)
                        return WeatherAlertSummaryResponse(
                            status="ok",
                            row=row
                        )
                    else:
                        return WeatherAlertSummaryResponse(
                            status="ok",
                            row=None
                        )
                    
        except Exception as e:
            logger.exception(f"Error retrieving weather alert summary: {e}")
            return WeatherAlertSummaryResponse(
                status="error",
                error=str(e)
            )
