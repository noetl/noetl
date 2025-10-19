"""
Normalization helpers for NoETL DSL steps.

Responsibilities:
- Normalize legacy aliases (with/params) to canonical args
- Convert legacy loop: {in, iterator} into type: iterator + args/element
- Validate that 'data' is not used on step definitions (reserved for results)

DSL Design:
- args: inputs TO a step (parameters passed to the action)
- data: outputs FROM a step (results, only in context/results, never in step def)
- input: edge payload passed via next[].input (merged into target step's args)
- with: legacy alias for args (normalized to args)

Notes:
- Do not touch nested save.data or iterator.task.data blocks
- Perform minimal, predictable mutations on a shallow copy of input
"""

from __future__ import annotations

from typing import Any, Dict


def normalize_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a step dict in-place and return it.

    - Merge legacy aliases (with/params) into args, with explicit args winning on key conflicts
    - Convert legacy loop syntax to iterator shape
    - Validate no misuse of 'data' field (reserved for results)
    - Avoid changing nested save.data
    """
    if not isinstance(step, dict):
        return step

    # Shallow copy for safety (callers typically pass transient dicts)
    out = dict(step)

    # 1) Validate 'data' is not used on step definition
    # 'data' is reserved for results (outputs), not inputs
    # TODO: Enable strict validation after migration period
    # if "data" in out and not _is_allowed_data_context(out):
    #     raise ValueError(
    #         f"Step definition cannot have 'data' field - use 'args' for inputs. "
    #         f"'data' is reserved for step results (outputs): STEP.<name>.data, LAST.data, THIS.data"
    #     )
    
    # Migration support: if 'data' exists and no 'args', convert data → args
    if "data" in out and "args" not in out:
        # Treat 'data' as legacy input args
        out["args"] = out.pop("data")

    # 2) Normalize aliases -> args
    merged: Dict[str, Any] = {}
    for alias in ("with", "params"):  # Note: 'args' is canonical, not an alias
        v = out.pop(alias, None)
        if v:
            if not isinstance(v, dict):
                raise ValueError(f"{alias} must be a mapping")
            merged.update(v)

    if "args" in out:
        if merged:
            # explicit 'args' wins on key conflicts
            merged.update(out["args"])  # type: ignore[index]
        out["args"] = merged or out["args"]
    elif merged:
        out["args"] = merged

    # 3) Iterator compatibility: loop -> iterator
    try:
        if "loop" in out and isinstance(out["loop"], dict):
            loop = dict(out.pop("loop"))
            out.setdefault("type", "iterator")
            # Only set args from loop.in when step has no explicit args already
            if "in" in loop and "args" not in out:
                out["args"] = loop.get("in")
            if "iterator" in loop:
                out.setdefault("element", loop.get("iterator"))
            # Carry over nested task/save if present under loop (legacy pattern)
            if "task" in loop and "task" not in out:
                out["task"] = loop.get("task")
            if "save" in loop and "save" not in out:
                out["save"] = loop.get("save")
    except Exception:
        # Best-effort normalization only
        pass

    return out


def _is_allowed_data_context(step: Dict[str, Any]) -> bool:
    """
    Check if 'data' field is in an allowed context.
    
    Allowed contexts:
    - Inside 'save' block (save.data is valid for save configuration)
    - Inside 'iterator.task' block (task definitions within iterators)
    
    Returns:
        True if data is allowed in this context, False otherwise
    """
    # For now, only allow 'data' if step has 'save' or if it's clearly a nested context
    # This is a simple heuristic; more sophisticated validation would track nesting depth
    return False  # Strict: no 'data' on step definitions


__all__ = ["normalize_step"]

