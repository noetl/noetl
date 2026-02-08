"""
NoETL Event API Schemas - Request/Response models for event emission endpoints.

Simple event emission without business logic - direct database operations only.

Supports ResultRef pattern for efficient result storage:
- output_inline: Small results stored directly in event payload
- output_ref: Large results stored externally with pointer in event
- output_select: Selected fields for templating when output_ref is used
- preview: Truncated sample for UI/debugging
"""

from typing import Optional, Dict, Any, List, Union, Literal
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Result Storage Types (ResultRef pattern)
# ============================================================================

class ArtifactInfo(BaseModel):
    """
    Artifact storage details for externalized results.
    
    Contains all information needed to retrieve the artifact from external storage.
    """
    id: str = Field(..., description="Unique artifact identifier")
    uri: str = Field(..., description="Storage URI (s3://, gs://, file://)")
    content_type: str = Field(default="application/json", description="MIME type")
    compression: str = Field(default="none", description="Compression type (none, gzip)")
    bytes: int = Field(default=0, description="Size in bytes")
    sha256: Optional[str] = Field(default=None, description="Content hash for integrity")
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")


class ResultRef(BaseModel):
    """
    Lightweight pointer to a result.
    
    The event log stores the pointer (and optionally a small preview).
    The artifact store holds the large body.
    """
    kind: str = Field(default="result_ref", description="Type discriminator")
    ref: str = Field(..., description="Logical URI: noetl://execution/<eid>/step/<step>/call/<tool_run_id>")
    store: str = Field(default="inline", description="Storage tier: inline, eventlog, artifact")
    artifact: Optional[ArtifactInfo] = Field(default=None, description="Artifact details when store=artifact")
    preview: Optional[Dict[str, Any]] = Field(default=None, description="Truncated preview for UI")


class Manifest(BaseModel):
    """
    Manifest for aggregated results.
    
    Instead of merging many pages into one giant JSON array,
    a manifest references the parts for streaming-like access.
    """
    kind: str = Field(default="manifest", description="Type discriminator")
    strategy: str = Field(default="append", description="Merge strategy: append, replace, merge")
    merge_path: Optional[str] = Field(default=None, description="Path for nested array merge (e.g., data.items)")
    parts: List[Dict[str, Any]] = Field(default_factory=list, description="List of part references")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Manifest metadata")


class CorrelationKeys(BaseModel):
    """
    Correlation keys for loop/pagination/retry tracking.

    These enable deterministic retrieval of specific pieces.
    Extended for TempRef/Manifest support.
    """
    step_run_id: Optional[str] = Field(default=None, description="Step run identifier")
    tool_run_id: Optional[str] = Field(default=None, description="Tool run identifier")
    iteration: Optional[int] = Field(default=None, description="Loop iteration index")
    iteration_id: Optional[str] = Field(default=None, description="Loop iteration identifier")
    page: Optional[int] = Field(default=None, description="Pagination page number")
    attempt: Optional[int] = Field(default=None, description="Retry attempt number")
    # TempRef/Manifest extensions
    cursor: Optional[str] = Field(default=None, description="Cursor for cursor-based pagination")
    parent_ref: Optional[str] = Field(default=None, description="Parent TempRef/Manifest URI")
    batch_id: Optional[str] = Field(default=None, description="Batch identifier for batch processing")
    manifest_ref: Optional[str] = Field(default=None, description="Associated manifest URI")


class EventPayloadData(BaseModel):
    """
    Structured event payload following the ResultRef specification.
    
    Contains inputs, outputs (inline or ref), and metadata.
    """
    # Input snapshot
    inputs: Optional[Dict[str, Any]] = Field(default=None, description="Rendered input snapshot")
    
    # Output fields (mutually exclusive: output_inline XOR output_ref)
    output_inline: Optional[Any] = Field(default=None, description="Small result body (< inline_max_bytes)")
    output_ref: Optional[ResultRef] = Field(default=None, description="Pointer to externalized result")
    output_select: Optional[Dict[str, Any]] = Field(default=None, description="Selected fields when output_ref used")
    preview: Optional[Dict[str, Any]] = Field(default=None, description="Truncated sample for UI/debugging")
    
    # Error handling
    error: Optional[Dict[str, Any]] = Field(default=None, description="Structured error object")
    
    # Free-form metadata
    meta: Optional[Dict[str, Any]] = Field(default=None, description="HTTP status, row counts, job_id, etc.")
    
    # Correlation keys
    correlation: Optional[CorrelationKeys] = Field(default=None, description="Loop/pagination/retry tracking")
    
    # Event classification for control flow
    actionable: bool = Field(default=False, description="Server should take action (routing, retry)")
    informative: bool = Field(default=True, description="Event is for logging/observability")


