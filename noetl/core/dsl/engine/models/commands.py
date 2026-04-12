from __future__ import annotations

from .common import *

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
    input: Optional[dict[str, Any]] = Field(None, description="Step input bindings")
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

    @model_validator(mode='before')
    @classmethod
    def _reject_legacy_fields(cls, obj):
        """Reject legacy command aliases; canonical commands carry `input`."""
        if isinstance(obj, dict) and "args" in obj:
            raise ValueError("command must use 'input' (legacy 'args' is not allowed)")
        return obj

    def to_queue_record(self) -> dict[str, Any]:
        """Convert to queue table record format."""
        return {
            "execution_id": self.execution_id,
            "step": self.step,
            "tool_kind": self.tool.kind,
            "tool_config": self.tool.config,
            "input": self.input or {},
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


# NOTE: Canonical-only parsing:
# - Reject legacy aliases such as args/set_ctx/set_iter/outcome/result on author-facing DSL models.
# Canonical v10 patterns:
# - step.input / arc.set / output.data / output.ref
# - set: { ctx.*, iter.*, step.* }
# - when (not expr)
# - next.arcs[] (not next[])
# - output.status: "ok" | "error"
