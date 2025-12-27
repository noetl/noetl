"""
Pydantic models for Variable Management API.
"""

from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class VariableMetadata(BaseModel):
    """Variable with full metadata."""
    value: Any = Field(..., description="Variable value (JSON-serializable)")
    type: str = Field(..., description="Variable type: user_defined, step_result, computed, iterator_state")
    source_step: Optional[str] = Field(None, description="Step that created/updated the variable")
    created_at: datetime = Field(..., description="Creation timestamp")
    accessed_at: datetime = Field(..., description="Last access timestamp")
    access_count: int = Field(..., description="Number of times variable was read")


class VariableListResponse(BaseModel):
    """Response for GET /api/vars/{execution_id}."""
    execution_id: int = Field(..., description="Execution identifier")
    variables: dict[str, VariableMetadata] = Field(..., description="Variables with metadata")
    count: int = Field(..., description="Total variable count")


class VariableValueResponse(BaseModel):
    """Response for GET /api/vars/{execution_id}/{var_name}."""
    execution_id: int = Field(..., description="Execution identifier")
    var_name: str = Field(..., description="Variable name")
    value: Any = Field(..., description="Variable value")
    type: str = Field(..., description="Variable type")
    source_step: Optional[str] = Field(None, description="Source step")
    created_at: datetime = Field(..., description="Creation timestamp")
    accessed_at: datetime = Field(..., description="Last access timestamp")
    access_count: int = Field(..., description="Access count")


class SetVariablesRequest(BaseModel):
    """Request body for POST /api/vars/{execution_id}."""
    variables: dict[str, Any] = Field(..., description="Variables to set: {var_name: value}")
    var_type: str = Field(
        default="user_defined",
        description="Variable type (user_defined, step_result, computed, iterator_state)"
    )
    source_step: Optional[str] = Field(
        default=None,
        description="Optional source step identifier"
    )


class SetVariablesResponse(BaseModel):
    """Response for POST /api/vars/{execution_id}."""
    execution_id: int = Field(..., description="Execution identifier")
    variables_set: int = Field(..., description="Number of variables set")
    var_names: list[str] = Field(..., description="Names of variables set")


class DeleteVariableResponse(BaseModel):
    """Response for DELETE /api/vars/{execution_id}/{var_name}."""
    execution_id: int = Field(..., description="Execution identifier")
    var_name: str = Field(..., description="Variable name deleted")
    deleted: bool = Field(..., description="Whether variable was found and deleted")


class CleanupExecutionResponse(BaseModel):
    """Response for DELETE /api/vars/{execution_id}."""
    execution_id: int = Field(..., description="Execution identifier")
    deleted_count: int = Field(..., description="Number of variables deleted")