# ============================================================================
# Event Types and Status
# ============================================================================

# Event types - past tense to describe what happened
EventType = Literal[
    "playbook_started",
    "playbook_completed",
    "playbook_failed",
    "workflow_initialized",
    "step_started",
    "step_completed",
    "step_failed",
    "step_skipped",
    "step_result",
    "action_started",
    "action_completed",
    "action_failed",
    "iterator_started",      # Iterator/loop execution started
    "iterator_completed",    # Iterator/loop completed all iterations
    "iterator_failed",       # Iterator/loop failed
    "iteration_completed",   # Single iteration within loop completed
    "retry_scheduled",       # Retry attempt scheduled for failed action
    "error",
    "info",
    "warning"
]

# Event status - uppercase to match worker/core status system
EventStatus = Literal[
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "SKIPPED",
    "STARTED",
    "PAUSED"
]


class EventEmitRequest(BaseModel):
    """
    Request schema for emitting an event to the event log.
    
    Minimal schema for direct event emission without business logic processing.
    """
    
    # Required fields
    execution_id: str = Field(
        ...,
        description="Execution ID this event belongs to",
        examples=["478775660589088776"]
    )
    event_type: EventType = Field(
        ...,
        description="Type of event being emitted"
    )
    
    # Optional identification
    event_id: Optional[str] = Field(
        default=None,
        description="Event ID (auto-generated if not provided)",
        examples=["478775660589088777"]
    )
    catalog_id: Optional[str] = Field(
        default=None,
        description="Catalog entry ID if applicable",
        examples=["478775660589088778"]
    )
    parent_event_id: Optional[str] = Field(
        default=None,
        description="Parent event ID for nested events"
    )
    parent_execution_id: Optional[str] = Field(
        default=None,
        description="Parent execution ID for child executions"
    )
    
    # Node information (for step/task events)
    node_id: Optional[str] = Field(
        default=None,
        description="Node/step/task identifier"
    )
    node_name: Optional[str] = Field(
        default=None,
        description="Human-readable node/step name"
    )
    node_type: Optional[str] = Field(
        default=None,
        description="Type of node (step, task, workflow, etc.)"
    )
    
    # Status and context
    status: Optional[EventStatus] = Field(
        default=None,
        description="Event status"
    )
    duration: Optional[float] = Field(
        default=None,
        description="Event duration in seconds (DOUBLE PRECISION)"
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Event context data (arbitrary JSON)"
    )
    result: Optional[Any] = Field(
        default=None,
        description="Event result data (arbitrary JSON - can be dict, list, string, number, etc.)"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if event represents a failure"
    )
    stack_trace: Optional[str] = Field(
        default=None,
        description="Stack trace for error events"
    )
    meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Event metadata (arbitrary JSON)"
    )
    
    # =========================================================================
    # ResultRef pattern fields for efficient result storage
    # 
    # The result column stores either:
    # 1. Inline data: {"data": [...], "status": "success"}
    # 2. ResultRef: {"kind": "ref", "store_tier": "artifact", "logical_uri": "gs://...", "preview": {...}}
    #
    # Use output_inline for small results, output_ref for large externalized results.
    # The service will build the appropriate structure in the result column.
    # =========================================================================
    
    # Structured payload (alternative to flat result field)
    payload_data: Optional[EventPayloadData] = Field(
        default=None,
        description="Structured payload with inputs, outputs, and correlation keys"
    )
    
    # Direct result storage fields
    output_inline: Optional[Any] = Field(
        default=None,
        description="Small result body - stored directly in result column"
    )
    output_ref: Optional[str] = Field(
        default=None,
        description="URI for externalized result (gs://, s3://, artifact://) - builds ResultRef in result column"
    )
    output_select: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Selected fields for templating when output_ref used"
    )
    preview: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Truncated result preview for UI/debugging"
    )
    
    # Correlation keys for loop/pagination/retry
    correlation: Optional[CorrelationKeys] = Field(
        default=None,
        description="Tracking keys: iteration, page, attempt"
    )
    
    # Event classification
    actionable: bool = Field(
        default=False,
        description="If True, server should take action (evaluate case, route, retry)"
    )
    informative: bool = Field(
        default=True,
        description="If True, event is for logging/observability"
    )
    
    # Timestamps
    created_at: Optional[datetime] = Field(
        default=None,
        description="Event creation timestamp (auto-generated if not provided)"
    )
    
    @field_validator('execution_id', 'event_id', 'catalog_id', 'parent_event_id', 'parent_execution_id', 'node_id', mode='before')
    @classmethod
    def coerce_ids_to_string(cls, v):
        """Coerce integers or other types to strings for all ID fields."""
        if v is None:
            return v
        return str(v)


