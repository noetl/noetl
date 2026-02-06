"""
NoETL DSL v2 Models - Canonical v10 Format

Canonical v10 implementation with:
- `when` is the ONLY conditional keyword (no `expr`)
- All knobs live under `spec` (at any level)
- Policies live under `spec.policy` and are typed by scope
- Task outcome handling uses `task.spec.policy` object with required `rules:`
- Routing uses Petri-net arcs: `step.next` is object with `next.spec` + `next.arcs[]`
- No special "sink" tool kind - storage is just tools returning references
- Loop is a step modifier (not a tool kind)
- NO `step.when` field - step admission via `step.spec.policy.admit.rules`
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
# Policy Rule Models - Canonical v10 policy structure
# ============================================================================

class PolicyRuleThen(BaseModel):
    """
    Action specification for a policy rule (canonical v10).

    Contains the control directive and optional parameters.
    """
    do: Literal["continue", "retry", "break", "jump", "fail"] = Field(
        ..., description="Control action (REQUIRED)"
    )
    # For admit policies
    allow: Optional[bool] = Field(None, description="Allow/deny for admission rules")
    # Retry options
    attempts: Optional[int] = Field(None, description="Max retry attempts")
    backoff: Optional[Literal["none", "linear", "exponential"]] = Field(
        None, description="Backoff strategy"
    )
    delay: Optional[float] = Field(None, description="Initial delay in seconds")
    # Jump option
    to: Optional[str] = Field(None, description="Target task label for jump action")
    # Variable mutations
    set_ctx: Optional[dict[str, Any]] = Field(
        None, description="Patches to execution-scoped context"
    )
    set_iter: Optional[dict[str, Any]] = Field(
        None, description="Patches to iteration-scoped context"
    )

    class Config:
        extra = "allow"


class PolicyRule(BaseModel):
    """
    Single policy rule (canonical v10).

    Uses `when` as the ONLY conditional keyword.
    First matching rule wins (or else clause if no when).

    Example:
        - when: "{{ outcome.status == 'error' and outcome.error.retryable }}"
          then: { do: retry, attempts: 3, backoff: exponential }
        - else:
            then: { do: continue }
    """
    when: Optional[str] = Field(
        None, description="Jinja2 condition expression (None for else clause)"
    )
    then: PolicyRuleThen = Field(..., description="Action to take when condition matches")

    class Config:
        extra = "allow"  # Allow 'else' shorthand


class AdmitPolicy(BaseModel):
    """
    Step admission policy (server-side, canonical v10).

    Evaluated before scheduling a step.
    If omitted, default is allow.

    Example:
        admit:
          mode: exclusive
          rules:
            - when: "{{ ctx.enabled }}"
              then: { allow: true }
            - else:
                then: { allow: false }
    """
    mode: Literal["exclusive", "inclusive"] = Field(
        default="exclusive",
        description="Evaluation mode (exclusive = first match wins)"
    )
    rules: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Admission rules with when/then"
    )


class TaskPolicy(BaseModel):
    """
    Task outcome policy (worker-side, canonical v10).

    MUST be an object with required `rules:` list.
    This is the ONLY place where control actions (retry/jump/break/fail/continue) are allowed.

    Example:
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 1.0 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: continue, set_iter: { has_more: "{{ outcome.result.paging.hasMore }}" } }
    """
    mode: Literal["exclusive", "inclusive"] = Field(
        default="exclusive",
        description="Evaluation mode (exclusive = first match wins)"
    )
    on_unmatched: Literal["continue", "fail"] = Field(
        default="continue",
        description="Default action if no rule matches and no else clause"
    )
    rules: list[dict[str, Any]] = Field(
        ..., description="Policy rules with when/then (REQUIRED)"
    )
    # Optional lifecycle hooks (placeholders for future)
    before: Optional[list[dict[str, Any]]] = Field(None, description="Pre-execution hooks (placeholder)")
    after: Optional[list[dict[str, Any]]] = Field(None, description="Post-execution hooks (placeholder)")
    finally_: Optional[list[dict[str, Any]]] = Field(None, alias="finally", description="Cleanup hooks (placeholder)")

    class Config:
        populate_by_name = True


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
    """
    enabled: bool = Field(default=False, description="Enable result accumulation")
    strategy: Literal["append", "replace", "merge", "concat"] = Field(
        default="append", description="How to combine results"
    )
    merge_path: Optional[str] = Field(
        default=None, description="JSONPath for nested array extraction in concat strategy"
    )
    manifest_as: Optional[str] = Field(
        default=None, description="Variable name for accumulated results"
    )
    on_success: bool = Field(default=True, description="Accumulate successful results")
    on_error: bool = Field(default=False, description="Accumulate error responses")
    max_items: Optional[int] = Field(default=None, description="Maximum items to accumulate")


