"""
Action registry for task tools (skeleton).
"""

from typing import Callable, Dict

_registry: Dict[str, Callable] = {}


def register(task_tool: str, handler: Callable) -> None:
    _registry[task_tool.lower()] = handler


def get(task_tool: str) -> Callable | None:
    return _registry.get(task_tool.lower())
