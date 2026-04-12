from __future__ import annotations

from .common import *
from .tools import ToolSpec
from .workflow import Step

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
    workload: Optional[dict[str, Any]] = Field(None, description="Default variables (becomes ctx at runtime)")
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
        return self.workflow[0].step

    def get_final_step(self) -> Optional[str]:
        """Get the optional final step name."""
        if self.executor and self.executor.spec:
            return self.executor.spec.final_step
        return None


# ============================================================================
# Command Model - Queue table entry
# ============================================================================
