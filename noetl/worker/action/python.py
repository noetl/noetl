import os
import uuid
import json
import datetime
from typing import Dict

from jinja2 import Environment

from noetl.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def execute_python_task(task_config: Dict, context: Dict, jinja_env: Environment, task_with: Dict, log_event_callback=None) -> Dict:
    """
    Execute a Python task.
    """
    logger.debug("=== PYTHON.EXECUTE_TASK: Function entry ===")
    logger.debug(f"PYTHON.EXECUTE_TASK: Parameters - task_config={task_config}, task_with={task_with}")

    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'python_task')
    start_time = datetime.datetime.now()

    try:
        code = task_config.get('code', '')
        logger.debug(f"PYTHON.EXECUTE_TASK: Python code length={len(code)} chars")

        event_id = None
        if log_event_callback:
            logger.debug(f"PYTHON.EXECUTE_TASK: Writing task_start event log")
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'python',
                'in_progress', 0, context, None,
                {'with_params': task_with}, None
            )
            logger.debug(f"PYTHON.EXECUTE_TASK: Task start event_id={event_id}")

        logger.debug(f"PYTHON.EXECUTE_TASK: Setting up execution globals")
        exec_globals = {
            '__builtins__': __builtins__,
            'context': context,
            'os': os,
            'json': json,
            'datetime': datetime,
            'uuid': uuid
        }
        logger.debug(f"PYTHON.EXECUTE_TASK: Execution globals keys: {list(exec_globals.keys())}")

        exec_locals = {}
        logger.debug(f"PYTHON.EXECUTE_TASK: Executing Python code")
        exec(code, exec_globals, exec_locals)
        logger.debug(f"PYTHON.EXECUTE_TASK: Python execution completed")
        logger.debug(f"PYTHON.EXECUTE_TASK: Execution locals keys: {list(exec_locals.keys())}")

        if 'main' in exec_locals:
            result_data = exec_locals['main'](**task_with)
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_complete', task_id, task_name, 'python',
                    'success', duration, context, result_data,
                    {'with_params': task_with}, event_id
                )

            return {
                'id': task_id,
                'status': 'success',
                'data': result_data
            }
        else:
            error_msg = "Main function must be defined in Python task."
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_error', task_id, task_name, 'python',
                    'error', duration, context, None,
                    {'error': error_msg, 'with_params': task_with}, event_id
                )

            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"PYTHON.EXECUTE_TASK: Exception - {error_msg}", exc_info=True)

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.debug(f"PYTHON.EXECUTE_TASK: Task duration={duration} seconds (error path)")

        if log_event_callback:
            logger.debug(f"PYTHON.EXECUTE_TASK: Writing task_error event log")
            log_event_callback(
                'task_error', task_id, task_name, 'python',
                'error', duration, context, None,
                {'error': error_msg, 'with_params': task_with}, event_id
            )

        result = {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }
        logger.debug(f"PYTHON.EXECUTE_TASK: Returning error result={result}")
        logger.debug("=== PYTHON.EXECUTE_TASK: Function exit (error) ===")
        return result


__all__ = ["execute_python_task"]
