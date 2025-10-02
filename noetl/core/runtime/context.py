"""
Execution context utilities (skeleton).
"""

from typing import Any, Dict


class ExecutionContext:
    def __init__(self, workload: Dict[str, Any] | None = None, results: Dict[str, Any] | None = None):
        self.workload = workload or {}
        self.results = results or {}

