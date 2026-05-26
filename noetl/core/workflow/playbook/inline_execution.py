"""Round A inline-child eligibility detector.

This module is intentionally pure: no database reads, no HTTP calls, and no
dispatch decisions. Round A only explains whether a child playbook would be a
safe candidate for a later inline runner.
"""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
from typing import Any, Iterable, Mapping, Optional


DEFAULT_MAX_STEPS = 3
DEFAULT_MAX_DEPTH = 3
DEFAULT_ALLOWED_TOOL_KINDS = frozenset({"python", "mcp", "noop"})
DEFAULT_ALLOW_LIST = ("automation/agents/mcp/*",)
ALLOW_LIST_ENV = "NOETL_INLINE_TRIVIAL_CHILDREN_ALLOW_LIST"


@dataclass(frozen=True)
class InlineDecision:
    inline: bool
    reasons: list[str]
    depth: int
    mode: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "inline": self.inline,
            "reasons": list(self.reasons),
            "depth": self.depth,
            "mode": self.mode,
        }


def detect_inline_child(
    child_playbook: Any,
    parent_context: Optional[Mapping[str, Any]] = None,
    *,
    child_path: Optional[str] = None,
    framework: str = "noetl",
    depth: Optional[int] = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_depth: int = DEFAULT_MAX_DEPTH,
    allowed_tool_kinds: Iterable[str] = DEFAULT_ALLOWED_TOOL_KINDS,
    allow_list: Optional[Iterable[str]] = None,
) -> InlineDecision:
    """Return the Round A inline eligibility decision for a child playbook."""

    playbook = _as_mapping(child_playbook)
    parent_context = parent_context or {}
    current_depth = _resolve_depth(parent_context, depth)
    allowed_kinds = {str(kind).strip().lower() for kind in allowed_tool_kinds}
    patterns = tuple(allow_list) if allow_list is not None else load_allow_list_from_env()
    reasons: list[str] = []
    blocked = False

    if str(framework or "").strip().lower() == "noetl":
        reasons.append("framework:ok:noetl")
    else:
        reasons.append(f"framework:block:{framework}")
        blocked = True

    if current_depth <= max_depth:
        reasons.append(f"depth:ok:{current_depth}<={max_depth}")
    else:
        reasons.append(f"depth:block:{current_depth}>{max_depth}")
        blocked = True

    metadata = _as_mapping(playbook.get("metadata"))
    metadata_flag = metadata.get("inline_when_safe")
    metadata_mode = False
    metadata_invalid = False
    if metadata_flag is True:
        metadata_mode = True
        reasons.append("metadata:ok:inline_when_safe=true")
    elif metadata_flag is None or metadata_flag is False:
        reasons.append("metadata:skip:inline_when_safe_not_true")
    else:
        metadata_invalid = True
        reasons.append("metadata:block:inline_when_safe_must_be_boolean_true")
        blocked = True

    allow_mode = _path_matches_allow_list(child_path, patterns)
    if allow_mode:
        reasons.append("allow_list:ok:path_matched")
    else:
        reasons.append("allow_list:skip:path_not_matched")

    mode: Optional[str]
    if metadata_mode:
        mode = "metadata_opt_in"
    elif allow_mode:
        mode = "allow_list"
    else:
        mode = None
        if not metadata_invalid:
            reasons.append("mode:block:not_opted_in_or_allow_listed")
            blocked = True

    workflow = _as_list(playbook.get("workflow"))
    step_count = len(workflow)
    if 0 < step_count <= max_steps:
        reasons.append(f"steps:ok:{step_count}<={max_steps}")
    else:
        reasons.append(f"steps:block:{step_count}>{max_steps}" if step_count else "steps:block:missing_workflow")
        blocked = True

    executor = _as_mapping(playbook.get("executor"))
    executor_spec = _as_mapping(executor.get("spec"))
    if executor_spec.get("final_step"):
        reasons.append("finalizer:block:executor_spec_final_step")
        blocked = True
    else:
        reasons.append("finalizer:ok:none")

    if _contains_key_with_truthy_value(playbook, "callback_subject"):
        reasons.append("callback:block:callback_subject_present")
        blocked = True
    else:
        reasons.append("callback:ok:none")

    if _contains_async_true(playbook):
        reasons.append("async:block:spec_async_true")
        blocked = True
    else:
        reasons.append("async:ok:none")

    if _contains_output_ref(playbook):
        reasons.append("output_ref:block:present")
        blocked = True
    else:
        reasons.append("output_ref:ok:none")

    loop_blocked = _append_loop_reasons(workflow, reasons)
    blocked = blocked or loop_blocked

    tool_blocked = _append_tool_reasons(workflow, reasons, allowed_kinds)
    blocked = blocked or tool_blocked

    tenant_blocked = _append_tenant_reasons(metadata, parent_context, reasons)
    blocked = blocked or tenant_blocked

    return InlineDecision(
        inline=not blocked,
        reasons=reasons,
        depth=current_depth,
        mode=mode,
    )


