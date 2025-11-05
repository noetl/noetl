"""
SQL execution and result handling for DuckDB commands.
"""

from typing import List, Any, Dict
import json
import datetime

from noetl.core.common import DateTimeEncoder
from noetl.core.logger import setup_logger

from noetl.plugin.actions.duckdb.types import TaskResult
from noetl.plugin.actions.duckdb.errors import SQLExecutionError

logger = setup_logger(__name__, include_location=True)


def execute_sql_commands(
    connection: Any, 
    commands: List[str],
    task_id: str
) -> Dict[str, Any]:
    """
    Execute a list of SQL commands against a DuckDB connection.
    
    Args:
        connection: DuckDB connection
        commands: List of SQL commands to execute
        task_id: Task ID for tracking
        
    Returns:
        Results dictionary
        
    Raises:
        SQLExecutionError: If command execution fails
    """
    results = {"executed_commands": len(commands), "task_id": task_id}
    last_sql_command = None
    
    try:
        for i, command in enumerate(commands):
            if not command.strip():
                continue
                
            last_sql_command = command
            logger.debug(f"Executing SQL command {i+1}/{len(commands)}: {command[:100]}...")
            
            # Execute the command
            result = connection.execute(command)
            
            # Try to fetch results if available
            try:
                if hasattr(result, 'fetchall'):
                    rows = result.fetchall()
                    if rows:
                        results[f"command_{i+1}_rows"] = len(rows)
                        # Store a sample of results for debugging (first 5 rows)
                        if len(rows) <= 5:
                            results[f"command_{i+1}_sample"] = rows
                        else:
                            results[f"command_{i+1}_sample"] = rows[:5]
            except Exception:
                # Many DuckDB commands don't return fetchable results
                pass
                
        logger.info(f"Successfully executed {len(commands)} SQL commands")
        return results
        
    except Exception as e:
        error_msg = f"SQL execution failed at command: {last_sql_command}. Error: {e}"
        logger.error(error_msg)
        raise SQLExecutionError(error_msg)


def serialize_results(results: Any, task_id: str) -> Dict[str, Any]:
    """
    Serialize task results with proper datetime handling.
    
    Args:
        results: Raw results to serialize
        task_id: Task ID
        
    Returns:
        Serialized results dictionary
    """
    try:
        # Try serialization with custom datetime encoder
        json_results = json.dumps(results, cls=DateTimeEncoder)
        parsed_results = json.loads(json_results)
        return parsed_results
        
    except Exception as json_error:
        # Fallback to string representation
        logger.warning(f"Error serializing results with DateTimeEncoder: {str(json_error)}. Using string fallback.")
        return {"serialized_results": str(results), "task_id": task_id}


def create_task_result(
    task_id: str,
    status: str,
    duration: float,
    data: Any = None,
    error: str = None,
    traceback: str = None
) -> Dict[str, Any]:
    """
    Create a standardized task result dictionary.
    
    Args:
        task_id: Unique task identifier
        status: Task status ('success' or 'error')
        duration: Execution duration in seconds
        data: Task result data
        error: Error message if status is 'error'
        traceback: Python traceback if available
        
    Returns:
        Standardized result dictionary
    """
    result = {
        'id': task_id,
        'status': status,
        'duration': duration
    }
    
    if data is not None:
        result['data'] = data
    if error is not None:
        result['error'] = error
    if traceback is not None:
        result['traceback'] = traceback
        
    return result