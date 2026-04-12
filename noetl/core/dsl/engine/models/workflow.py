from __future__ import annotations

from .common import *
from .policy import AdmitPolicy
from .tools import ToolSpec

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
            set:
              ctx.result_ref: "{{ output.ref }}"
          - step: error_handler
            when: "{{ event.name == 'step.failed' }}"
    """
    step: str = Field(..., description="Target step name")
    when: Optional[str] = Field(
        None, description="Arc guard expression (Jinja2). Default true if omitted."
    )
    set: Optional[dict[str, Any]] = Field(
        None, description="Transition-scoped variable mutations (ctx.*, step.*, iter.*)"
    )
    spec: Optional[dict[str, Any]] = Field(
        None, description="Arc-level spec (placeholder for future)"
    )

    @model_validator(mode='before')
    @classmethod
    def _reject_legacy_fields(cls, obj):
        """Reject legacy arc aliases; use canonical `set` only."""
        if isinstance(obj, dict) and "args" in obj:
            raise ValueError("next.arcs[] must use 'set' (legacy 'args' is not allowed)")
        return obj


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
    - NO `tool.eval` - use `task.spec.policy.rules` for output-status handling
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
                      - when: "{{ output.status == 'error' }}"
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

    input: Optional[dict[str, Any]] = Field(None, description="Input bindings for this step")
    loop: Optional[Loop] = Field(None, description="Loop configuration")

    # Tool: single ToolSpec (shorthand) or list of labeled tasks (pipeline)
    tool: Optional[Union[ToolSpec, list[dict[str, Any]]]] = Field(
        None,
        description="Tool pipeline (list of labeled tasks) or single tool shorthand"
    )

    # Next: router object with spec + arcs (canonical v10)
    next: Optional[NextRouter] = Field(
        None,
        description="Next router with spec and arcs"
    )

    # Step-level scoped mutation (processed after tool completes)
    set: Optional[dict[str, Any]] = Field(
        None,
        description="Scoped variable mutations after step completes (ctx.*, step.*, iter.*)"
    )

    # NOTE: Legacy fields (output, result, vars) removed in v10
    # Use tool.output for output config, ctx/iter via policy for variables

    @field_validator("tool", mode="before")
    @classmethod
    def normalize_tool(cls, v):
        """
        Normalize tool field - accept both single and list formats.

        Supported formats:
        1. Single tool: { kind: "http", ... }
        2. Canonical pipeline (named): [{ name: "task_name", kind: "http", ... }, ...]
        3. Unnamed pipeline: [{ kind: "http", ... }, ...] - synthetic names generated

        NOT supported (removed):
        - Syntactic sugar: { task_label: { kind: ... } }
        """
        if v is None:
            return None

        # Single tool shorthand: tool: {kind: http, ...}
        if isinstance(v, dict) and "kind" in v:
            return v

        # Pipeline format
        if isinstance(v, list):
            for i, task in enumerate(v):
                if not isinstance(task, dict):
                    raise ValueError(f"tool[{i}] must be an object")

                # Canonical format: { name: "...", kind: "...", ... }
                if "name" in task and "kind" in task:
                    continue  # Valid canonical format

                # Unnamed task format: { kind: "...", ... } (no name field)
                if "kind" in task and "name" not in task:
                    continue  # Valid unnamed format

                # Invalid format - syntactic sugar is no longer supported
                raise ValueError(
                    f"tool[{i}] must be either:\n"
                    f"  1. Canonical: {{ name: 'task_name', kind: 'http', ... }}\n"
                    f"  2. Unnamed: {{ kind: 'http', ... }}\n"
                    f"Got: {list(task.keys())}"
                )
            return v

        raise ValueError("tool must be an object with 'kind' or a list of tasks")

    @field_validator("next", mode="before")
    @classmethod
    def normalize_next(cls, v):
        """Normalize next field to canonical router format."""
        if v is None:
            return None

        if isinstance(v, NextRouter):
            return v

        if isinstance(v, dict):
            if "arcs" in v:
                return v
            if "spec" in v and "arcs" not in v:
                raise ValueError("next router must have 'arcs' field")
            raise ValueError("next must use canonical router format with 'arcs'")

        return v

    @model_validator(mode='before')
    @classmethod
    def _reject_legacy_fields(cls, obj):
        """Reject legacy step-level aliases; canonical fields are input/output/set only."""
        if isinstance(obj, dict) and (
            "args" in obj
            or "set_ctx" in obj
            or "set_iter" in obj
            or "result" in obj
            or "outcome" in obj
        ):
            raise ValueError(
                "step must use canonical fields only (legacy args/set_ctx/set_iter/result/outcome are not allowed; use input/set and tool.output)"
            )
        return obj


# ============================================================================
# Workbook Models
# ============================================================================
