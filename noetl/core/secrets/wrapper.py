"""
Secret manager task execution wrapper.

This module provides a thin adapter for executing secret manager tasks.
The actual secret retrieval logic is delegated to the SecretManager instance
passed at runtime (typically from Google Cloud Secret Manager or other providers).
"""

import uuid
import datetime
from typing import Dict, Callable, Optional
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def create_log_event_wrapper(
    log_event_callback: Optional[Callable],
    task_with: Dict
) -> Callable:
    """
    Create a log event wrapper that injects task_with parameters into metadata.
    
    This wrapper function ensures that the 'with_params' are included in the
    event metadata for proper logging and tracking.
    
    Args:
        log_event_callback: Optional callback function to log events
        task_with: The rendered 'with' parameters dictionary
        
    Returns:
        Wrapped log event callback function that includes task_with in metadata
    """
    def log_event_wrapper(
        event_type: str,
        task_id: str,
        task_name: str,
        node_type: str,
        status: str,
        duration: float,
        context: Dict,
        result: any,
        metadata: Optional[Dict],
        parent_event_id: Optional[str]
    ) -> Optional[str]:
        """
        Log event wrapper that injects with_params into metadata.
        
        Args:
            event_type: Type of event ('task_start', 'task_complete', etc.)
            task_id: Unique task identifier
            task_name: Name of the task
            node_type: Type of node ('secrets')
            status: Task status ('in_progress', 'success', 'error')
            duration: Task duration in seconds
            context: Execution context
            result: Task result data
            metadata: Additional metadata
            parent_event_id: Parent event identifier
            
        Returns:
            Event ID if callback exists, None otherwise
        """
        if log_event_callback:
            if metadata is None:
                metadata = {}
            metadata['with_params'] = task_with
            return log_event_callback(
                event_type, task_id, task_name, node_type,
                status, duration, context, result,
                metadata, parent_event_id
            )
        return None
    
    return log_event_wrapper
