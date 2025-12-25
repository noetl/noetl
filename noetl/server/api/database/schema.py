"""
NoETL Database API Schemas - Request/Response models for database operations.

Supports:
- PostgreSQL query execution
- Stored procedure calls
- Query result retrieval
"""

from typing import Optional, Any, List, Dict, Union
from pydantic import BaseModel, Field, field_validator


class PostgresExecuteRequest(BaseModel):
    """Request schema for executing PostgreSQL queries or procedures."""
    
    query: Optional[str] = Field(
        default=None,
        description="SQL query to execute"
    )
    query_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded SQL query (alternative to query field)"
    )
    procedure: Optional[str] = Field(
        default=None,
        description="Stored procedure to call"
    )
    parameters: Optional[Union[List[Any], Dict[str, Any], Any]] = Field(
        default=None,
        description="Parameters for the query or procedure"
    )
    db_schema: Optional[str] = Field(
        default=None,
        description="Database schema to use",
        alias="schema"
    )
    database: Optional[str] = Field(
        default=None,
        description="Database name to connect to (overrides default)"
    )
    credential: Optional[str] = Field(
        default=None,
        description="Credential name from credential table to use for connection"
    )
    connection_string: Optional[str] = Field(
        default=None,
        description="Custom connection string (overrides database and credential)"
    )
    
    @field_validator('query', 'procedure', mode='before')
    @classmethod
    def strip_sql(cls, v):
        """Strip whitespace from SQL strings."""
        if v:
            return str(v).strip()
        return v
    
    model_config = {
        "populate_by_name": True,
    }


class PostgresExecuteResponse(BaseModel):
    """Response schema for PostgreSQL execution."""
    
    status: str = Field(
        ...,
        description="Execution status (ok or error)"
    )
    result: Optional[List[Any]] = Field(
        default=None,
        description="Query results (if any)"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message (if status is error)"
    )


class WeatherAlertSummaryRow(BaseModel):
    """Schema for a weather alert summary row."""
    
    id: str = Field(
        ...,
        description="Row ID"
    )
    alert_cities: Optional[Any] = Field(
        default=None,
        description="Cities with alerts"
    )
    alert_count: Optional[int] = Field(
        default=None,
        description="Number of alerts"
    )
    execution_id: str = Field(
        ...,
        description="Execution ID"
    )
    created_at: str = Field(
        ...,
        description="Creation timestamp"
    )
    
    @field_validator('id', 'execution_id', mode='before')
    @classmethod
    def coerce_to_string(cls, v):
        """Coerce IDs to string."""
        if v is None:
            return v
        return str(v)
    
    @field_validator('created_at', mode='before')
    @classmethod
    def coerce_datetime_to_iso(cls, v):
        """Coerce datetime to ISO 8601 string."""
        if v is None:
            return v
        if hasattr(v, 'isoformat'):
            return v.isoformat()
        return str(v)


class WeatherAlertSummaryResponse(BaseModel):
    """Response schema for weather alert summary queries."""
    
    status: str = Field(
        ...,
        description="Query status (ok or error)"
    )
    row: Optional[WeatherAlertSummaryRow] = Field(
        default=None,
        description="Weather alert summary row"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message (if status is error)"
    )
