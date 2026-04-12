from __future__ import annotations

from .common import *

class StepEnterPayload(BaseModel):
    """Payload for step.enter event."""
    input: dict[str, Any] = Field(default_factory=dict, description="Step input bindings")
    context: Optional[dict[str, Any]] = Field(None, description="Execution context")

    @model_validator(mode='before')
    @classmethod
    def _reject_legacy_fields(cls, obj):
        """Reject legacy payload aliases to keep event contracts unambiguous."""
        if isinstance(obj, dict) and "args" in obj:
            raise ValueError("step.enter payload must use 'input' (legacy 'args' is not allowed)")
        return obj


class CallDonePayload(BaseModel):
    """Payload for call.done event (tool execution result)."""
    result: Any = Field(None, description="Control-plane result envelope (status/reference/context)")
    error: Optional[Union[str, dict[str, Any]]] = Field(None, description="Error details if tool failed (string or dict)")
    duration_ms: Optional[int] = Field(None, description="Tool execution duration in milliseconds")


class StepExitPayload(BaseModel):
    """Payload for step.exit event."""
    result: Any = Field(None, description="Final control-plane result envelope")
    error: Optional[Union[str, dict[str, Any]]] = Field(None, description="Error details if step failed (string or dict)")
    context: Optional[dict[str, Any]] = Field(None, description="Updated execution context")


class LifecycleEventPayload(BaseModel):
    """Payload for lifecycle events (workflow/playbook initialized/completed/failed)."""
    status: str = Field(..., description="Status: initialized, completed, failed")
    final_step: Optional[str] = Field(None, description="Final step name (for completion events)")
    result: Any = Field(None, description="Final control-plane result envelope (for completion events)")
    error: Optional[Union[str, dict[str, Any]]] = Field(None, description="Error details (for failed events, string or dict)")


class LoopItemPayload(BaseModel):
    """Payload for loop.item event."""
    item: Any = Field(..., description="Current loop item")
    index: int = Field(..., description="Loop iteration index")
    iterator: str = Field(..., description="Iterator variable name")


class LoopDonePayload(BaseModel):
    """Payload for loop.done event."""
    iterations: int = Field(..., description="Total number of iterations")
    results: list[Any] = Field(default_factory=list, description="Results from all iterations")


class CommandIssuedPayload(BaseModel):
    """Payload for command.issued event."""
    command_id: str = Field(..., description="Unique command identifier")
    step: str = Field(..., description="Step name")
    tool_kind: str = Field(..., description="Tool type")
    tool_config: dict[str, Any] = Field(default_factory=dict, description="Tool configuration")
    input: dict[str, Any] = Field(default_factory=dict, description="Step input bindings")
    render_context: dict[str, Any] = Field(default_factory=dict, description="Render context for templates")
    priority: int = Field(default=0, description="Command priority")
    max_attempts: int = Field(default=3, description="Maximum retry attempts")

    @model_validator(mode='before')
    @classmethod
    def _reject_legacy_fields(cls, obj):
        """Reject legacy payload aliases to keep command contracts strict."""
        if isinstance(obj, dict) and "args" in obj:
            raise ValueError("command.issued payload must use 'input' (legacy 'args' is not allowed)")
        return obj


class CommandClaimedPayload(BaseModel):
    """Payload for command.claimed event."""
    command_id: str = Field(..., description="Command identifier")
    worker_id: str = Field(..., description="Worker that claimed the command")
    claim_timestamp: datetime = Field(default_factory=datetime.utcnow, description="When command was claimed")


class CommandStartedPayload(BaseModel):
    """Payload for command.started event."""
    command_id: str = Field(..., description="Command identifier")
    worker_id: str = Field(..., description="Worker executing the command")


class CommandCompletedPayload(BaseModel):
    """Payload for command.completed event."""
    command_id: str = Field(..., description="Command identifier")
    worker_id: str = Field(..., description="Worker that completed the command")
    result: Any = Field(None, description="Command control-plane result envelope")


class CommandFailedPayload(BaseModel):
    """Payload for command.failed event."""
    command_id: str = Field(..., description="Command identifier")
    worker_id: str = Field(..., description="Worker that failed the command")
    error: Union[str, dict[str, Any]] = Field(..., description="Error details")
    attempts: int = Field(..., description="Number of attempts made")


# Union type for all event payloads (for type hints, not runtime validation)
EventPayload = Union[
    StepEnterPayload,
    CallDonePayload,
    StepExitPayload,
    LifecycleEventPayload,
    LoopItemPayload,
    LoopDonePayload,
    CommandIssuedPayload,
    CommandClaimedPayload,
    CommandStartedPayload,
    CommandCompletedPayload,
    CommandFailedPayload,
    dict[str, Any]  # Runtime: always dict
]


# ============================================================================
# Event Model - Internal events emitted during step execution
# ============================================================================

class Event(BaseModel):
    """
    Event emitted during workflow execution.

    Event names:
    - step.enter: Before step starts
    - call.done: After tool call completes (success or error)
    - step.exit: When step is done (result known)
    - loop.item: On each loop iteration
    - loop.done: When loop completes
    - command.issued: Server generated command for worker
    - command.claimed: Worker claimed command for execution
    - command.started: Worker started executing command
    - command.completed: Worker completed command successfully
    - command.failed: Worker failed to complete command after retries
    - playbook_initialized: Playbook execution begins
    - playbook_completed: Playbook execution succeeds
    - playbook_failed: Playbook execution fails
    - workflow_initialized: Workflow begins
    - workflow_completed: Workflow completes successfully
    - workflow_failed: Workflow fails
    """
    execution_id: str = Field(..., description="Execution identifier")
    step: Optional[str] = Field(None, description="Step name that emitted the event")
    name: str = Field(..., description="Event name (step.enter, call.done, step.exit, command.*, etc.)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event data (response, error, metadata) - always dict at runtime")
    meta: Optional[dict[str, Any]] = Field(default_factory=dict, description="Event metadata (command_id, etc)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    worker_id: Optional[str] = Field(None, description="Worker that executed the command")
    attempt: int = Field(default=1, description="Attempt number for retries")
    parent_event_id: Optional[int] = Field(None, description="Parent event ID for ordering")


# ============================================================================
# Policy Rule Models - Canonical v10 policy structure
# ============================================================================

