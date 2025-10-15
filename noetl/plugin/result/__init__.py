"""
Result processing package for NoETL.

This package provides utilities for processing and aggregating loop iteration results.
This is not an action type plugin, but a utility function used by the result aggregation worker.

Package Structure:
    - aggregation.py: Loop result aggregation worker function
"""

from .aggregation import process_loop_aggregation_job

__all__ = ['process_loop_aggregation_job']
