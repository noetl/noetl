"""Pydantic schemas for execution API responses."""

from datetime import datetime
from typing import Any, Dict, Optional

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
