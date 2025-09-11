"""
Action registry for task types (skeleton).
"""

from typing import Callable, Dict


_registry: Dict[str, Callable] = {}


def register(task_type: str, handler: Callable) -> None:
    _registry[task_type.lower()] = handler


def get(task_type: str) -> Callable | None:
    return _registry.get(task_type.lower())

