"""
Unified execute(task, ctx) entry (skeleton).
"""

from typing import Any, Dict

from .registry import get as get_handler


def execute(task_config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    tool_name = task_config.get("tool")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError("Unknown task tool: missing 'tool'")
    tool_name = tool_name.strip()
    handler = get_handler(tool_name)
    if not handler:
        raise ValueError(f"Unknown task tool: {tool_name}")
    return handler(task_config, context)
