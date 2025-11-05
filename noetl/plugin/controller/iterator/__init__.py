"""
Iterator task executor package for NoETL.

This package handles 'iterator' type tasks which execute nested tasks
over collections with per-iteration context and optional per-item save,
supporting sequential or async execution with bounded concurrency.

Package Structure:
    - utils.py: Helper functions for coercion, filtering, sorting
    - config.py: Configuration extraction and validation
    - execution.py: Per-iteration execution logic
    - executor.py: Main iterator task orchestrator
"""

from noetl.plugin.controller.iterator.executor import execute_loop_task

__all__ = ['execute_loop_task']
