"""
Deprecated sink functionality.

This module provides a stub for the removed execute_sink_task function.
Sink has been replaced by the tool: task approach in case conditions.
"""

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def execute_sink_task(*args, **kwargs):
    """
    DEPRECATED: Sink functionality has been removed.

    Use tool: task in case conditions instead.

    This stub function logs a deprecation warning and returns an error result.
    """
    logger.error(
        "DEPRECATED: execute_sink_task is no longer supported. "
        "Sink has been replaced by 'tool: task' in case conditions. "
        "Please refactor your playbooks."
    )
    return {
        "status": "error",
        "error": "Sink functionality is deprecated. Use 'tool: task' in case conditions instead.",
        "deprecated": True
    }


__all__ = ["execute_sink_task"]
