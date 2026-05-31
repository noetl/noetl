from typing import Any, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
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
    """Worker event - reports task completion with result.

    R-1.2 PR-EE-4 finalisation: accepts BOTH the legacy field
    names (``name``, ``payload``, ``execution_id: str``) AND the
    EE-3 / EE-4 canonical names (``event_type``, ``context``,
    ``execution_id: int|str``) on the wire so the Rust worker's
    ``ExecutorEvent`` shape lands cleanly without an extra
    translation layer.  Internally we still expose ``name`` /
    ``payload`` so the engine handlers in
    ``core/events.py::handle_event`` don't need to change.

    The companion ``broker/endpoint.py::emit_event(payload:
    EventEmitRequest)`` route was dead code that never got
    mounted; this change makes the actual mounted ``/api/events``
    endpoint (``core/events.py``) accept the EE wire shape
    directly via Pydantic ``validation_alias`` declarations.
    Surfaced 2026-05-31 by the noetl-worker (Rust) kind-validation
    pass against this broker.
    """

    model_config = ConfigDict(populate_by_name=True)

    execution_id: str = Field(
        ...,
        description="Execution ID.  Accepts JSON string OR JSON "
        "integer on the wire; stringified before storage to "
        "match the bigint-string convention used by the rest of "
        "the API surface.",
    )
    step: str = Field(
        ...,
        description="Step / node name.",
        validation_alias=AliasChoices("step", "node_name"),
    )
    name: str = Field(
        ...,
        description="Event type (e.g. ``step.enter``, ``call.done``, "
        "``step.exit``, ``command.completed``).  The legacy field "
        "name; EE-4 producers may send ``event_type`` instead.",
        validation_alias=AliasChoices("name", "event_type"),
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event payload / result data.  EE-4 producers "
        "may send ``context`` instead.",
        validation_alias=AliasChoices("payload", "context"),
    )
    meta: Optional[dict[str, Any]] = None
    worker_id: Optional[str] = None
    actionable: bool = True
    informative: bool = True

    @field_validator("execution_id", mode="before")
    @classmethod
    def _coerce_execution_id_to_string(cls, v):
        """Accept JSON integer or string for execution_id; the
        rest of the engine treats it as ``str`` (and parses to
        ``int`` only at the SQL boundary)."""
        if v is None:
            return v
        return str(v)

class EventResponse(BaseModel):
    """Response for event."""
    status: str
    event_id: int
    commands_generated: int

class BatchEventItem(BaseModel):
    """A single event within a batch.

    Same EE-4 wire-shape compatibility as :class:`EventRequest` —
    accepts both legacy (``name`` / ``payload``) and EE-3 / EE-4
    canonical (``event_type`` / ``context``) field names.
    """

    model_config = ConfigDict(populate_by_name=True)

    step: str = Field(
        ...,
        description="Step / node name.",
        validation_alias=AliasChoices("step", "node_name"),
    )
    name: str = Field(
        ...,
        description="Event type.",
        validation_alias=AliasChoices("name", "event_type"),
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event payload / result data.",
        validation_alias=AliasChoices("payload", "context"),
    )
    actionable: bool = False
    informative: bool = True
    meta: Optional[dict[str, Any]] = None

class BatchEventRequest(BaseModel):
    """Batch of events for one execution - persisted in a single DB transaction."""
    execution_id: str
    events: list[BatchEventItem]
    worker_id: Optional[str] = None
    catalog_id: Optional[int] = Field(
        default=None,
        description=(
            "Fallback catalog_id for executions that have no prior event "
            "rows (e.g. inline-runner children created in-worker without a "
            "``POST /api/execute`` ingress). The persistence path normally "
            "discovers ``catalog_id`` by querying the first existing event "
            "row for the execution; for inline children there is no such "
            "row yet, so the caller must supply it. Ignored when the "
            "execution already has events written — the DB-discovered value "
            "wins to keep cross-batch event rows consistent."
        ),
    )

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
    locality: Optional[dict[str, Any]] = None

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
