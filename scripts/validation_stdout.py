"""Helpers for parsing machine-readable validation command output."""

from __future__ import annotations

import json
from typing import Any


def parse_json_output(value: str) -> Any | None:
    """Parse JSON stdout that may include a log preface before the payload."""
    text = value.strip()
    if not text:
        return None
    candidates = [text]
    for marker in ("\n{", "\n["):
        index = text.rfind(marker)
        if index >= 0:
            candidates.append(text[index + 1 :])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for candidate in candidates[1:]:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None
