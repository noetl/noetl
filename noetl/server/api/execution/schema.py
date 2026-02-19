
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


class CleanupStuckExecutionsRequest(BaseModel):
    """Request schema for cleaning up stuck executions."""
    
    older_than_minutes: int = Field(
        default=5,
        ge=1,
        description="Cancel executions older than this many minutes without terminal event"
    )
    dry_run: bool = Field(
        default=False,
        description="If True, only report what would be cancelled without making changes"
    )


class CleanupStuckExecutionsResponse(BaseModel):
    """Response schema for stuck execution cleanup."""
    
    cancelled_count: int = Field(..., description="Number of executions marked as cancelled")
    execution_ids: List[str] = Field(..., description="List of execution IDs that were cancelled")
    message: str = Field(..., description="Human-readable status message")


class AnalyzeExecutionRequest(BaseModel):
    """Request schema for execution analysis bundle."""

    max_events: int = Field(
        default=2000,
        ge=100,
        le=10000,
        description="Maximum number of events to include in analysis",
    )
    event_sample_size: int = Field(
        default=200,
        ge=20,
        le=1000,
        description="Number of latest events to include in AI prompt sample",
    )
    include_playbook_content: bool = Field(
        default=True,
        description="Include full playbook YAML content in analysis bundle",
    )


class AnalyzeExecutionResponse(BaseModel):
    """Response schema for execution analysis bundle."""

    execution_id: str = Field(..., description="Execution identifier")
    path: str = Field(..., description="Playbook path")
    status: str = Field(..., description="Execution status")
    generated_at: datetime = Field(..., description="UTC timestamp when analysis was generated")
    summary: Dict[str, Any] = Field(..., description="Computed execution summary metrics")
    findings: List[Dict[str, Any]] = Field(default_factory=list, description="Detected findings")
    recommendations: List[str] = Field(default_factory=list, description="Suggested improvements")
    cloud: Dict[str, Any] = Field(default_factory=dict, description="Cloud links/query helpers")
    playbook: Dict[str, Any] = Field(default_factory=dict, description="Playbook metadata/content")
    event_sample: List[Dict[str, Any]] = Field(default_factory=list, description="Latest event sample for AI")
    ai_prompt: str = Field(..., description="Prompt payload for external AI analysis")
