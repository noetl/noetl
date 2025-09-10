"""
Broker API endpoints and helper utilities for broker operations.
Renamed from routes.py to endpoint.py to better reflect purpose and avoid defining endpoints in __init__.
"""
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from noetl.core.logger import setup_logger

# Processing functions live in the event processing module
from noetl.server.api.event.processing import (
    evaluate_broker_for_execution,
    check_and_process_completed_loops,
)

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/broker/evaluate/{execution_id}")
async def trigger_broker_evaluation(execution_id: str):
    """Manually trigger broker evaluation for an execution, including loop completion checks."""
    try:
        await evaluate_broker_for_execution(execution_id)
        return {"status": "success", "message": f"Broker evaluation triggered for execution {execution_id}"}
    except Exception as e:
        logger.error(f"Failed to trigger broker evaluation for {execution_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger broker evaluation: {str(e)}")


@router.post("/loop/complete/{execution_id}")
async def trigger_loop_completion(execution_id: str):
    """Manually trigger loop completion check for an execution."""
    try:
        await check_and_process_completed_loops(execution_id)
        return {"status": "success", "message": f"Loop completion check triggered for execution {execution_id}"}
    except Exception as e:
        logger.error(f"Failed to trigger loop completion for {execution_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger loop completion: {str(e)}")


def encode_task_for_queue(task_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply base64 encoding to multiline code/commands in task configuration
    to prevent serialization issues when passing through JSON in queue table.
    Only base64 versions are stored - original fields are removed to ensure single method of handling.
    
    Args:
        task_config: The original task configuration
        
    Returns:
        Modified task configuration with base64 encoded fields, original fields removed
    """
    if not isinstance(task_config, dict):
        return task_config
    
    import base64
    encoded_task = dict(task_config)
    
    try:
        # Encode Python code and remove original
        code_val = encoded_task.get('code')
        if isinstance(code_val, str) and code_val.strip():
            encoded_task['code_b64'] = base64.b64encode(code_val.encode('utf-8')).decode('ascii')
            # Remove original to ensure only base64 is used
            encoded_task.pop('code', None)
            
        # Encode command/commands for PostgreSQL and DuckDB and remove originals
        for field in ('command', 'commands'):
            cmd_val = encoded_task.get(field)
            if isinstance(cmd_val, str) and cmd_val.strip():
                encoded_task[f'{field}_b64'] = base64.b64encode(cmd_val.encode('utf-8')).decode('ascii')
                # Remove original to ensure only base64 is used
                encoded_task.pop(field, None)
                
    except Exception:
        logger.debug("ENCODE_TASK_FOR_QUEUE: Failed to encode task fields with base64", exc_info=True)
        
    return encoded_task

__all__ = [
    'router',
    'encode_task_for_queue',
]
