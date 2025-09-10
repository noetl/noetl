"""
Unified execute(task, ctx) entry (skeleton).
"""

from typing import Any, Dict
from .registry import get as get_handler


def execute(task_config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    handler = get_handler(task_config.get("type", ""))
    if not handler:
        raise ValueError(f"Unknown task type: {task_config.get('type')}")
    return handler(task_config, context)

