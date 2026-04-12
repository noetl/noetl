from __future__ import annotations

from .common import *

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
    # Unified scoped mutation (replaces set_ctx / set_iter)
    set: Optional[dict[str, Any]] = Field(
        None, description="Scoped variable mutations: ctx.*, iter.*, step.*"
    )

    class Config:
        extra = "allow"

    @model_validator(mode='before')
    @classmethod
    def _reject_legacy_fields(cls, obj):
        """Reject legacy assignment aliases; use canonical `set` only."""
        if isinstance(obj, dict) and ("set_ctx" in obj or "set_iter" in obj):
            raise ValueError("policy.then must use 'set' (legacy set_ctx/set_iter are not allowed)")
        return obj


class PolicyRule(BaseModel):
    """
    Single policy rule (canonical v10).

    Uses `when` as the ONLY conditional keyword.
    First matching rule wins (or else clause if no when).

    Example:
        - when: "{{ output.status == 'error' and output.error.retryable }}"
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
    Task output-status policy (worker-side, canonical v10).

    MUST be an object with required `rules:` list.
    This is the ONLY place where control actions (retry/jump/break/fail/continue) are allowed.

    Example:
        spec:
          policy:
            rules:
              - when: "{{ output.status == 'error' and output.http.status in [429,500,502,503] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 1.0 }
              - when: "{{ output.status == 'error' }}"
                then: { do: fail }
              - else:
                  then:
                    do: continue
                    set:
                      iter.has_more: "{{ output.data.paging.hasMore }}"
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

