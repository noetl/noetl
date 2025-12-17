"""
NoETL DSL v2 Models

Complete redesign with:
- tool.kind pattern for tool configuration
- Step-level case/when/then for event-driven control flow  
- Step-level loop for iteration
- Event-driven architecture (no backward compatibility)
"""

from pydantic import BaseModel, Field, field_validator
from typing import Any, Literal, Optional, Union
from datetime import datetime


# ============================================================================
# Event Payload Models - Typed payloads for different event types
# ============================================================================

class StepEnterPayload(BaseModel):
    """Payload for step.enter event."""
    args: dict[str, Any] = Field(default_factory=dict, description="Step input arguments")
    context: Optional[dict[str, Any]] = Field(None, description="Execution context")


class CallDonePayload(BaseModel):
    """Payload for call.done event (tool execution result)."""
    result: Any = Field(None, description="Tool execution result")
    error: Optional[Union[str, dict[str, Any]]] = Field(None, description="Error details if tool failed (string or dict)")
    duration_ms: Optional[int] = Field(None, description="Tool execution duration in milliseconds")


class StepExitPayload(BaseModel):
    """Payload for step.exit event."""
    result: Any = Field(None, description="Final step result")
    error: Optional[Union[str, dict[str, Any]]] = Field(None, description="Error details if step failed (string or dict)")
    context: Optional[dict[str, Any]] = Field(None, description="Updated execution context")


class LifecycleEventPayload(BaseModel):
    """Payload for lifecycle events (workflow/playbook initialized/completed/failed)."""
    status: str = Field(..., description="Status: initialized, completed, failed")
    final_step: Optional[str] = Field(None, description="Final step name (for completion events)")
    result: Any = Field(None, description="Final result (for completion events)")
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
    args: dict[str, Any] = Field(default_factory=dict, description="Step arguments")
    render_context: dict[str, Any] = Field(default_factory=dict, description="Render context for templates")
    priority: int = Field(default=0, description="Command priority")
    max_attempts: int = Field(default=3, description="Maximum retry attempts")


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
    result: Any = Field(None, description="Command result")


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
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    worker_id: Optional[str] = Field(None, description="Worker that executed the command")
    attempt: int = Field(default=1, description="Attempt number for retries")
    parent_event_id: Optional[int] = Field(None, description="Parent event ID for ordering")


# ============================================================================
# Tool Specification - tool.kind pattern
# ============================================================================

class ToolSpec(BaseModel):
    """
    Tool configuration with tool.kind pattern.
    All execution-specific fields live under tool.
    """
    kind: Literal["http", "postgres", "duckdb", "python", "workbook", "playbook", "playbooks", "secrets", "iterator", "container", "script"] = Field(
        ..., description="Tool type"
    )
    # Tool-specific fields stored as flexible dict
    # Each kind validated in engine based on requirements
    
    class Config:
        extra = "allow"  # Allow additional fields for tool-specific config
    
    def model_post_init(self, __context):
        """Capture all extra fields as tool config."""
        # Store all non-kind fields for tool execution
        pass


# ============================================================================
# Loop Model - Step-level looping
# ============================================================================

class Loop(BaseModel):
    """Step-level loop configuration."""
    in_: str = Field(..., alias="in", description="Jinja expression for collection to iterate over")
    iterator: str = Field(..., description="Variable name for each item")
    mode: Literal["sequential", "parallel", "async"] = Field(default="sequential", description="Execution mode")
    
    class Config:
        populate_by_name = True


# ============================================================================
# Actions - Used inside case.then blocks
# ============================================================================

class NextTarget(BaseModel):
    """Target for next transition."""
    step: str = Field(..., description="Target step name")
    args: Optional[dict[str, Any]] = Field(None, description="Arguments to pass to target step")


# Action types - keeping as simple dicts for flexibility
# The engine will validate structure when processing


# ============================================================================
# ThenBlock - Action container for case.then
# ============================================================================

class ThenBlock(BaseModel):
    """
    Action block inside case.then.
    Flexible structure to support all action types.
    """
    # Store raw actions - will be processed by engine
    raw_actions: list[dict[str, Any]] | dict[str, Any] = Field(..., alias="actions_data")
    
    class Config:
        extra = "allow"
        populate_by_name = True
    
    @classmethod
    def from_data(cls, data: dict | list):
        """Create ThenBlock from raw data."""
        if isinstance(data, list):
            return cls(raw_actions=data)
        else:
            return cls(raw_actions=[data])


# ============================================================================
# CaseEntry - Conditional rule with when/then
# ============================================================================

class CaseEntry(BaseModel):
    """
    Conditional behavior rule.
    Evaluated against event context with Jinja2.
    """
    when: str = Field(..., description="Jinja2 condition expression")
    then: dict[str, Any] | list[dict[str, Any]] = Field(..., description="Actions to execute when condition is true")


# ============================================================================
# Step Model - Workflow node
# ============================================================================

