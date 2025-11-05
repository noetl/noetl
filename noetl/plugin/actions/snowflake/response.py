"""
Snowflake response formatting module.

Handles result processing and response formatting for Snowflake tasks.
"""

import traceback
from typing import Dict, Tuple

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def process_results(results: Dict) -> Tuple[bool, str]:
    """
    Process execution results to determine overall status.
    
    Args:
        results: Dictionary of statement execution results
        
    Returns:
        Tuple of (has_error: bool, error_message: str)
    """
    errors = []
    
    for key, result in results.items():
        if result.get('status') == 'error':
            error_msg = result.get('error', 'Unknown error')
            query_snippet = result.get('query', 'Unknown query')
            errors.append(f"{key}: {error_msg} (Query: {query_snippet})")
    
    if errors:
        error_message = "; ".join(errors)
        return True, error_message
    
    return False, ""


def format_success_response(task_id: str, results: Dict) -> Dict:
    """
    Format successful task execution response.
    
    Args:
        task_id: Task identifier
        results: Dictionary of statement execution results
        
    Returns:
        Formatted response dictionary
    """
    return {
        'id': task_id,
        'status': 'success',
        'data': results
    }


def format_error_response(task_id: str, error_message: str, results: Dict) -> Dict:
    """
    Format error task execution response.
    
    Args:
        task_id: Task identifier
        error_message: Error message
        results: Dictionary of statement execution results (may be partial)
        
    Returns:
        Formatted response dictionary
    """
    return {
        'id': task_id,
        'status': 'error',
        'error': error_message,
        'data': results
    }


def format_exception_response(task_id: str, exception: Exception) -> Dict:
    """
    Format exception response for unexpected errors.
    
    Args:
        task_id: Task identifier
        exception: Exception that occurred
        
    Returns:
        Formatted response dictionary with traceback
    """
    return {
        'id': task_id,
        'status': 'error',
        'error': str(exception),
        'traceback': traceback.format_exc()
    }
