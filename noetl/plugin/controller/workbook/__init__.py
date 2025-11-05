"""
Workbook execution plugin package for NoETL.

This package handles 'workbook' type tasks which look up actions
by name in the workbook section of a playbook and execute them.

Package Structure:
    - catalog.py: Catalog operations (fetch playbook, find workbook action)
    - executor.py: Main workbook task execution orchestrator
"""

from noetl.plugin.controller.workbook.executor import execute_workbook_task

__all__ = ['execute_workbook_task']
