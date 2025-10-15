"""
Plugin tool package - MCP-compliant generic functionality.

This package provides core tools for plugin execution following the
Model Context Protocol (MCP) approach:

- Task execution: Main entry point for routing tasks to appropriate plugins
- Event reporting: Worker-to-server communication with metadata enrichment
- SQL utilities: SQL statement parsing and processing

These tools are used across all plugin implementations to provide consistent
functionality and MCP-compliant interfaces.
"""

from .execution import execute_task, execute_task_resolved
from .reporting import report_event
from .sql import sql_split

__all__ = [
    'execute_task',
    'execute_task_resolved',
    'report_event',
    'sql_split',
]
