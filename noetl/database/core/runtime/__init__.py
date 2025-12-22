"""
Pure runtime engine (context, router, loop, registry, executor).
This package must remain side-effect free.

Exports runtime utilities moved from plugin/runtime/:
- sql_split: SQL statement splitting
- report_event, report_event_async: Worker-to-server event reporting
- execute_task, execute_task_resolved: Task execution
- execute_with_retry: Retry logic
"""

# SQL utilities
from noetl.core.runtime.sql import sql_split

# Event reporting
from noetl.core.runtime.events import report_event, report_event_async

# Task execution
from noetl.core.runtime.execution import execute_task, execute_task_resolved

# Retry logic
from noetl.core.runtime.retry import execute_with_retry

# Context
from noetl.core.runtime.context import ExecutionContext

__all__ = [
    # SQL utilities
    "sql_split",
    # Event reporting
    "report_event",
    "report_event_async",
    # Task execution
    "execute_task",
    "execute_task_resolved",
    # Retry logic
    "execute_with_retry",
    # Context
    "ExecutionContext",
]

