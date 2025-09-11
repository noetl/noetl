"""
Loop and until semantics (skeleton).
"""

from typing import Any, Dict, Iterable


def iterate(items: Iterable[Any]):
    for i, item in enumerate(items or []):
        yield i, item

