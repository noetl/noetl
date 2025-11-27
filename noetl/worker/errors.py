from __future__ import annotations

from typing import Any, Dict, Optional


class TaskExecutionError(RuntimeError):
    """Raised when a task execution reports an error status."""

    def __init__(self, message: str, result: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.result = result or {}
