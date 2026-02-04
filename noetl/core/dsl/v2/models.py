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
    All execution-specific fields live under tool, including output configuration.
    """
    kind: Literal[
        "http",
        "postgres",
        "duckdb",
        "ducklake",
        "python",
        "workbook",
        "playbook",
        "playbooks",
        "secrets",
        "iterator",
        "container",
        "script",
        "snowflake",
        "transfer",
        "snowflake_transfer",
        "gcs",
        "gateway",
        "nats",
        "shell",
        "artifact",
        "noop",      # No-operation tool for case-driven steps
        "pipeline",  # Pipeline execution tool
    ] = Field(
        ..., description="Tool type"
    )
    # Output configuration at tool level (forward reference)
    output: Optional["ToolOutput"] = Field(
        default=None,
        description="Result storage and accumulation configuration"
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
# Pipeline Models - Clojure-style threading with error handling
# ============================================================================

class PipelineControlAction(BaseModel):
    """
    Control action for pipeline error handling.

    Actions:
    - retry: Retry current task (or from a named task)
    - skip: Skip to next task, optionally set _prev
    - jump: Jump to a named task in the pipeline
    - fail: End step with error
    - continue: Continue to next task (implicit on success)
    """
    do: Literal["retry", "skip", "jump", "fail", "continue"] = Field(
        ..., description="Control action type"
    )
    # For retry
    task: Optional[str] = Field(
        None, description="Task to retry (default: current failed task)"
    )
    from_: Optional[str] = Field(
        None, alias="from", description="Restart pipeline from this task"
    )
    attempts: Optional[int] = Field(
        None, description="Max retry attempts"
    )
    backoff: Optional[Literal["none", "linear", "exponential"]] = Field(
        None, description="Backoff strategy"
    )
    delay: Optional[float] = Field(
        None, description="Initial delay in seconds"
    )
    # For skip
    set_prev: Optional[Any] = Field(
        None, description="Value to set as _prev when skipping"
    )
    # For jump
    to: Optional[str] = Field(
        None, description="Task to jump to"
    )

    class Config:
        populate_by_name = True


class CatchCondition(BaseModel):
    """
    Single catch condition in a pipeline's catch block.

    Pattern matching on _task, _err, _attempt to decide control flow.

    Example:
        - when: "{{ _task == 'fetch' and _err.retryable }}"
          do: retry
          attempts: 3
          backoff: exponential
    """
    when: Optional[str] = Field(
        None, description="Jinja2 condition (None for else/default)"
    )
    do: Literal["retry", "skip", "jump", "fail", "continue"] = Field(
        ..., description="Control action"
    )
    # Retry options
    task: Optional[str] = Field(None, description="Task to retry")
    from_: Optional[str] = Field(None, alias="from", description="Restart from task")
    attempts: Optional[int] = Field(None, description="Max attempts")
    backoff: Optional[Literal["none", "linear", "exponential"]] = Field(None)
    delay: Optional[float] = Field(None, description="Initial delay seconds")
    # Skip options
    set_prev: Optional[Any] = Field(None, description="Value for _prev on skip")
    # Jump options
    to: Optional[str] = Field(None, description="Target task for jump")

    class Config:
        populate_by_name = True
        extra = "allow"  # Allow 'else' shorthand


class CatchBlock(BaseModel):
    """
    Pipeline error handling block with cond-style matching.

    Evaluated only when a task fails. First matching condition wins.

    Example:
        catch:
          cond:
            - when: "{{ _task == 'fetch' and _err.retryable }}"
              do: retry
              attempts: 3
            - when: "{{ _task == 'transform' }}"
              do: skip
            - else:
                do: fail
    """
    cond: list[CatchCondition | dict[str, Any]] = Field(
        default_factory=list,
        description="List of condition/action pairs (first match wins)"
    )


class PipelineTask(BaseModel):
    """
    Named task in a pipeline.

    Each task has:
    - name: identifier for _task matching and jump targets
    - tool: tool configuration
    - optional per-task catch override

    Example:
        - fetch:
            tool: {kind: http, url: "..."}
        - transform:
            tool: {kind: python, code: "..."}
    """
    name: str = Field(..., description="Task name (used as _task)")
    tool: dict[str, Any] = Field(..., description="Tool configuration")
    catch: Optional[CatchBlock] = Field(
        None, description="Per-task catch override (optional)"
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineTask":
        """Parse a task from dict like {task_name: {tool: {...}}}."""
        if len(data) != 1:
            raise ValueError(f"Pipeline task must have exactly one key (task name): {data}")
        name = list(data.keys())[0]
        config = data[name]
        if not isinstance(config, dict) or "tool" not in config:
            raise ValueError(f"Pipeline task '{name}' must have 'tool' config: {config}")
        return cls(
            name=name,
            tool=config["tool"],
            catch=CatchBlock(**config["catch"]) if "catch" in config else None
        )


class PipelineBlock(BaseModel):
    """
    Pipeline execution block with Clojure-style threading and error handling.

    Structure:
    - pipe: ordered list of named tasks (data threads via _prev)
    - catch: centralized error handling (cond-style matching)
    - finally: actions to run after successful completion

    Runtime variables:
    - _task: name of current/failed task
    - _prev: result of last successful task (threading)
    - _err: structured error payload {kind, retryable, code, message, source}
    - _attempt: retry attempt count for current task

    Example:
        pipe:
          - fetch: {tool: {kind: http, url: "..."}}
          - transform: {tool: {kind: python, args: {data: "{{ _prev }}"}}}
          - store: {tool: {kind: postgres, data: "{{ _prev }}"}}

        catch:
          cond:
            - when: "{{ _task == 'fetch' and _err.retryable }}"
              do: retry
              attempts: 5
            - when: "{{ _task == 'transform' and _err.kind == 'schema' }}"
              do: skip
            - else:
                do: fail

        finally:
          - collect: {strategy: append, path: data, into: pages}
          - next: [{step: continue_pagination}]
    """
    pipe: list[dict[str, Any]] = Field(
        ..., description="Ordered list of named tasks"
    )
    catch: Optional[CatchBlock] = Field(
        None, description="Error handling block"
    )
    finally_: Optional[list[dict[str, Any]]] = Field(
        None, alias="finally", description="Actions after successful pipeline"
    )

    class Config:
        populate_by_name = True

    def get_tasks(self) -> list[PipelineTask]:
        """Parse pipe list into PipelineTask objects."""
        return [PipelineTask.from_dict(t) for t in self.pipe]

    def get_task_names(self) -> list[str]:
        """Get ordered list of task names."""
        return [list(t.keys())[0] for t in self.pipe]


# ============================================================================
# CaseEntry - Conditional rule with when/then
# ============================================================================

class CaseEntry(BaseModel):
    """
    Conditional behavior rule.
    Evaluated against event context with Jinja2.

    Supports two forms:
    - when: "{{ condition }}" with then: - Standard conditional
    - else: (no when) - Fallback when no conditions matched in inclusive mode
    """
    when: Optional[str] = Field(None, description="Jinja2 condition expression (optional for else clause)")
    then: Optional[dict[str, Any] | list[dict[str, Any]]] = Field(None, description="Actions to execute when condition is true")

    class Config:
        extra = "allow"  # Allow 'else' as alternative to 'then'


# ============================================================================
# Step Spec Model - Step-level behavior configuration
# ============================================================================

class StepSpec(BaseModel):
    """
    Step-level behavior configuration.

    Controls how a step evaluates case conditions:
    - case_mode: exclusive (default, first match wins) or inclusive (all matches execute)
    - eval_mode: on_entry (default, once) or on_event (re-evaluate on every event)
    - timeout: step execution timeout
    - on_error: error handling behavior
    """
    case_mode: Literal["exclusive", "inclusive"] = Field(
        default="exclusive",
        description="Case evaluation mode: exclusive (XOR, first match) or inclusive (OR, all matches)"
    )
    eval_mode: Literal["on_entry", "on_event"] = Field(
        default="on_entry",
        description="Case evaluation timing: on_entry (once) or on_event (every event)"
    )
    timeout: Optional[str] = Field(None, description="Step timeout (e.g., '30s', '5m')")
    on_error: Optional[Literal["fail", "continue", "retry"]] = Field(
        None,
        description="Error handling: fail (default), continue, or retry"
    )


# ============================================================================
# Tool Output Models - Result storage configuration at tool level
# ============================================================================

class OutputStore(BaseModel):
    """
    Storage configuration for tool output.

    Controls where and how tool results are stored externally.
    """
    kind: Literal["auto", "memory", "kv", "object", "s3", "gcs", "db", "duckdb", "eventlog"] = Field(
        default="auto", description="Storage tier (auto selects based on size)"
    )
    driver: Optional[str] = Field(
        default=None, description="Specific driver (e.g., minio for s3)"
    )
    bucket: Optional[str] = Field(default=None, description="Bucket name for object/s3/gcs")
    prefix: Optional[str] = Field(default=None, description="Key prefix for storage")
    ttl: Optional[str] = Field(
        default=None, description="TTL duration (e.g., '2h', '30m', '1d', '1y', 'forever')"
    )
    compression: Literal["none", "gzip", "lz4"] = Field(
        default="none", description="Compression for stored data"
    )
    credential: Optional[str] = Field(
        default=None, description="Keychain credential name for storage access"
    )


class OutputSelect(BaseModel):
    """
    Field selection for output templating.

    Extracts specific fields from large results for efficient access
    without resolving the full result reference.
    """
    path: str = Field(..., description="JSONPath to extract (e.g., $.data.next)")
    as_: str = Field(..., alias="as", description="Variable name to assign extracted value")

    class Config:
        populate_by_name = True


class OutputAccumulate(BaseModel):
    """
    Accumulation configuration for pagination/retry loops.

    Automatically accumulates successful results across retries or pagination
    iterations without explicit storage steps.

    Example:
        accumulate:
          enabled: true
          strategy: concat
          merge_path: "$.data"
          manifest_as: all_pages
    """
    enabled: bool = Field(default=False, description="Enable result accumulation")
    strategy: Literal["append", "replace", "merge", "concat"] = Field(
        default="append", description="How to combine results: append (list), merge (deep), concat (flatten arrays)"
    )
    merge_path: Optional[str] = Field(
        default=None, description="JSONPath for nested array extraction in concat strategy"
    )
    manifest_as: Optional[str] = Field(
        default=None, description="Variable name for accumulated results (default: 'accumulated')"
    )
    on_success: bool = Field(default=True, description="Accumulate successful results")
    on_error: bool = Field(default=False, description="Accumulate error responses")
    max_items: Optional[int] = Field(default=None, description="Maximum items to accumulate")


class ToolOutput(BaseModel):
    """
    Tool-level output configuration.

    Controls how tool results are stored and made available to subsequent steps.
    Lives inside the tool: block, not at step level.

    Example:
        tool:
          kind: http
          endpoint: https://api.example.com/data
          output:
            store:
              kind: auto
              ttl: "1h"
            select:
              - path: "$.pagination.next"
                as: next_cursor
            accumulate:
              enabled: true
              strategy: concat
    """
    store: Optional[OutputStore] = Field(
        default=None, description="Storage tier configuration"
    )
    select: Optional[list[OutputSelect]] = Field(
        default=None, description="Fields to extract for templating (without resolving full ref)"
    )
    accumulate: Optional[OutputAccumulate] = Field(
        default=None, description="Accumulation config for pagination/retry"
    )
    inline_max_bytes: int = Field(
        default=65536, description="Max bytes to store inline in event log (64KB default)"
    )
    preview_max_bytes: int = Field(
        default=1024, description="Max bytes for preview (1KB default)"
    )
    scope: Literal["step", "execution", "workflow", "permanent"] = Field(
        default="execution", description="Lifecycle scope for stored data"
    )
    as_: Optional[str] = Field(
        default=None, alias="as", description="Custom name for this result (for tool chains)"
    )

    class Config:
        populate_by_name = True


# Legacy alias for backwards compatibility
StepOutput = ToolOutput
OutputPublish = OutputAccumulate  # Renamed concept


# ============================================================================
# Step Model - Workflow node
# ============================================================================

class Step(BaseModel):
    """
    Workflow step with event-driven control flow.

    Step-level attributes:
    - step: name (identifier)
    - desc: description
    - spec: step behavior configuration (case_mode, eval_mode, etc.)
    - args: input arguments (from previous steps)
    - loop: iteration config
    - tool: execution config (tool.kind pattern) - includes output config
    - case: event-driven conditional rules
    - next: structural default next step(s)

    Note: Output configuration should be placed inside tool: block.
    Step-level output is deprecated but supported for backwards compatibility.
    """
    step: str = Field(..., description="Step name (unique identifier)")
    desc: Optional[str] = Field(None, description="Step description")
    spec: Optional[StepSpec] = Field(None, description="Step behavior configuration")
    args: Optional[dict[str, Any]] = Field(None, description="Input arguments for this step")
    vars: Optional[dict[str, Any]] = Field(None, description="Variables to extract from step result")
    output: Optional[ToolOutput] = Field(
        None,
        description="DEPRECATED: Use tool.output instead. Step-level output for backwards compatibility."
    )
    result: Optional[dict[str, Any]] = Field(
        None,
        description="Result storage config (output_select, store). Passed to worker for ResultHandler."
    )
    loop: Optional[Loop] = Field(None, description="Loop configuration")
    tool: Optional[ToolSpec] = Field(None, description="Tool configuration with tool.kind and output")
    case: Optional[list[CaseEntry]] = Field(None, description="Event-driven conditional rules")
    next: Optional[str | list[str] | list[dict[str, Any]]] = Field(
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


class CommandSpec(BaseModel):
    """
    Command-level behavior configuration (passed from step.spec).

    Controls case evaluation semantics in the worker:
    - case_mode: exclusive (first match wins) or inclusive (all matches fire)
    - eval_mode: on_entry (once) or on_event (re-evaluate per event)
    """
    case_mode: Literal["exclusive", "inclusive"] = Field(
        default="exclusive",
        description="Case evaluation mode: exclusive (XOR, first match) or inclusive (OR, all matches)"
    )
    eval_mode: Literal["on_entry", "on_event"] = Field(
        default="on_entry",
        description="Case evaluation timing: on_entry (once) or on_event (every event)"
    )


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
    case: Optional[list[dict[str, Any]]] = Field(None, description="Case blocks for immediate worker-side conditional execution (sinks, vars, etc.)")
    spec: Optional[CommandSpec] = Field(None, description="Step behavior configuration (case_mode, eval_mode)")
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
            "case": self.case,  # Include case blocks for worker-side execution
            "spec": self.spec.model_dump() if self.spec else None,  # Include step behavior spec
            "attempt": self.attempt,
            "priority": self.priority,
            "backoff": self.backoff,
            "max_attempts": self.max_attempts,
            "metadata": self.metadata,
            "status": "pending",
        }