def load_allow_list_from_env(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    env = env if env is not None else os.environ
    raw = str(env.get(ALLOW_LIST_ENV, "") or "").strip()
    if not raw:
        return DEFAULT_ALLOW_LIST
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _resolve_depth(parent_context: Mapping[str, Any], explicit_depth: Optional[int]) -> int:
    if explicit_depth is not None:
        return max(0, int(explicit_depth))
    for key in ("inline_depth", "_inline_depth"):
        if key in parent_context:
            try:
                return max(0, int(parent_context[key]))
            except (TypeError, ValueError):
                return 0
    meta = _as_mapping(parent_context.get("meta"))
    if "inline_depth" in meta:
        try:
            return max(0, int(meta["inline_depth"]))
        except (TypeError, ValueError):
            return 0
    return 0


def _path_matches_allow_list(path: Optional[str], patterns: Iterable[str]) -> bool:
    if not path:
        return False
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _append_loop_reasons(workflow: list[Any], reasons: list[str]) -> bool:
    blocked = False
    loop_seen = False
    for idx, raw_step in enumerate(workflow):
        step = _as_mapping(raw_step)
        loop = _as_mapping(step.get("loop"))
        if not loop:
            continue
        loop_seen = True
        loop_spec = _as_mapping(loop.get("spec"))
        loop_policy = _as_mapping(loop_spec.get("policy"))
        mode = str(loop_spec.get("mode") or loop.get("mode") or "sequential").lower()
        if mode in {"parallel", "cursor"}:
            reasons.append(f"loop:block:step[{idx}].mode={mode}")
            blocked = True
        elif loop.get("cursor") is not None:
            reasons.append(f"loop:block:step[{idx}].cursor_present")
            blocked = True
        elif str(loop_policy.get("exec") or "").lower() == "distributed":
            reasons.append(f"loop:block:step[{idx}].policy_exec=distributed")
            blocked = True
        else:
            reasons.append(f"loop:ok:step[{idx}].mode={mode or 'sequential'}")
    if not loop_seen:
        reasons.append("loop:ok:none")
    return blocked


def _append_tool_reasons(
    workflow: list[Any],
    reasons: list[str],
    allowed_kinds: set[str],
) -> bool:
    blocked = False
    for idx, raw_step in enumerate(workflow):
        kinds = _tool_kinds(_as_mapping(raw_step).get("tool"))
        if not kinds:
            reasons.append(f"tool:block:step[{idx}].missing_tool_kind")
            blocked = True
            continue
        for kind in kinds:
            if kind == "agent":
                reasons.append(f"tool:block:step[{idx}].kind=agent")
                blocked = True
            elif kind in {"playbook", "playbooks"}:
                reasons.append(f"tool:block:step[{idx}].kind={kind}")
                blocked = True
            elif kind not in allowed_kinds:
                reasons.append(f"tool:block:step[{idx}].kind={kind}")
                blocked = True
            else:
                reasons.append(f"tool:ok:step[{idx}].kind={kind}")
    return blocked


def _append_tenant_reasons(
    metadata: Mapping[str, Any],
    parent_context: Mapping[str, Any],
    reasons: list[str],
) -> bool:
    blocked = False
    for key in ("tenant_id", "organization_id"):
        child_value = metadata.get(key)
        parent_value = _context_value(parent_context, key)
        if child_value is None:
            reasons.append(f"{key}:ok:no_child_constraint")
            continue
        if parent_value is None:
            reasons.append(f"{key}:block:parent_missing")
            blocked = True
            continue
        if str(child_value) == str(parent_value):
            reasons.append(f"{key}:ok:match")
        else:
            reasons.append(f"{key}:block:mismatch")
            blocked = True
    return blocked


def _context_value(context: Mapping[str, Any], key: str) -> Any:
    if key in context:
        return context.get(key)
    for container_key in ("workload", "ctx", "meta"):
        container = _as_mapping(context.get(container_key))
        if key in container:
            return container.get(key)
    return None


def _tool_kinds(tool: Any) -> list[str]:
    if tool is None:
        return []
    if isinstance(tool, list):
        kinds: list[str] = []
        for item in tool:
            item_map = _as_mapping(item)
            kind = item_map.get("kind")
            if kind is not None:
                kinds.append(str(kind).strip().lower())
        return kinds
    tool_map = _as_mapping(tool)
    kind = tool_map.get("kind")
    return [str(kind).strip().lower()] if kind is not None else []


def _contains_async_true(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) == "async" and bool(item):
                return True
            if _contains_async_true(item):
                return True
    elif isinstance(value, list):
        return any(_contains_async_true(item) for item in value)
    return False


def _contains_output_ref(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) == "output_ref" and item not in (None, "", {}):
                return True
            if _contains_output_ref(item):
                return True
    elif isinstance(value, list):
        return any(_contains_output_ref(item) for item in value)
    return False


def _contains_key_with_truthy_value(value: Any, needle: str) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) == needle and bool(item):
                return True
            if _contains_key_with_truthy_value(item, needle):
                return True
    elif isinstance(value, list):
        return any(_contains_key_with_truthy_value(item, needle) for item in value)
    return False


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, Mapping) else {}
    if hasattr(value, "dict"):
        dumped = value.dict()
        return dumped if isinstance(dumped, Mapping) else {}
    return {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