class EventEmitResponse(BaseModel):
    """
    Response schema for event emission.
    
    Returns the emitted event details for confirmation and tracking.
    """
    
    event_id: str = Field(
        ...,
        description="Generated or provided event ID"
    )
    execution_id: str = Field(
        ...,
        description="Execution ID this event belongs to"
    )
    event_type: EventType = Field(
        ...,
        description="Type of event emitted"
    )
    status: str = Field(
        default="emitted",
        description="Emission status"
    )
    created_at: str = Field(
        ...,
        description="Event creation timestamp (ISO format)"
    )
    
    @field_validator('event_id', 'execution_id', mode='before')
    @classmethod
    def coerce_to_string(cls, v):
        """Coerce integers or other types to strings for ID fields."""
        if v is None:
            return v
        return str(v)


class EventQuery(BaseModel):
    """Query parameters for listing events."""
    
    # Filters
    execution_id: Optional[str] = Field(
        None,
        description="Filter by execution ID"
    )
    catalog_id: Optional[str] = Field(
        None,
        description="Filter by catalog ID"
    )
    event_type: Optional[EventType] = Field(
        None,
        description="Filter by event type"
    )
    status: Optional[EventStatus] = Field(
        None,
        description="Filter by status"
    )
    parent_execution_id: Optional[str] = Field(
        None,
        description="Filter by parent execution ID"
    )
    node_name: Optional[str] = Field(
        None,
        description="Filter by node/step name"
    )
    
    # Time range
    start_time: Optional[datetime] = Field(
        None,
        description="Filter events after this time"
    )
    end_time: Optional[datetime] = Field(
        None,
        description="Filter events before this time"
    )
    
    # Pagination
    limit: int = Field(
        default=100,
        le=1000,
        description="Maximum number of results"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Offset for pagination"
    )


class EventResponse(BaseModel):
    """Individual event response."""
    
    event_id: str
    execution_id: str
    catalog_id: Optional[str] = None
    parent_event_id: Optional[str] = None
    parent_execution_id: Optional[str] = None
    event_type: str
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    node_type: Optional[str] = None
    status: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None
    created_at: str
    
    @field_validator('event_id', 'execution_id', 'catalog_id', 'parent_event_id', 'parent_execution_id', mode='before')
    @classmethod
    def coerce_to_string(cls, v):
        """Coerce integers or other types to strings for all ID fields."""
        if v is None:
            return v
        return str(v)


class EventListResponse(BaseModel):
    """Response for event list queries."""
    
    items: list[EventResponse] = Field(
        ...,
        description="List of event responses"
    )
    total: int = Field(
        ...,
        description="Total count of matching events"
    )
    limit: int = Field(
        ...,
        description="Query limit used"
    )
    offset: int = Field(
        ...,
        description="Query offset used"
    )
    has_more: bool = Field(
        ...,
        description="Whether more results exist"
    )

class WorkloadData(BaseModel):
    """
    Workload data structure for context workload retrieval.
    """
    workload: Dict[str, Any] = Field(
        ...,
        description="Workload data as a dictionary"
    )
    path: str = Field(
        ...,
        description="Path associated with the workload"
    )
    version: Optional[int] = Field(
        None,
        description="Version of the workload (integer or None for latest)"
    )
    
    @field_validator('version', mode='before')
    @classmethod
    def coerce_version_to_int(cls, v):
        """Convert version to int if it's not None."""
        if v is None:
            return None
        # Handle both string and int inputs
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                raise ValueError(f"version must be convertible to int, got: {v}")
        return int(v)

__all__ = [
    "EventType",
    "EventStatus",
    "EventEmitRequest",
    "EventEmitResponse",
    "EventQuery",
    "EventResponse",
    "EventListResponse"
]