class ToolOutput(BaseModel):
    """
    Tool-level output configuration.

    Controls how tool results are stored and made available to subsequent steps.
    Lives inside the tool: block, not at step level.
    """
    store: Optional[OutputStore] = Field(
        default=None, description="Storage tier configuration"
    )
    select: Optional[list[OutputSelect]] = Field(
        default=None, description="Fields to extract for templating"
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
        default=None, alias="as", description="Custom name for this result"
    )

    class Config:
        populate_by_name = True


# ============================================================================
# Task Spec Models - Tool/task level configuration (canonical v10)
# ============================================================================

class TaskSpec(BaseModel):
    """
    Task-level spec configuration (canonical v10).

    Contains task policy for outcome handling.
    Policy is the ONLY place where control actions are allowed.
    """
    timeout: Optional[dict[str, Any]] = Field(
        None, description="Timeout config { connect: 5, read: 15 }"
    )
    policy: Optional[TaskPolicy] = Field(
        None, description="Task outcome policy with rules"
    )

    class Config:
        extra = "allow"


# ============================================================================
# Tool Specification - tool.kind pattern (canonical v10)
# ============================================================================

class ToolSpec(BaseModel):
    """
    Tool configuration with tool.kind pattern (canonical v10).

    The `eval` field is REJECTED in v10. Use `spec.policy.rules` instead.
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
        "noop",           # No-operation tool for routing/initialization
        "task_sequence",  # Task sequence execution
        "rhai",           # Rhai scripting engine
    ] = Field(
        ..., description="Tool type"
    )
    # Task-level spec with policy (canonical v10)
    spec: Optional[TaskSpec] = Field(
        default=None,
        description="Task spec with policy.rules for outcome handling"
    )
    # Output configuration at tool level
    output: Optional[ToolOutput] = Field(
        default=None,
        description="Result storage and accumulation configuration"
    )

    class Config:
        extra = "allow"  # Allow additional fields for tool-specific config


# ============================================================================
# Tool Outcome - Structured execution result (canonical v10)
# ============================================================================

class ToolOutcome(BaseModel):
    """
    Structured result of tool execution (canonical v10).

    Available in policy rule expressions as 'outcome'.

    IMPORTANT: status is "ok" or "error" (not "success").

    Example outcome:
        outcome = {
            "status": "error",
            "error": {
                "kind": "rate_limit",
                "retryable": True,
                "code": "HTTP_429",
                "message": "Rate limit exceeded"
            },
            "meta": {"attempt": 1, "duration_ms": 150, "ts": "..."},
            "http": {"status": 429, "headers": {...}}
        }
    """
    status: Literal["ok", "error"] = Field(..., description="Execution status: ok or error")
    result: Any = Field(None, description="Tool output (if ok)")
    error: Optional[dict[str, Any]] = Field(
        None, description="Structured error {kind, retryable, code, message, details}"
    )
    meta: Optional[dict[str, Any]] = Field(
        None, description="Execution metadata {attempt, duration_ms, ts}"
    )
    # Tool-specific helpers
    http: Optional[dict[str, Any]] = Field(
        None, description="HTTP-specific info {status, headers, request_id}"
    )
    pg: Optional[dict[str, Any]] = Field(
        None, description="PostgreSQL-specific info {code, sqlstate}"
    )
    py: Optional[dict[str, Any]] = Field(
        None, description="Python-specific info {exception_type, traceback}"
    )

    class Config:
        extra = "allow"


# ============================================================================
# Loop Models - Step-level looping (canonical v10)
# ============================================================================

class LoopPolicy(BaseModel):
    """
    Loop scheduling policy (server-side, canonical v10).

    Controls how iterations are scheduled/distributed.
    """
    exec: Literal["distributed", "local"] = Field(
        default="local",
        description="Execution intent: distributed (across workers) or local"
    )


class LoopSpec(BaseModel):
    """
    Loop runtime specification (canonical v10).

    Controls loop execution behavior.
    """
    mode: Literal["sequential", "parallel"] = Field(
        default="sequential",
        description="Execution mode: sequential or parallel"
    )
    max_in_flight: Optional[int] = Field(
        None,
        description="Maximum concurrent iterations in parallel mode"
    )
    policy: Optional[LoopPolicy] = Field(
        None,
        description="Loop scheduling policy"
    )


class Loop(BaseModel):
    """
    Step-level loop configuration (canonical v10).

    Loop is a step MODIFIER, not a tool kind.

    Canonical format:
        loop:
          in: "{{ workload.items }}"
          iterator: item
          spec:
            mode: parallel
            max_in_flight: 10
            policy:
              exec: distributed
    """
    in_: str = Field(..., alias="in", description="Jinja expression for collection to iterate")
    iterator: str = Field(..., description="Variable name for each item (binds iter.<iterator>)")
    spec: Optional[LoopSpec] = Field(None, description="Loop runtime specification")

    class Config:
        populate_by_name = True

    @property
    def mode(self) -> str:
        """Get loop mode from spec."""
        return self.spec.mode if self.spec else "sequential"


# ============================================================================
# Next Router Models - Petri-net arc routing (canonical v10)
# ============================================================================

class NextSpec(BaseModel):
    """
    Next router specification (canonical v10).

    Controls how arcs are evaluated.
    """
    mode: Literal["exclusive", "inclusive"] = Field(
        default="exclusive",
        description="Arc evaluation mode: exclusive (first match) or inclusive (all matches)"
    )
    policy: Optional[dict[str, Any]] = Field(
        None,
        description="Router policy (placeholder for priority/dedupe/partitioning)"
    )


class Arc(BaseModel):
    """
    Routing arc (Petri-net transition, canonical v10).

    Evaluated by server on terminal boundary events.

    Example:
        arcs:
          - step: success_handler
            when: "{{ event.name == 'step.done' }}"
            args: { data: "{{ ctx.result }}" }
          - step: error_handler
            when: "{{ event.name == 'step.failed' }}"
    """
    step: str = Field(..., description="Target step name")
    when: Optional[str] = Field(
        None, description="Arc guard expression (Jinja2). Default true if omitted."
    )
    args: Optional[dict[str, Any]] = Field(
        None, description="Token payload to pass to target step (arc inscription)"
    )
    spec: Optional[dict[str, Any]] = Field(
        None, description="Arc-level spec (placeholder for future)"
    )


class NextRouter(BaseModel):
    """
    Step next router (canonical v10).

    Replaces simple next[] list with structured router object.

    Canonical format:
        next:
          spec:
            mode: exclusive
          arcs:
            - step: validate_results
              when: "{{ event.name == 'loop.done' }}"
            - step: cleanup
              when: "{{ event.name == 'step.failed' }}"
    """
    spec: Optional[NextSpec] = Field(
        default_factory=lambda: NextSpec(),
        description="Router specification"
    )
    arcs: list[Arc] = Field(
        default_factory=list,
        description="Routing arcs"
    )


# ============================================================================
# Step Spec and Policy Models (canonical v10)
# ============================================================================

class StepPolicy(BaseModel):
    """
    Step-level policy (canonical v10).

    Contains admission policy and lifecycle hints.
    MUST NOT include task control actions (those are task-level only).
    """
    admit: Optional[AdmitPolicy] = Field(
        None, description="Step admission policy (server-side)"
    )
    lifecycle: Optional[dict[str, Any]] = Field(
        None, description="Lifecycle hints: timeout_s, deadline_s"
    )
    failure: Optional[dict[str, Any]] = Field(
        None, description="Failure mode: fail_fast | best_effort"
    )
    emit: Optional[dict[str, Any]] = Field(
        None, description="Event emission config"
    )


class StepSpec(BaseModel):
    """
    Step-level behavior configuration (canonical v10).

    All knobs live under spec. Policy for admission is under spec.policy.
    NOTE: next_mode is REMOVED - routing mode belongs to next.spec.mode.
    """
    policy: Optional[StepPolicy] = Field(
        None, description="Step policy (admission, lifecycle, failure)"
    )
    timeout: Optional[str] = Field(None, description="Step timeout (e.g., '30s', '5m')")

    class Config:
        extra = "allow"


# ============================================================================
# Step Model - Workflow node (canonical v10)
# ============================================================================

class Step(BaseModel):
    """
    Workflow step in canonical v10 format.

    Key changes from previous versions:
    - NO `step.when` field - use `step.spec.policy.admit.rules` for admission
    - NO `tool.eval` - use `task.spec.policy.rules` for outcome handling
    - `next` is a router object with `spec` + `arcs[]`

    Canonical step structure:
        - step: name
          desc: description
          spec:
            policy:
              admit:
                rules:
                  - when: "{{ ctx.enabled }}"
                    then: { allow: true }
          loop:
            in: "{{ workload.items }}"
            iterator: item
            spec:
              mode: parallel
          tool:
            - task_label:
                kind: http
                url: "..."
                spec:
                  policy:
                    rules:
                      - when: "{{ outcome.status == 'error' }}"
                        then: { do: retry, attempts: 3 }
                      - else:
                          then: { do: continue }
          next:
            spec:
              mode: exclusive
            arcs:
              - step: success
                when: "{{ event.name == 'step.done' }}"
    """
    step: str = Field(..., description="Step name (unique identifier)")
    desc: Optional[str] = Field(None, description="Step description")
    spec: Optional[StepSpec] = Field(None, description="Step spec with policy")

    # NOTE: step.when is REMOVED in v10 - use step.spec.policy.admit.rules
    # when: REMOVED

    args: Optional[dict[str, Any]] = Field(None, description="Input arguments for this step")
    loop: Optional[Loop] = Field(None, description="Loop configuration")

    # Tool: single ToolSpec (shorthand) or list of labeled tasks (pipeline)
    tool: Optional[Union[ToolSpec, list[dict[str, Any]]]] = Field(
        None,
        description="Tool pipeline (list of labeled tasks) or single tool shorthand"
    )

    # Next: router object with spec + arcs (canonical v10)
    next: Optional[Union[str, list[str], dict[str, Any], NextRouter]] = Field(
        None,
        description="Next router with spec and arcs"
    )

    # NOTE: Legacy fields (output, result, vars) removed in v10
    # Use tool.output for output config, ctx/iter via policy for variables

    @field_validator("tool", mode="before")
    @classmethod
    def normalize_tool(cls, v):
        """Normalize tool field - accept both single and list formats."""
        if v is None:
            return None

        # Single tool shorthand: tool: {kind: http, ...}
        if isinstance(v, dict) and "kind" in v:
            return v

        # Pipeline format: tool: [- label: {kind: ...}]
        if isinstance(v, list):
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

    @field_validator("next", mode="before")
    @classmethod
    def normalize_next(cls, v):
        """Normalize next field to canonical router format."""
        if v is None:
            return None

        # Already a NextRouter object
        if isinstance(v, NextRouter):
            return v

        # Canonical router format: {spec: {...}, arcs: [...]}
        if isinstance(v, dict):
            if "arcs" in v:
                return v  # Already canonical format
            if "spec" in v and "arcs" not in v:
                raise ValueError("next router must have 'arcs' field")
            # Legacy: {step: name, when: "..."} - convert to arc
            if "step" in v:
                return {"spec": {"mode": "exclusive"}, "arcs": [v]}

        # String shorthand: next: "step_name"
        if isinstance(v, str):
            return {"spec": {"mode": "exclusive"}, "arcs": [{"step": v}]}

        # List format (legacy) - convert to arcs
        if isinstance(v, list):
            arcs = []
            for item in v:
                if isinstance(item, str):
                    arcs.append({"step": item})
                elif isinstance(item, dict):
                    if "step" not in item:
                        raise ValueError(f"Invalid next entry: {item}. Must have 'step' field")
                    arcs.append(item)
                else:
                    raise ValueError(f"Invalid next entry: {item}")
            return {"spec": {"mode": "exclusive"}, "arcs": arcs}

        return v


# ============================================================================
# Workbook Models
# ============================================================================

class WorkbookTask(BaseModel):
    """Reusable task definition."""
    name: str = Field(..., description="Task name")
    tool: ToolSpec = Field(..., description="Tool configuration")


# ============================================================================
# Executor Models - Runtime requirements and workflow control
# ============================================================================

class ExecutorSpec(BaseModel):
    """
    Executor specification for workflow entry and termination control.
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
        description="Treat 'no matching next arc' as error (default: false)"
    )


