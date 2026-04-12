from __future__ import annotations

from .common import *
from .policy import TaskPolicy

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

    Contains task policy for output-status handling.
    Policy is the ONLY place where control actions are allowed.
    """
    timeout: Optional[dict[str, Any]] = Field(
        None, description="Timeout config { connect: 5, read: 15 }"
    )
    policy: Optional[TaskPolicy] = Field(
        None, description="Task output-status policy with rules"
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
        "agent",
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
        description="Task spec with policy.rules for output-status handling"
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

    Available in policy rule expressions as 'output'.

    IMPORTANT: status is "ok" or "error" (not "success").

    Example output:
        output = {
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
    data: Any = Field(None, description="Tool output payload (if ok)")
    ref: Optional[dict[str, Any]] = Field(None, description="Reference to externalized payload")
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

