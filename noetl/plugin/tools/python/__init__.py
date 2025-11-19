"""
Python plugin package for NoETL.
"""

from noetl.plugin.tools.python.executor import (
    execute_python_task,
    execute_python_task_async,
)

__all__ = ['execute_python_task', 'execute_python_task_async']
