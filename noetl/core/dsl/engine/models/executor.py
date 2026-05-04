from __future__ import annotations

from .common import *
from .tools import ToolSpec
from .workflow import Step

class WorkbookTask(BaseModel):
    """Reusable task definition."""
    name: str = Field(..., description="Task name")
    tool: ToolSpec = Field(..., description="Tool configuration")


# ============================================================================
# Playbook Metadata - typed view over the metadata dict
# ============================================================================


class PlaybookMetadata(BaseModel):
    """Typed view over the ``metadata`` dict on a Playbook / Agent.

    The on-disk schema keeps ``metadata`` as a free-form dict (so authors
    can attach arbitrary keys without churning the Pydantic model on
    every new use case), but a handful of well-known fields drive
    server / GUI behaviour and need shape validation:

    - ``name`` — human-readable resource title; required for every
      catalog entry.
    - ``path`` — canonical catalog path; runtime falls back on this
      via ``playbook.metadata.get("path", ...)``.
    - ``description`` — markdown-rendered description shown in the
      GUI; surfaces as the MCP tool's ``description`` field.
    - ``tags`` — list of strings; used by catalog filtering.
    - ``exposed_in_ui`` — bool; opt-in flag for surfacing the
      resource's workload form in the GUI's run dialog.
    - ``exposes_as_mcp`` — bool; opt-out (when false) flag that the
      playbook-as-MCP-server endpoint reads to decide whether to
      advertise the playbook over the MCP wire. Absent / true means
      "expose"; explicit false means "do not expose".
    - ``agent`` — bool; legacy flag distinguishing agent-style
      playbooks from regular ones.
    - ``capabilities`` — list of strings used by the agent
      catalogue's filter endpoints.

    Unknown keys pass through unchanged thanks to ``extra=allow`` —
    the model only constrains shapes for fields it knows. Use this
    class when you need typed access (e.g. ``meta.exposes_as_mcp``),
    and keep using the dict directly when you need the full set of
    keys.
    """

    name: str = Field(..., description="Human-readable resource title")
    path: Optional[str] = Field(None, description="Canonical catalog path")
    description: Optional[str] = Field(None, description="Markdown description")
    tags: Optional[list[str]] = Field(None, description="Catalog filter tags")
    exposed_in_ui: Optional[bool] = Field(
        None,
        description="Opt-in: render workload form in GUI run dialog",
    )
    exposes_as_mcp: Optional[bool] = Field(
        None,
        description=(
            "Opt-out flag (when explicitly false) for the "
            "playbook-as-MCP-server endpoint. Absent / true means the "
            "playbook is exposed as an MCP tool; false hides it."
        ),
    )
    agent: Optional[bool] = Field(None, description="Legacy agent flag")
    capabilities: Optional[list[str]] = Field(
        None, description="Agent capabilities for filtering"
    )

    model_config = {"extra": "allow"}

    @field_validator("tags", "capabilities", mode="before")
    @classmethod
    def _coerce_str_list(cls, v: Any) -> Any:
        # Accept None, a list of strings, or a single string (split once).
        # The string-singleton case shows up in copy-paste YAML where an
        # author wrote ``tags: foo`` instead of ``tags: [foo]`` — accept
        # it rather than rejecting registration over a trivial mistake.
        if v is None:
            return v
        if isinstance(v, str):
            return [v]
        if not isinstance(v, list):
            raise ValueError("must be a list of strings (or a single string)")
        return v


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
        """Validate metadata against the typed PlaybookMetadata view.

        The on-disk shape stays as a free-form dict so existing call
        sites that do ``playbook.metadata.get("path", ...)`` keep
        working unchanged. We round-trip through ``PlaybookMetadata``
        purely to enforce typed validation on the well-known fields
        (``exposes_as_mcp`` / ``exposed_in_ui`` must be bool when
        present, ``tags`` / ``capabilities`` must be lists of strings,
        ``name`` is required). Unknown keys pass through because the
        sub-model uses ``extra=allow``. ``ValueError`` from Pydantic
        propagates as a 422 at the catalog-register endpoint.
        """
        if not isinstance(v, dict):
            raise ValueError("metadata must be a mapping/dict")
        # Validate (raises pydantic.ValidationError on bad shapes); we
        # discard the parsed model and return the original dict so
        # downstream code that expects ``metadata.get(...)`` keeps
        # working without a type-shift refactor.
        PlaybookMetadata.model_validate(v)
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