class Step(BaseModel):
    """
    Workflow step with event-driven control flow.
    
    Step-level attributes:
    - step: name (identifier)
    - desc: description
    - args: input arguments (from previous steps)
    - loop: iteration config
    - tool: execution config (tool.kind pattern)
    - case: event-driven conditional rules
    - next: structural default next step(s)
    """
    step: str = Field(..., description="Step name (unique identifier)")
    desc: Optional[str] = Field(None, description="Step description")
    args: Optional[dict[str, Any]] = Field(None, description="Input arguments for this step")
    loop: Optional[Loop] = Field(None, description="Loop configuration")
    tool: ToolSpec = Field(..., description="Tool configuration with tool.kind")
    case: Optional[list[CaseEntry]] = Field(None, description="Event-driven conditional rules")
    next: Optional[str | list[str] | list[dict[str, str]]] = Field(
        None, 
        description="Structural default next step(s) - unconditional"
    )
    
    @field_validator("next", mode="before")
    @classmethod
    def normalize_next(cls, v):
        """Normalize next field - reject old when/then/else patterns."""
        if v is None:
            return None
        
        # If it's a list, check for old patterns
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    # Reject old conditional patterns
                    if "when" in item or "then" in item or "else" in item:
                        raise ValueError(
                            "Conditional 'next' with when/then/else is not allowed. "
                            "Use case/when/then for conditional transitions."
                        )
                    # Allow simple {step: name} format
                    if "step" not in item:
                        raise ValueError(f"Invalid next entry: {item}. Expected {{step: name}}")
        
        return v


# ============================================================================
# Workload and Workbook Models
# ============================================================================

class WorkbookTask(BaseModel):
    """Reusable task definition."""
    name: str = Field(..., description="Task name")
    tool: ToolSpec = Field(..., description="Tool configuration")
    sink: Optional[dict[str, Any]] = Field(None, description="Optional sink configuration")


# ============================================================================
# Playbook Model - Complete workflow definition
# ============================================================================

class Playbook(BaseModel):
    """
    Complete workflow definition (v2).
    
    Structure:
    - apiVersion: noetl.io/v2
    - kind: Playbook
    - metadata: name, path, labels
    - workload: global variables
    - keychain: credential/token definitions (optional)
    - workbook: reusable tasks (optional)
    - workflow: execution flow (must have 'start' step)
    """
    apiVersion: Literal["noetl.io/v2"] = Field(..., description="API version")
    kind: Literal["Playbook"] = Field(..., description="Resource kind")
    metadata: dict[str, Any] = Field(..., description="Metadata (name, path, labels)")
    workload: Optional[dict[str, Any]] = Field(None, description="Global workflow variables")
    keychain: Optional[list[dict[str, Any]]] = Field(None, description="Keychain definitions for credentials and tokens")
    workbook: Optional[list[WorkbookTask]] = Field(None, description="Reusable tasks")
    workflow: list[Step] = Field(..., description="Workflow steps")
    
    @field_validator("workflow")
    @classmethod
    def validate_workflow(cls, v):
        """Ensure workflow has a 'start' step."""
        step_names = [step.step for step in v]
        if "start" not in step_names:
            raise ValueError("Workflow must have a step named 'start'")
        return v
    
    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v):
        """Ensure metadata has required fields."""
        if "name" not in v:
            raise ValueError("Metadata must include 'name'")
        return v


# ============================================================================
# Command Model - Queue table entry
# ============================================================================

class ToolCall(BaseModel):
    """Tool invocation details."""
    kind: str = Field(..., description="Tool kind (http, postgres, python, etc.)")
    config: dict[str, Any] = Field(default_factory=dict, description="Tool-specific configuration")


class Command(BaseModel):
    """
    Command to be executed by worker.
    Written to queue table by server after evaluating events.
    """
    execution_id: str = Field(..., description="Execution identifier")
    step: str = Field(..., description="Step name")
    tool: ToolCall = Field(..., description="Tool invocation details")
    args: Optional[dict[str, Any]] = Field(None, description="Step input arguments")
    render_context: dict[str, Any] = Field(default_factory=dict, description="Full render context for Jinja2 templates (workload, step results, vars)")
    attempt: int = Field(default=1, description="Attempt number for retries")
    priority: int = Field(default=0, description="Command priority (higher = more urgent)")
    backoff: Optional[float] = Field(None, description="Retry backoff delay in seconds")
    max_attempts: Optional[int] = Field(None, description="Maximum retry attempts")
    retry_delay: Optional[float] = Field(None, description="Initial retry delay in seconds")
    retry_backoff: Optional[str] = Field(None, description="Retry backoff strategy: linear or exponential")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    def to_queue_record(self) -> dict[str, Any]:
        """Convert to queue table record format."""
        return {
            "execution_id": self.execution_id,
            "step": self.step,
            "tool_kind": self.tool.kind,
            "tool_config": self.tool.config,
            "args": self.args or {},
            "attempt": self.attempt,
            "priority": self.priority,
            "backoff": self.backoff,
            "max_attempts": self.max_attempts,
            "metadata": self.metadata,
            "status": "pending",
        }
