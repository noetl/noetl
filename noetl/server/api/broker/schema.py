"""
NoETL Event API Schemas - Request/Response models for event emission endpoints.

Simple event emission without business logic - direct database operations only.
"""

from typing import Optional, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


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
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Event result data (arbitrary JSON)"
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
