"""
Iterator completion handling.

Monitors and aggregates results from iterator steps that spawn child playbook executions.
Regular iterator steps complete on workers and don't need server-side aggregation.
"""

from noetl.core.common import get_async_db_connection
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def check_iterator_completions(execution_id: str) -> None:
    """
    Check for iterator steps with child playbook executions that have completed.
    
    Only handles iterators that spawn child playbooks (type: playbook iterations).
    Regular iterators complete entirely on workers.
    """
    logger.debug(f"ITERATORS: Checking for completed child executions in {execution_id}")
    
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Find iterator steps with child executions that haven't been finalized
                await cur.execute(
                    """
                    SELECT DISTINCT 
                        node_name,
                        COUNT(*) as total_iterations
                    FROM noetl.event 
                    WHERE execution_id = %s 
                      AND event_type = 'iteration_started'
                      AND context::text LIKE '%%child_execution_id%%'
                      AND node_name NOT IN (
                          SELECT DISTINCT node_name 
                          FROM noetl.event 
                          WHERE execution_id = %s 
                            AND event_type IN ('iterator_completed', 'action_completed')
                      )
                    GROUP BY node_name
                    """,
                    (execution_id, execution_id)
                )
                active_iterators = await cur.fetchall()
                
                if not active_iterators:
                    return
                
                from ..service import get_event_service
                es = get_event_service()
                
                for iterator_step_name, total_iterations in active_iterators:
                    await _check_iterator_completion(
                        cur, es, execution_id, iterator_step_name, total_iterations
                    )
                    
    except Exception as e:
        logger.debug(f"ITERATORS: Error checking completions: {e}", exc_info=True)


async def _check_iterator_completion(
    cur, event_service, execution_id: str, step_name: str, total_iterations: int
) -> None:
    """Check if all child executions for an iterator have completed."""
    
    import json
    
    # Get all child execution IDs
    await cur.execute(
        """
        SELECT 
            (context::json)->>'child_execution_id' as child_exec_id,
            COALESCE((context::json)->>'index', '0') as iteration_index
        FROM noetl.event 
        WHERE execution_id = %s 
          AND event_type = 'iteration_started'
          AND node_name = %s
          AND context::text LIKE '%%child_execution_id%%'
        ORDER BY CAST(COALESCE((context::json)->>'index', '0') AS INTEGER)
        """,
        (execution_id, step_name)
    )
    child_executions = await cur.fetchall()
    
    if not child_executions:
        return
    
    # Check completion status
    all_complete = True
    results = []
    
    for child_exec_id, iteration_index in child_executions:
        if not child_exec_id:
            continue
        
        # Check if child completed
        await cur.execute(
            """
            SELECT result FROM noetl.event
            WHERE execution_id = %s
              AND event_type = 'execution_complete'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (child_exec_id,)
        )
        child_result_row = await cur.fetchone()
        
        if child_result_row:
            result_data = child_result_row[0]
            try:
                result = json.loads(result_data) if isinstance(result_data, str) else result_data
            except Exception:
                result = result_data
            
            results.append({
                'index': int(iteration_index) if iteration_index else 0,
                'child_execution_id': child_exec_id,
                'result': result
            })
        else:
            all_complete = False
            break
    
    if all_complete:
        # All children complete - emit iterator_completed
        logger.info(f"ITERATORS: All {len(results)} iterations complete for {step_name}")
        
        results.sort(key=lambda x: x['index'])
        aggregated_results = [r['result'] for r in results]
        
        await event_service.emit({
            'execution_id': execution_id,
            'event_type': 'iterator_completed',
            'node_name': step_name,
            'node_type': 'iterator',
            'status': 'COMPLETED',
            'result': {
                'data': aggregated_results,
                'total_iterations': len(results),
                'child_executions': [r['child_execution_id'] for r in results]
            },
            'context': {
                'iterator_step': step_name,
                'iterations': len(results)
            }
        })
