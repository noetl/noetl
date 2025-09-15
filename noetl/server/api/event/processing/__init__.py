"""
Event processing package - handles workflow execution, loop completion, and broker evaluation.

This package is organized into logical modules:
- workflow: Database operations for workflow/step management
- loop_completion: Loop processing and aggregation logic
- child_executions: Child execution monitoring and completion
- broker: Main workflow broker evaluation logic
"""

# Import main public functions
from .broker import evaluate_broker_for_execution, _evaluate_broker_for_execution
from .loop_completion import check_and_process_completed_loops
from .child_executions import check_and_process_completed_child_executions, check_distributed_loop_completion, _check_distributed_loop_completion  
from .workflow import populate_workflow_tables

# Re-export for backward compatibility - alias for old naming
_populate_workflow_tables = populate_workflow_tables

__all__ = [
    'evaluate_broker_for_execution',
    '_evaluate_broker_for_execution',
    'check_and_process_completed_loops', 
    'check_and_process_completed_child_executions',
    'check_distributed_loop_completion',
    '_check_distributed_loop_completion',
    '_populate_workflow_tables',
    'populate_workflow_tables'
    'populate_workflow_tables'
]