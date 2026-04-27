from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator
from .core import _BATCH_MAX_EVENTS_PER_REQUEST, _BATCH_MAX_PAYLOAD_BYTES
from .utils import _estimate_json_size

class ExecuteRequest(BaseModel):
    """Request to start playbook execution."""
    path: Optional[str] = Field(None, description="Playbook catalog path")
    catalog_id: Optional[int] = Field(None, description="Catalog ID (alternative to path)")
    version: Optional[int] = Field(None, description="Specific version to execute (used with path)")
    resource_kind: Optional[str] = Field(
        None,
        description="Executable catalog kind to run. Defaults to playbook or agent.",
    )
    payload: dict[str, Any] = Field(default_factory=dict, alias="workload", description="Input payload/workload")
    parent_execution_id: Optional[int] = Field(None, description="Parent execution ID")

    class Config:
        populate_by_name = True  # Allow both 'payload' and 'workload' field names

    @model_validator(mode='after')
    def validate_path_or_catalog_id(self):
        if not self.path and not self.catalog_id:
            raise ValueError("Either 'path' or 'catalog_id' must be provided")
        return self

# Alias for backward compatibility
StartExecutionRequest = ExecuteRequest

class ExecuteResponse(BaseModel):
    """Response for starting execution."""
    execution_id: str
    status: str
    commands_generated: int

class EventRequest(BaseModel):
    """Worker event - reports task completion with result."""
    execution_id: str
    step: str
    name: str  # step.enter, call.done, step.exit
    payload: dict[str, Any] = Field(default_factory=dict)
    meta: Optional[dict[str, Any]] = None
    worker_id: Optional[str] = None
    actionable: bool = True
    informative: bool = True

class EventResponse(BaseModel):
    """Response for event."""
    status: str
    event_id: int
    commands_generated: int

class BatchEventItem(BaseModel):
    """A single event within a batch."""
    step: str
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    actionable: bool = False
    informative: bool = True
    meta: Optional[dict[str, Any]] = None

class BatchEventRequest(BaseModel):
    """Batch of events for one execution - persisted in a single DB transaction."""
    execution_id: str
    events: list[BatchEventItem]
    worker_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_batch_limits(self):
        event_count = len(self.events or [])
        if event_count > _BATCH_MAX_EVENTS_PER_REQUEST:
            raise ValueError(
                f"Batch contains {event_count} events; limit is {_BATCH_MAX_EVENTS_PER_REQUEST}"
            )

        if event_count > 0:
            estimated_bytes = _estimate_json_size([evt.payload for evt in self.events])
            if estimated_bytes > _BATCH_MAX_PAYLOAD_BYTES:
                raise ValueError(
                    "Batch payload exceeds configured limit "
                    f"({_BATCH_MAX_PAYLOAD_BYTES} bytes)"
                )
        return self

class BatchEventResponse(BaseModel):
    """Response for async batch event acceptance."""
    status: str
    request_id: str
    event_ids: list[int] = Field(default_factory=list)
    commands_generated: int = 0
    queue_depth: int = 0
    duplicate: bool = False
    idempotency_key: Optional[str] = None

class ClaimRequest(BaseModel):
    """Request to claim a command."""
    worker_id: str

class ClaimResponse(BaseModel):
    """Response for successful claim with command details."""
    status: str
    event_id: int
    execution_id: int
    node_id: str
    node_name: str
    action: str  # tool_kind
    context: dict[str, Any]
    meta: dict[str, Any]
