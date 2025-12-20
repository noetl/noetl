"""
Loop result aggregation worker.

Builds aggregated results for loop steps by collecting per-iteration results
from event log and emitting final aggregated events.
"""

from __future__ import annotations
import json
from typing import Any, Dict, List, Optional

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def fetch_iteration_results(
    execution_id: Any, 
    step_name: str
) -> List[Any]:
    """
    Fetch per-iteration results from server API.
    
    Args:
        execution_id: Parent execution ID
        step_name: Loop step name
        
    Returns:
        List of iteration results
    """
    agg_list: List[Any] = []
    
    try:
        import os
        import httpx
        
        base = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
        if not base.endswith('/api'):
            base = base + '/api'
        
        params = {
            "execution_id": str(execution_id), 
            "step_name": str(step_name)
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/aggregate/loop/results", params=params)
            
            if resp.status_code == 200:
                data = resp.json() or {}
                if isinstance(data, dict):
                    results = data.get('results')
                    if isinstance(results, list):
                        agg_list = results
    except Exception:
        logger.debug(
            "RESULT.WORKER: Fallback to empty aggregate due to API error", 
            exc_info=True
        )
    
    return agg_list


async def emit_aggregation_events(
    execution_id: Any,
    step_name: str,
    aggregated_results: List[Any],
    total_iterations: Optional[int] = None
) -> None:
    """
    Emit final aggregated events for loop completion.
    
    Args:
        execution_id: Parent execution ID
        step_name: Loop step name
        aggregated_results: List of aggregated results
        total_iterations: Total number of iterations
    """
    from noetl.server.api.event import get_event_service
    
    es = get_event_service()
    count = len(aggregated_results)
    
    payload = {
        'data': {
            'results': aggregated_results, 
            'result': aggregated_results, 
            'count': count
        },
        'results': aggregated_results,
        'result': aggregated_results,
        'count': count
    }
    
    context = {
        'loop_completed': True,
        'total_iterations': total_iterations if total_iterations is not None else count
    }
    
    # Emit action_completed event
    await es.emit({
        'execution_id': execution_id,
        'event_type': 'action_completed',
        'node_name': step_name,
        'node_type': 'loop',
        'status': 'COMPLETED',
        'result': payload,
        'context': context
    })
    
    # Emit result event
    await es.emit({
        'execution_id': execution_id,
        'event_type': 'result',
        'node_name': step_name,
        'node_type': 'loop',
        'status': 'COMPLETED',
        'result': payload,
        'context': context
    })
    
    # Emit loop_completed marker (idempotent if already exists)
    try:
        completion_context = context.copy()
        completion_context['aggregated_results'] = aggregated_results
        
        await es.emit({
            'execution_id': execution_id,
            'event_type': 'loop_completed',
            'node_name': step_name,
            'node_type': 'loop_control',
            'status': 'COMPLETED',
            'result': payload,
            'context': completion_context
        })
    except Exception:
        pass


async def process_loop_aggregation_job(job_row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Worker entry-point to aggregate per-iteration loop results for a step.
    
    This function:
    1. Extracts execution_id and step_name from job context
    2. Fetches per-iteration results from server API
    3. Emits final aggregated events back to server
    
    Expected job_row structure:
    {
        "execution_id": <int or str>,
        "context": {
            "step_name": <str>,
            "total_iterations": <int, optional>
        }
    }
    
    The worker reads per-iteration events (event_type in ['result','action_completed'] 
    with node_id like %-iter-%) and posts final aggregated result events back to 
    server for the loop step.
    
    Args:
        job_row: Job configuration with execution_id and context
        
    Returns:
        Status dictionary with 'status' and 'count' or 'error'
    """
    try:
        # Extract job parameters
        execution_id = job_row.get('execution_id') or job_row.get('executionId')
        
        input_ctx = job_row.get('context') or {}
        if isinstance(input_ctx, str):
            try:
                input_ctx = json.loads(input_ctx)
            except Exception:
                input_ctx = {}
        
        step_name = (input_ctx.get('step_name') or 
                    input_ctx.get('node_name') or 
                    input_ctx.get('loop_step_name'))
        
        total_iterations = input_ctx.get('total_iterations')
        
        if not execution_id or not step_name:
            raise ValueError(
                'process_loop_aggregation_job requires execution_id and step_name'
            )
        
        # Fetch per-iteration results from server API
        aggregated_results = await fetch_iteration_results(execution_id, step_name)
        
        # Emit final events back to server
        await emit_aggregation_events(
            execution_id, 
            step_name, 
            aggregated_results, 
            total_iterations
        )
        
        logger.info(
            f"RESULT.WORKER: Aggregated {len(aggregated_results)} items for "
            f"{execution_id}/{step_name}"
        )
        
        return {
            'status': 'ok', 
            'count': len(aggregated_results)
        }
        
    except Exception as e:
        logger.exception(f"RESULT.WORKER: Failed aggregation: {e}")
        return {
            'status': 'error', 
            'message': str(e)
        }