class ExecutorPolicy(BaseModel):
    """
    Executor-level policy (global defaults, canonical v10).

    Placeholders for global settings.
    """
    defaults: Optional[dict[str, Any]] = Field(None, description="Default timeouts, resources")
    results: Optional[dict[str, Any]] = Field(None, description="Result handling: reference_first")
    limits: Optional[dict[str, Any]] = Field(None, description="Limits: max_payload_bytes")


class ExecutorSpecFull(BaseModel):
    """
    Full executor spec with policy (canonical v10).
    """
    entry_step: Optional[str] = Field(None, description="Override entry step")
    final_step: Optional[str] = Field(None, description="Finalization step")
    no_next_is_error: Optional[bool] = Field(None, description="No-match is error")
    policy: Optional[ExecutorPolicy] = Field(None, description="Global policy defaults")


class ExecutorRequires(BaseModel):
    """Executor capability requirements."""
    tools: Optional[list[str]] = Field(None, description="Required tool kinds")
    features: Optional[list[str]] = Field(None, description="Required runtime features")


class Executor(BaseModel):
    """
    Executor configuration (canonical v10).
    """
    profile: Literal["local", "distributed", "auto"] = Field(
        default="auto",
        description="Runtime profile"
    )
    version: str = Field(
        default="noetl-runtime/1",
        description="Semantic contract version"
    )
    requires: Optional[ExecutorRequires] = Field(None, description="Required capabilities")
    spec: Optional[ExecutorSpecFull] = Field(None, description="Executor spec with policy")


