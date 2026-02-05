"""
NoETL DSL v2 Models - Canonical Format

Canonical DSL implementation with:
- tool as ordered pipeline (list of labeled tasks) or single tool shorthand
- step.when for transition enable guard
- next[].when for conditional routing
- loop.spec.mode for iteration mode
- tool.eval for per-task flow control
- No case/when/then blocks (removed)
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

    The eval: field provides tool-level flow control, evaluated after each execution.
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
        "noop",           # No-operation tool for case-driven steps
        "task_sequence",  # Task sequence execution (replaces pipeline)
        "rhai",           # Rhai scripting engine for polling/async operations
    ] = Field(
        ..., description="Tool type"
    )
    # Flow control: evaluated after tool execution
    eval: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="Tool-level flow control conditions (EvalCondition list)"
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
# Loop Model - Step-level looping (Canonical format)
# ============================================================================

class LoopSpec(BaseModel):
    """
    Loop runtime specification (canonical format).

    Controls loop execution behavior:
    - mode: sequential (default) or parallel
    - max_in_flight: max concurrent iterations in parallel mode
    """
    mode: Literal["sequential", "parallel"] = Field(
        default="sequential",
        description="Execution mode: sequential (one at a time) or parallel (concurrent)"
    )
    max_in_flight: Optional[int] = Field(
        None,
        description="Maximum concurrent iterations in parallel mode"
    )


class Loop(BaseModel):
    """
    Step-level loop configuration (canonical format).

    Canonical format:
        loop:
          spec:
            mode: parallel
            max_in_flight: 5
          in: "{{ workload.items }}"
          iterator: item
    """
    spec: Optional[LoopSpec] = Field(None, description="Loop runtime specification")
    in_: str = Field(..., alias="in", description="Jinja expression for collection to iterate over")
    iterator: str = Field(..., description="Variable name for each item (binds iter.<iterator>)")

    class Config:
        populate_by_name = True

    @property
    def mode(self) -> str:
        """Get loop mode from spec (for backward compatibility)."""
        return self.spec.mode if self.spec else "sequential"


# ============================================================================
# NextTarget - Simple next target (for backward compatibility)
# ============================================================================

class NextTarget(BaseModel):
    """Simple target for next transition (backward compatibility)."""
    step: str = Field(..., description="Target step name")
    args: Optional[dict[str, Any]] = Field(None, description="Arguments to pass to target step")


# ============================================================================
# Tool-Level Eval Models - Flow control at task level
# ============================================================================

class EvalCondition(BaseModel):
    """
    Single eval condition for tool-level flow control.

    Evaluated after tool execution using the outcome object.
    First matching condition wins (or else clause if no expr).

    Default behavior (if tool.eval is omitted):
    - success → continue
    - error → fail

    If tool.eval is present and no clause matches, same default applies
    unless an else clause is provided.

    Variable scoping:
    - set_vars: Updates step-scoped vars (visible to subsequent tools in same
      then: list and to later case evaluation within same step)
    - set_iter: Updates iteration-scoped vars (only in parallel loops, isolated
      per iteration)
    - _prev is pipeline-local and only valid during then: list execution

    Example:
        eval:
          - expr: "{{ outcome.status == 'error' and outcome.error.retryable == true }}"
            do: retry
            attempts: 3
            backoff: exponential
            delay: 1.0

          - expr: "{{ outcome.status == 'error' }}"
            do: fail

          - else:
              do: continue
              set_vars:
                has_more: "{{ outcome.result.data.paging.hasMore }}"
    """
    expr: Optional[str] = Field(
        None, description="Jinja2 expression (None for else/default clause)"
    )
    do: Literal["continue", "retry", "break", "jump", "fail"] = Field(
        default="continue", description="Control action"
    )
    # Retry options
    attempts: Optional[int] = Field(None, description="Max retry attempts")
    backoff: Optional[Literal["none", "linear", "exponential"]] = Field(
        None, description="Backoff strategy"
    )
    delay: Optional[float] = Field(None, description="Initial delay in seconds")
    # Jump option
    to: Optional[str] = Field(None, description="Target task label for jump action")
    # Variable setting (step-scoped by default)
    set_vars: Optional[dict[str, Any]] = Field(
        None, description="Variables to set in step scope (visible to subsequent tools and case evaluation)"
    )
    # Iteration-scoped variables (for parallel loops)
    set_iter: Optional[dict[str, Any]] = Field(
        None, description="Variables to set in iteration scope (isolated per parallel loop iteration)"
    )

    class Config:
        extra = "allow"  # Allow 'else' shorthand: - else: {do: continue}


class ToolOutcome(BaseModel):
    """
    Structured result of tool execution, available in eval expressions as 'outcome'.

    Contains:
    - status: success or error
    - result: tool output (if success)
    - error: structured error info (if error)
    - meta: execution metadata (attempt, duration_ms)
    - Tool-specific helpers: http, pg, py

    Example outcome:
        outcome = {
            "status": "error",
            "error": {
                "kind": "rate_limit",
                "retryable": True,
                "code": "HTTP_429",
                "message": "Rate limit exceeded",
                "retry_after": 5
            },
            "meta": {"attempt": 1, "duration_ms": 150},
            "http": {"status": 429, "headers": {...}}
        }
    """
    status: Literal["success", "error"] = Field(..., description="Execution status")
    result: Any = Field(None, description="Tool output (if success)")
    error: Optional[dict[str, Any]] = Field(
        None, description="Structured error {kind, retryable, code, message, ...}"
    )
    meta: Optional[dict[str, Any]] = Field(
        None, description="Execution metadata {attempt, duration_ms}"
    )
    # Tool-specific helpers
    http: Optional[dict[str, Any]] = Field(
        None, description="HTTP-specific info {status, headers}"
    )
    pg: Optional[dict[str, Any]] = Field(
        None, description="PostgreSQL-specific info {code, sqlstate}"
    )
    py: Optional[dict[str, Any]] = Field(
        None, description="Python-specific info {exception, traceback}"
    )

    class Config:
        extra = "allow"  # Allow additional tool-specific fields


# ============================================================================
# CaseEntry - DEPRECATED (kept for migration tooling only)
# ============================================================================

class CaseEntry(BaseModel):
    """
    DEPRECATED: Use step.when for enable guards and next[].when for routing.
    Kept only for migration tooling to read old playbooks.
    """
    when: Optional[str] = Field(None, description="DEPRECATED")
    then: Optional[dict[str, Any] | list[dict[str, Any]]] = Field(None, description="DEPRECATED")

    class Config:
        extra = "allow"


# ============================================================================
# Step Spec Model - Step-level behavior configuration (Canonical format)
# ============================================================================

class StepSpec(BaseModel):
    """
    Step-level behavior configuration (canonical format).

    Controls step execution behavior:
    - next_mode: exclusive (default, first match) or inclusive (all matches fire)
    - timeout: step execution timeout
    - on_error: error handling behavior
    """
    next_mode: Literal["exclusive", "inclusive"] = Field(
        default="exclusive",
        description="Next evaluation mode: exclusive (first matching next fires) or inclusive (all matching fire)"
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
# Canonical Next Target - Conditional routing (replaces case-based routing)
# ============================================================================

class CanonicalNextTarget(BaseModel):
    """
    Target for next transition with optional conditional routing (canonical format).

    Replaces case-based routing with declarative next[].when conditions.

    Example:
        next:
          - step: success_handler
            when: "{{ outcome.status == 'success' }}"
            args:
              data: "{{ outcome.result }}"
          - step: error_handler
            when: "{{ outcome.status == 'error' }}"
    """
    step: str = Field(..., description="Target step name")
    spec: Optional[dict[str, Any]] = Field(None, description="Optional edge semantics")
    when: Optional[str] = Field(None, description="Transition guard expression (Jinja2)")
    args: Optional[dict[str, Any]] = Field(None, description="Token payload to pass to target step")


# ============================================================================
# Step Model - Workflow node (Canonical format)
# ============================================================================

class Step(BaseModel):
    """
    Workflow step in canonical format.

    Canonical step structure:
    - step: name (unique identifier)
    - desc: description
    - spec: step behavior (next_mode, timeout, on_error)
    - when: transition enable guard (evaluated by server on input token)
    - loop: optional loop wrapper with spec.mode
    - tool: ordered pipeline (list of labeled tasks) OR single tool shorthand
    - next: outgoing arcs with optional when conditions for routing

    Example (pipeline):
        - step: fetch_transform
          when: "{{ workload.enabled }}"
          tool:
            - fetch:
                kind: http
                url: "..."
                eval:
                  - expr: "{{ outcome.status == 'error' }}"
                    do: fail
            - transform:
                kind: python
                args: { data: "{{ _prev }}" }
          next:
            - step: success
              when: "{{ outcome.status == 'success' }}"
            - step: failure
              when: "{{ outcome.status == 'error' }}"

    Example (single tool shorthand):
        - step: simple_fetch
          tool:
            kind: http
            url: "..."
          next:
            - step: process
    """
    step: str = Field(..., description="Step name (unique identifier)")
    desc: Optional[str] = Field(None, description="Step description")
    spec: Optional[StepSpec] = Field(None, description="Step behavior configuration (next_mode, timeout)")

    # Canonical: transition enable guard (replaces case for enable)
    when: Optional[str] = Field(
        None,
        description="Transition enable guard - Jinja2 expression evaluated by server on input token"
    )

    args: Optional[dict[str, Any]] = Field(None, description="Input arguments for this step")
    vars: Optional[dict[str, Any]] = Field(None, description="Variables to extract from step result")
    output: Optional[ToolOutput] = Field(
        None,
        description="Step-level output configuration (tool.output preferred)"
    )
    result: Optional[dict[str, Any]] = Field(
        None,
        description="Result storage config (output_select, store). Passed to worker for ResultHandler."
    )
    loop: Optional[Loop] = Field(None, description="Loop configuration with spec.mode")

    # Canonical: tool is either single ToolSpec (shorthand) or list of labeled tasks (pipeline)
    tool: Optional[Union[ToolSpec, list[dict[str, Any]]]] = Field(
        None,
        description="Tool pipeline (list of labeled tasks) or single tool shorthand"
    )

    # Canonical: next with optional when conditions for routing
    next: Optional[Union[str, list[str], list[dict[str, Any]]]] = Field(
        None,
        description="Next step(s) with optional when conditions for conditional routing"
    )

    @field_validator("next", mode="before")
    @classmethod
    def normalize_next(cls, v):
        """Normalize next field - validate canonical format."""
        if v is None:
            return None

        # String shorthand: next: "step_name"
        if isinstance(v, str):
            return v

        # List format
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    continue  # Simple step name
                if isinstance(item, dict):
                    # Canonical format: {step: name, when: "...", args: {...}}
                    if "step" not in item:
                        raise ValueError(f"Invalid next entry: {item}. Must have 'step' field")
                    # Reject old then/else patterns (but allow when - that's canonical!)
                    if "then" in item or "else" in item:
                        raise ValueError(
                            "Invalid next entry: 'then' and 'else' not allowed in next[]. "
                            "Use next[].when for conditional routing."
                        )

        return v

    @field_validator("tool", mode="before")
    @classmethod
    def normalize_tool(cls, v):
        """Normalize tool field - accept both single and list formats."""
        if v is None:
            return None

        # Single tool shorthand: tool: {kind: http, ...}
        if isinstance(v, dict) and "kind" in v:
            return v  # Keep as single ToolSpec for shorthand

        # Pipeline format: tool: [- label: {kind: ...}]
        if isinstance(v, list):
            # Validate each task has proper structure
            for i, task in enumerate(v):
                if not isinstance(task, dict):
                    raise ValueError(f"tool[{i}] must be an object")
                if len(task) != 1:
                    raise ValueError(
                        f"tool[{i}] must have exactly one key (the task label). Got: {list(task.keys())}"
                    )
                label, config = next(iter(task.items()))
                if not isinstance(config, dict):
                    raise ValueError(f"tool[{i}].{label} must be an object")
                if "kind" not in config:
                    raise ValueError(f"tool[{i}].{label} must have 'kind' field")
            return v

        raise ValueError("tool must be an object with 'kind' or a list of labeled tasks")


# ============================================================================
# Workload and Workbook Models
# ============================================================================

class WorkbookTask(BaseModel):
    """Reusable task definition."""
    name: str = Field(..., description="Task name")
    tool: ToolSpec = Field(..., description="Tool configuration")
    sink: Optional[dict[str, Any]] = Field(None, description="Optional sink configuration")


# ============================================================================
# Executor Models - Runtime requirements and workflow control
# ============================================================================

class ExecutorSpec(BaseModel):
    """
    Executor specification for workflow entry and termination control.

    Controls:
    - entry_step: Override default entry (workflow[0])
    - final_step: Optional finalization step run after quiescence
    - no_next_is_error: Treat "no next match" as error (default: false = branch terminates)
    """
    entry_step: Optional[str] = Field(
        None,
        description="Override entry step (default: workflow[0].step)"
    )
    final_step: Optional[str] = Field(
        None,
        description="Optional finalization step run after workflow quiescence"
    )
    no_next_is_error: Optional[bool] = Field(
        None,
        description="Treat 'no matching next arc' as error (default: false = branch terminates)"
    )


class ExecutorRequires(BaseModel):
    """Executor capability requirements."""
    tools: Optional[list[str]] = Field(None, description="Required tool kinds")
    features: Optional[list[str]] = Field(None, description="Required runtime features")


class Executor(BaseModel):
    """
    Executor configuration - runtime requirements and workflow control.

    Controls:
    - profile: Runtime profile (local, distributed, auto)
    - version: Semantic contract version
    - requires: Capability requirements
    - spec: Entry/final step configuration
    """
    profile: Literal["local", "distributed", "auto"] = Field(
        default="auto",
        description="Runtime profile: local, distributed, or auto"
    )
    version: str = Field(
        default="noetl-runtime/1",
        description="Semantic contract version"
    )
    requires: Optional[ExecutorRequires] = Field(
        None,
        description="Required capabilities (tools, features)"
    )
    spec: Optional[ExecutorSpec] = Field(
        None,
        description="Executor spec for entry/final step configuration"
    )


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
    - executor: runtime configuration (profile, spec with entry_step/final_step)
    - workload: global variables
    - keychain: credential/token definitions (optional)
    - workbook: reusable tasks (optional)
    - workflow: execution flow (entry determined by executor.spec.entry_step or workflow[0])

    Canonical Entry Selection:
    1. executor.spec.entry_step if configured
    2. workflow[0].step (first step in workflow array)
    """
    apiVersion: Literal["noetl.io/v2"] = Field(..., description="API version")
    kind: Literal["Playbook"] = Field(..., description="Resource kind")
    metadata: dict[str, Any] = Field(..., description="Metadata (name, path, labels)")
    executor: Optional[Executor] = Field(
        None,
        description="Executor configuration (profile, version, requires, spec)"
    )
    workload: Optional[dict[str, Any]] = Field(None, description="Global workflow variables")
    keychain: Optional[list[dict[str, Any]]] = Field(None, description="Keychain definitions for credentials and tokens")
    workbook: Optional[list[WorkbookTask]] = Field(None, description="Reusable tasks")
    workflow: list[Step] = Field(..., description="Workflow steps")

    @field_validator("workflow")
    @classmethod
    def validate_workflow(cls, v):
        """Validate workflow has at least one step."""
        if not v:
            raise ValueError("Workflow must have at least one step")
        return v

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v):
        """Ensure metadata has required fields."""
        if "name" not in v:
            raise ValueError("Metadata must include 'name'")
        return v

    def get_entry_step(self) -> str:
        """
        Get the entry step name using canonical rules.

        Priority:
        1. executor.spec.entry_step if configured
        2. workflow[0].step (first step in workflow array)

        Returns:
            Entry step name
        """
        if self.executor and self.executor.spec and self.executor.spec.entry_step:
            return self.executor.spec.entry_step
        return self.workflow[0].step if self.workflow else "start"

    def get_final_step(self) -> Optional[str]:
        """
        Get the optional final step name.

        Returns:
            Final step name or None if not configured
        """
        if self.executor and self.executor.spec:
            return self.executor.spec.final_step
        return None


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

    Controls execution semantics:
    - next_mode: exclusive (first match) or inclusive (all matching next[] fire)
    """
    next_mode: Literal["exclusive", "inclusive"] = Field(
        default="exclusive",
        description="Next evaluation mode: exclusive (first match) or inclusive (all matches)"
    )


class Command(BaseModel):
    """
    Command to be executed by worker (canonical format).
    Written to queue table by server after evaluating events.
    """
    execution_id: str = Field(..., description="Execution identifier")
    step: str = Field(..., description="Step name")
    tool: ToolCall = Field(..., description="Tool invocation details")
    args: Optional[dict[str, Any]] = Field(None, description="Step input arguments")
    render_context: dict[str, Any] = Field(default_factory=dict, description="Full render context for Jinja2 templates")

    # Pipeline: list of labeled tasks when tool is a pipeline
    pipeline: Optional[list[dict[str, Any]]] = Field(
        None,
        description="Pipeline tasks (list of labeled tasks) for task_sequence execution"
    )

    # Next targets: for conditional routing after step completion
    next_targets: Optional[list[dict[str, Any]]] = Field(
        None,
        description="Next targets with optional when conditions for routing"
    )

    spec: Optional[CommandSpec] = Field(None, description="Step behavior configuration (next_mode)")
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
            "pipeline": self.pipeline,
            "next_targets": self.next_targets,
            "spec": self.spec.model_dump() if self.spec else None,
            "attempt": self.attempt,
            "priority": self.priority,
            "backoff": self.backoff,
            "max_attempts": self.max_attempts,
            "metadata": self.metadata,
            "status": "pending",
        }
