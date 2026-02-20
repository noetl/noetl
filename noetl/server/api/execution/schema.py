
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


class AnalyzeExecutionWithAIRequest(BaseModel):
    """Request schema for execution analysis + AI playbook run."""

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
    include_event_rows: bool = Field(
        default=True,
        description="Include raw event rows from Postgres in payload sent to AI playbook",
    )
    event_rows_limit: int = Field(
        default=500,
        ge=50,
        le=5000,
        description="Maximum number of event rows to include",
    )
    include_event_log_rows: bool = Field(
        default=True,
        description="Include event_log rows from Postgres in payload sent to AI playbook",
    )
    event_log_rows_limit: int = Field(
        default=200,
        ge=20,
        le=2000,
        description="Maximum number of event_log rows to include",
    )
    analysis_playbook_path: str = Field(
        default="ops/execution_ai_analyze",
        description="Playbook path used to run AI analysis",
    )
    gcp_auth_credential: Optional[str] = Field(
        default=None,
        description="Optional override for analyzer playbook workload.gcp_auth (keychain auth credential)",
    )
    openai_secret_path: Optional[str] = Field(
        default=None,
        description="Optional override for analyzer playbook workload.openai_secret_path",
    )
    model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model used by analysis playbook",
    )
    include_patch_diff: bool = Field(
        default=True,
        description="Ask AI playbook to generate optional patch diff",
    )
    auto_fix_mode: str = Field(
        default="report",
        description="One of: report, dry_run, apply. apply requires explicit approval flag.",
    )
    approval_required: bool = Field(
        default=True,
        description="Require explicit approval before apply mode",
    )
    approved: bool = Field(
        default=False,
        description="Explicit user approval for apply mode",
    )
    timeout_seconds: int = Field(
        default=180,
        ge=30,
        le=1200,
        description="Max time to wait for AI playbook completion",
    )
    poll_interval_ms: int = Field(
        default=1500,
        ge=200,
        le=10000,
        description="Polling interval while waiting for AI playbook execution",
    )


class AnalyzeExecutionWithAIResponse(BaseModel):
    """Response schema for execution analysis + AI playbook run."""

    execution_id: str = Field(..., description="Target execution identifier")
    path: str = Field(..., description="Target playbook path")
    status: str = Field(..., description="Target execution status")
    generated_at: datetime = Field(..., description="UTC timestamp when AI analysis finished")
    bundle: AnalyzeExecutionResponse = Field(..., description="Base analysis bundle used as AI input")
    ai_playbook_path: str = Field(..., description="AI analyzer playbook path")
    ai_execution_id: Optional[str] = Field(None, description="Execution ID of AI analyzer playbook")
    ai_execution_status: str = Field(..., description="AI analyzer playbook status")
    ai_report: Dict[str, Any] = Field(default_factory=dict, description="Parsed AI report payload")
    ai_raw_output: Dict[str, Any] = Field(default_factory=dict, description="Raw AI step output payload")
    approval_required: bool = Field(default=True, description="Whether explicit approval is required for apply mode")
    approved: bool = Field(default=False, description="Whether apply mode was explicitly approved")
    auto_fix_mode: str = Field(default="report", description="Requested auto-fix mode")
    dry_run_recommended: bool = Field(default=True, description="Always true: run dry-run/tests before apply")
