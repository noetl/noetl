"""
PostgreSQL response processing and result formatting.

This module handles:
- Result status checking
- Error aggregation
- Response formatting for task completion
"""

from typing import Any, Dict, Tuple
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


def _statement_sort_key(command_key: str) -> int:
    try:
        return int(str(command_key).split("_", 1)[1])
    except Exception:
        return -1


def collapse_results_to_last_command(results: Dict[str, Dict]) -> Dict[str, Any]:
    """
    Collapse multi-command execution output into a single task result.

    Runtime contract:
    - Postgres tool returns a single result object
    - If multiple SQL statements ran, the LAST command is the task result payload
    - command_* keyed transport is not exposed outside the tool boundary
    """
    if not isinstance(results, dict) or not results:
        return {"status": "success", "message": "No SQL statements executed", "statement_count": 0}

    ordered_keys = sorted(results.keys(), key=_statement_sort_key)
    last_key = ordered_keys[-1]
    last_result = results.get(last_key)
    payload: Dict[str, Any]
    if isinstance(last_result, dict):
        payload = dict(last_result)
    else:
        payload = {"value": last_result}

    errors = []
    for statement_idx, statement_key in enumerate(ordered_keys):
        statement_result = results.get(statement_key) or {}
        if isinstance(statement_result, dict) and statement_result.get("status") == "error":
            errors.append(
                {
                    "statement_index": statement_idx,
                    "message": str(statement_result.get("message") or statement_result.get("error") or "unknown error"),
                }
            )

    payload["statement_count"] = len(ordered_keys)
    if errors:
        payload["status"] = "error"
        payload["errors"] = errors
        payload["message"] = "; ".join(
            f"statement_{e['statement_index']}: {e['message']}" for e in errors
        )
    elif "status" not in payload:
        payload["status"] = "success"
    return payload


def format_success_response(task_id: str, result_data: Dict[str, Any]) -> Dict:
    """
    Format successful task response.
    
    Args:
        task_id: The task identifier
        result_data: Collapsed task result payload
        
    Returns:
        Success response dictionary with task ID, status, and data
    """
    return {
        'id': task_id,
        'status': 'success',
        'data': result_data
    }


def format_error_response(task_id: str, error_message: str, result_data: Dict[str, Any] = None) -> Dict:
    """
    Format error task response.
    
    Args:
        task_id: The task identifier
        error_message: The error message
        result_data: Optional collapsed task result payload
        
    Returns:
        Error response dictionary with task ID, status, error message, and optional data
    """
    response = {
        'id': task_id,
        'status': 'error',
        'error': error_message
    }
    
    if result_data is not None:
        response['data'] = result_data
    
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
