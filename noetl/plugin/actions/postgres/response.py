"""
PostgreSQL response processing and result formatting.

This module handles:
- Result status checking
- Error aggregation
- Response formatting for task completion
"""

from typing import Dict, Tuple
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def process_results(results: Dict[str, Dict]) -> Tuple[bool, str]:
    """
    Process execution results and determine overall status.
    
    Args:
        results: Dictionary mapping command indices to result dictionaries
        
    Returns:
        Tuple of (has_error: bool, error_message: str)
    """
    has_error = False
    error_message = ""
    
    for cmd_key, cmd_result in results.items():
        if cmd_result.get('status') == 'error':
            has_error = True
            error_message += f"{cmd_key}: {cmd_result.get('message')}; "
    
    return has_error, error_message.strip()


def format_success_response(task_id: str, results: Dict[str, Dict]) -> Dict:
    """
    Format successful task response.
    
    Args:
        task_id: The task identifier
        results: Dictionary of command execution results
        
    Returns:
        Success response dictionary with task ID, status, and data
    """
    return {
        'id': task_id,
        'status': 'success',
        'data': results
    }


def format_error_response(task_id: str, error_message: str, results: Dict[str, Dict] = None) -> Dict:
    """
    Format error task response.
    
    Args:
        task_id: The task identifier
        error_message: The error message
        results: Optional dictionary of command execution results
        
    Returns:
        Error response dictionary with task ID, status, error message, and optional data
    """
    response = {
        'id': task_id,
        'status': 'error',
        'error': error_message
    }
    
    if results is not None:
        response['data'] = results
    
    return response


def format_exception_response(task_id: str, error: Exception) -> Dict:
    """
    Format exception response with traceback.
    
    Args:
        task_id: The task identifier
        error: The exception object
        
    Returns:
        Error response dictionary with task ID, status, error message, and traceback
    """
    import traceback as _tb
    
    error_msg = str(error)
    tb_text = _tb.format_exc()
    
    return {
        'id': task_id,
        'status': 'error',
        'error': error_msg,
        'traceback': tb_text
    }