# ============================================================================
# Playbook Model - Complete workflow definition (canonical v10)
# ============================================================================

class Playbook(BaseModel):
    """
    Complete workflow definition (canonical v10).

    Root sections:
    - metadata
    - executor (optional)
    - workload (immutable inputs)
    - workflow (array of steps)
    - workbook (optional reusable blocks)
    - keychain (optional credential definitions)

    NOTE: Root `vars` is REJECTED in v10. Use ctx/iter via policy mutations.
    """
    apiVersion: Literal["noetl.io/v2", "noetl.io/v10"] = Field(..., description="API version")
    kind: Literal["Playbook"] = Field(..., description="Resource kind")
    metadata: dict[str, Any] = Field(..., description="Metadata (name, path, labels)")
    executor: Optional[Executor] = Field(None, description="Executor configuration")
    workload: Optional[dict[str, Any]] = Field(None, description="Immutable workflow inputs")
    keychain: Optional[list[dict[str, Any]]] = Field(None, description="Keychain definitions")
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
        """Get the entry step name using canonical rules."""
        if self.executor and self.executor.spec and self.executor.spec.entry_step:
            return self.executor.spec.entry_step
        return self.workflow[0].step if self.workflow else "start"

    def get_final_step(self) -> Optional[str]:
        """Get the optional final step name."""
        if self.executor and self.executor.spec:
            return self.executor.spec.final_step
        return None


