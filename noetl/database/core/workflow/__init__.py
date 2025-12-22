"""
Workflow orchestration modules.

This package contains workflow execution components moved from plugin/controller/:

- playbook: Sub-playbook execution
- workbook: Reusable task catalog
- result: Result aggregation for loops
"""

from noetl.core.workflow.playbook import execute_playbook_task
from noetl.core.workflow.workbook import execute_workbook_task
from noetl.core.workflow.result import process_loop_aggregation_job

__all__ = [
    "execute_playbook_task",
    "execute_workbook_task",
    "process_loop_aggregation_job",
]
