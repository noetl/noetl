"""
SQL execution and result handling for DuckDB commands.
"""

from typing import List, Any, Dict, Optional
import json
import datetime

from noetl.core.common import DateTimeEncoder
from noetl.core.logger import setup_logger

from noetl.tools.duckdb.types import TaskResult
from noetl.tools.duckdb.errors import SQLExecutionError, ExcelExportError

logger = setup_logger(__name__, include_location=True)


def execute_sql_commands(
    connection: Any, 
    commands: List[str],
    task_id: str,
    excel_manager: Optional[Any] = None
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
            
            # Check for Excel COPY commands handled via Polars
            try:
                if excel_manager and excel_manager.try_capture_command(connection, command, i):
                    results["excel_commands"] = results.get("excel_commands", 0) + 1
                    continue
            except ExcelExportError as exc:
                error_msg = f"Excel export failed for command {i+1}: {exc}"
                logger.error(error_msg)
                raise SQLExecutionError(error_msg) from exc

            # Execute the command inside DuckDB
            result = connection.execute(command)
            
            # Diagnostic: Check settings if this was a COPY command that failed previously
            if "COPY" in command.upper() and ("gs://" in command or "s3://" in command):
                try:
                    s3_settings = connection.execute("SELECT name, value FROM duckdb_settings() WHERE name LIKE 's3_%' OR name LIKE 'gcs_%'").fetchall()
                    logger.info(f"Cloud settings after COPY attempt: {s3_settings}")
                    logger.debug(f"[DUCKDB DEBUG] Cloud settings: {s3_settings}")
                except Exception as e:
                    logger.exception(f"Copy failed {e}")

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
                logger.exception("Many DuckDB commands don't return fetchable results")
        
        # Force checkpoint to ensure all changes are persisted to disk
        # This is critical for distributed workers accessing the same database file
        try:
            connection.execute("CHECKPOINT;")
            logger.debug("Executed CHECKPOINT to flush changes to disk")
        except Exception as e:
            logger.warning(f"Failed to execute CHECKPOINT: {e}")
                
        if excel_manager:
            excel_summary = excel_manager.finalize()
            if excel_summary:
                results["excel_exports"] = excel_summary

        logger.info(f"Successfully executed {len(commands)} SQL commands")
        return results
        
    except Exception as e:
        error_msg = f"SQL execution failed at command: {last_sql_command}. Error: {e}"
        logger.exception(error_msg)
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
        logger.exception(f"Error serializing results with DateTimeEncoder: {str(json_error)}. Using string fallback.")
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
