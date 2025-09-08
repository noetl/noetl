"""
Result processing worker: builds aggregated results for loop steps.
"""
from __future__ import annotations
import json
from typing import Any, Dict, List, Optional
from noetl.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

async def process_loop_aggregation_job(job_row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Worker entry-point to aggregate per-iteration loop results for a step.
    Expects job_row to contain at least:
      - execution_id: parent execution id (int or str)
      - context: dict with keys { step_name, total_iterations? }
    The worker reads per-iteration events (event_type in ['result','action_completed'] with node_id like %-iter-%)
    and posts final aggregated result events back to server for the loop step.
    """
    try:
        execution_id = job_row.get('execution_id') or job_row.get('executionId')
        input_ctx = job_row.get('context') or {}
        if isinstance(input_ctx, str):
            try:
                input_ctx = json.loads(input_ctx)
            except Exception:
                input_ctx = {}
        step_name = (input_ctx.get('step_name') or input_ctx.get('node_name') or input_ctx.get('loop_step_name'))
        total_iterations = input_ctx.get('total_iterations')
        if not execution_id or not step_name:
            raise ValueError('process_loop_aggregation_job requires execution_id and step_name')

        # Pull per-iteration results from server API (not directly from DB)
        agg_list: List[Any] = []
        try:
            import os
            import httpx
            base = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
            if not base.endswith('/api'):
                base = base + '/api'
            params = {"execution_id": str(execution_id), "step_name": str(step_name)}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base}/aggregate/loop/results", params=params)
                if resp.status_code == 200:
                    data = resp.json() or {}
                    if isinstance(data, dict):
                        results = data.get('results')
                        if isinstance(results, list):
                            agg_list = results
        except Exception:
            logger.debug("RESULT.WORKER: Fallback to empty aggregate due to API error", exc_info=True)

        # Emit final events back to server
        payload = {
            'data': {'results': agg_list, 'result': agg_list, 'count': len(agg_list)},
            'results': agg_list,
            'result': agg_list,
            'count': len(agg_list)
        }
        from noetl.api.event import get_event_service
        es = get_event_service()
        await es.emit({
            'execution_id': execution_id,
            'event_type': 'action_completed',
            'node_name': step_name,
            'node_type': 'loop',
            'status': 'COMPLETED',
            'result': payload,
            'context': {
                'loop_completed': True,
                'total_iterations': total_iterations if total_iterations is not None else len(agg_list)
            }
        })
        await es.emit({
            'execution_id': execution_id,
            'event_type': 'result',
            'node_name': step_name,
            'node_type': 'loop',
            'status': 'COMPLETED',
            'result': payload,
            'context': {
                'loop_completed': True,
                'total_iterations': total_iterations if total_iterations is not None else len(agg_list)
            }
        })
        # Additionally emit a loop_completed marker (idempotent if already exists)
        try:
            await es.emit({
                'execution_id': execution_id,
                'event_type': 'loop_completed',
                'node_name': step_name,
                'node_type': 'loop_control',
                'status': 'COMPLETED',
                'result': payload,
                'context': {
                    'loop_completed': True,
                    'total_iterations': total_iterations if total_iterations is not None else len(agg_list),
                    'aggregated_results': agg_list
                }
            })
        except Exception:
            pass
        logger.info(f"RESULT.WORKER: Aggregated {len(agg_list)} items for {execution_id}/{step_name}")
        return {'status': 'ok', 'count': len(agg_list)}
    except Exception as e:
        logger.exception(f"RESULT.WORKER: Failed aggregation: {e}")
        return {'status': 'error', 'message': str(e)}

__all__ = ['process_loop_aggregation_job']