# ============================================================================
# Command Model - Queue table entry
# ============================================================================

class ToolCall(BaseModel):
    """Tool invocation details."""
    kind: str = Field(..., description="Tool kind")
    config: dict[str, Any] = Field(default_factory=dict, description="Tool-specific configuration")


class CommandSpec(BaseModel):
    """
    Command-level behavior configuration.
    """
    next_mode: Literal["exclusive", "inclusive"] = Field(
        default="exclusive",
        description="Next evaluation mode (legacy, use next.spec.mode)"
    )


class Command(BaseModel):
    """
    Command to be executed by worker (canonical v10).
    """
    execution_id: str = Field(..., description="Execution identifier")
    step: str = Field(..., description="Step name")
    tool: ToolCall = Field(..., description="Tool invocation details")
    args: Optional[dict[str, Any]] = Field(None, description="Step input arguments")
    render_context: dict[str, Any] = Field(default_factory=dict, description="Full render context")

    # Pipeline: list of labeled tasks
    pipeline: Optional[list[dict[str, Any]]] = Field(
        None, description="Pipeline tasks for task_sequence execution"
    )

    # Next router (canonical v10)
    next_router: Optional[dict[str, Any]] = Field(
        None, description="Next router with spec and arcs"
    )

    # Legacy compatibility
    next_targets: Optional[list[dict[str, Any]]] = Field(
        None, description="[LEGACY] Use next_router"
    )

    spec: Optional[CommandSpec] = Field(None, description="Command spec")
    attempt: int = Field(default=1, description="Attempt number")
    priority: int = Field(default=0, description="Command priority")
    backoff: Optional[float] = Field(None, description="Retry backoff delay")
    max_attempts: Optional[int] = Field(None, description="Maximum retry attempts")
    retry_delay: Optional[float] = Field(None, description="Initial retry delay")
    retry_backoff: Optional[str] = Field(None, description="Retry backoff strategy")
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
            "next_router": self.next_router,
            "next_targets": self.next_targets,
            "spec": self.spec.model_dump() if self.spec else None,
            "attempt": self.attempt,
            "priority": self.priority,
            "backoff": self.backoff,
            "max_attempts": self.max_attempts,
            "metadata": self.metadata,
            "status": "pending",
        }


# NOTE: All legacy aliases and deprecated models have been removed in v10.
# Use canonical v10 patterns only:
# - task.spec.policy.rules (not eval)
# - when (not expr)
# - set_ctx (not set_vars)
# - next.arcs[] (not next[])
# - outcome.status: "ok" | "error" (not "success")
