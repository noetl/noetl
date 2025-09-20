"""
Normalization helpers for NoETL DSL steps.

Responsibilities:
- Merge legacy aliases (with/args/params) into canonical data
- Convert legacy loop: {in, iterator} into type: iterator + data/element

Notes:
- Do not touch nested save.data or iterator.data blocks
- Perform minimal, predictable mutations on a shallow copy of input
"""

from __future__ import annotations

from typing import Any, Dict


def normalize_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a step dict in-place and return it.

    - Merge legacy aliases (with/args/params) into data, with explicit data winning on key conflicts
    - Convert legacy loop syntax to iterator shape
    - Avoid changing nested save.data
    """
    if not isinstance(step, dict):
        return step

    # Shallow copy for safety (callers typically pass transient dicts)
    out = dict(step)

    # 1) Normalize aliases -> data
    merged: Dict[str, Any] = {}
    for alias in ("with", "args", "params"):
        v = out.pop(alias, None)
        if v:
            if not isinstance(v, dict):
                raise ValueError(f"{alias} must be a mapping")
            merged.update(v)

    if "data" in out:
        if merged:
            # 'data' wins on key conflicts
            merged.update(out["data"])  # type: ignore[index]
        out["data"] = merged or out["data"]
    elif merged:
        out["data"] = merged

    # 2) Iterator compatibility: loop -> iterator
    try:
        if "loop" in out and isinstance(out["loop"], dict):
            loop = dict(out.pop("loop"))
            out.setdefault("type", "iterator")
            # Only set data from loop.in when step has no explicit data already
            if "in" in loop and "data" not in out:
                out["data"] = loop.get("in")
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


__all__ = ["normalize_step"]

