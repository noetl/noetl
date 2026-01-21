
# --- Finalize Execution API ---
from pydantic import BaseModel, Field

class FinalizeExecutionRequest(BaseModel):
    reason: str = Field(default="Abandoned or timed out", description="Reason for forced finalization")

class FinalizeExecutionResponse(BaseModel):
    status: str = Field(..., description="Finalization status: finalized, already_completed, not_found")
    execution_id: str = Field(..., description="The execution ID that was finalized")
    message: str = Field(..., description="Human-readable status message")
"""Pydantic schemas for execution API responses."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from noetl.core.common import AppBaseModel

class ExecutionEntryResponse(AppBaseModel):
    """Response schema for a single execution entry."""

    execution_id: str = Field(..., description="Unique execution identifier")
    catalog_id: str = Field(..., description="id catalog resource")
    path: str = Field(..., description="Full path to the playbook")
    version: int = Field(..., description="Version of the playbook")
    status: str = Field(..., description="Execution status (COMPLETED, RUNNING, FAILED, etc.)")
    start_time: datetime = Field(..., description="Execution start timestamp")
    end_time: Optional[datetime] = Field(None, description="Execution end timestamp (null if still running)")
    progress: int = Field(..., ge=0, le=100, description="Execution progress percentage (0-100)")
    result: Optional[Dict[str, Any]] = Field(None, description="Execution results with command outputs")
    error: Optional[str] = Field(None, description="Error message if execution failed")
    parent_execution_id: Optional[str] = Field(None, description="Parent execution ID if this is a sub-playbook")


class CancelExecutionRequest(BaseModel):
    """Request schema for cancelling an execution."""
    
    reason: Optional[str] = Field(
        default="User requested cancellation",
        description="Reason for cancellation"
    )
    cascade: bool = Field(
        default=True,
        description="If True, also cancel child executions (sub-playbooks)"
    )


class CancelExecutionResponse(BaseModel):
    """Response schema for execution cancellation."""
    
    status: str = Field(..., description="Cancellation status: cancelled, already_completed, not_found")
    execution_id: str = Field(..., description="The execution ID that was cancelled")
    cancelled_executions: List[str] = Field(
        default_factory=list,
        description="List of all execution IDs that were cancelled (including children)"
    )
    message: str = Field(..., description="Human-readable status message")
