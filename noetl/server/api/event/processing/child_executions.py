"""
Child execution monitoring and completion processing.
Handles proactive checking of completed child executions and processing their results.
"""

import json
from typing import Any
from noetl.core.common import get_async_db_connection
from noetl.core.logger import setup_logger
from noetl.server.api.event.event_log import EventLog

logger = setup_logger(__name__, include_location=True)


async def check_and_process_completed_child_executions(parent_execution_id: str):
    """
    Proactively check for completed child executions and process their results.
    This handles the case where child executions complete but don't send events to the server.
    """
    try:
        logger.info(f"PROACTIVE_COMPLETION_CHECK: Checking for completed child executions of parent {parent_execution_id}")
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Find all child executions spawned by this parent
                await cur.execute(
                    """
                    SELECT DISTINCT 
                        (context::json)->>'child_execution_id' as child_exec_id,
                        node_name as parent_step,
                        node_id as iter_node_id
                    FROM noetl.event_log 
                    WHERE execution_id = %s 
                      AND event_type = 'loop_iteration'
                      AND context::text LIKE '%%child_execution_id%%'
                    """,
                    (parent_execution_id,)
                )
                child_executions = await cur.fetchall()
                
                if not child_executions:
                    logger.debug(f"PROACTIVE_COMPLETION_CHECK: No child executions found for parent {parent_execution_id}")
                    return
                
                from ..service import get_event_service
                
                for child_exec_id, parent_step, iter_node_id in child_executions:
                    if not child_exec_id:
                        continue
                    
                    logger.info(f"PROACTIVE_COMPLETION_CHECK: Checking child execution {child_exec_id} for parent step {parent_step}")
                    
                    # Check if this child execution has completed
                    await cur.execute(
                        """
                        SELECT 1 FROM noetl.event_log 
                        WHERE execution_id = %s 
                          AND event_type = 'execution_start'
                        """,
                        (child_exec_id,)
                    )
                    child_exists = await cur.fetchone() is not None
                    
                    if not child_exists:
                        logger.debug(f"PROACTIVE_COMPLETION_CHECK: Child execution {child_exec_id} not found in event log yet")
                        continue
                    
                    # Check if we've already processed this child completion
                    await cur.execute(
                        """
                        SELECT 1 FROM noetl.event_log 
                        WHERE execution_id = %s 
                          AND event_type = 'action_completed'
                          AND node_name = %s
                          AND node_id LIKE %s
                        """,
                        (parent_execution_id, parent_step, f'%-iter-{child_exec_id}')
                    )
                    already_processed = await cur.fetchone() is not None
                    
                    if already_processed:
                        logger.debug(f"PROACTIVE_COMPLETION_CHECK: Child execution {child_exec_id} already processed")
                        continue
                    
                    # Check if child execution has meaningful results
                    child_result = None
                    for step_name in ['evaluate_weather_step', 'evaluate_weather', 'alert_step', 'log_step']:
                        await cur.execute(
                            """
                            SELECT result FROM noetl.event_log
                            WHERE execution_id = %s
                              AND node_name = %s
                              AND event_type = 'action_completed'
                              AND lower(status) IN ('completed','success')
                              AND result IS NOT NULL
                              AND result != '{}'
                              AND NOT (result::text LIKE '%%"skipped": true%%')
                              AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                            ORDER BY timestamp DESC
                            LIMIT 1
                            """,
                            (child_exec_id, step_name)
                        )
                        result_row = await cur.fetchone()
                        if result_row:
                            result_data = result_row[0] if isinstance(result_row, tuple) else result_row.get('result')
                            try:
                                child_result = json.loads(result_data) if isinstance(result_data, str) else result_data
                                # Extract data if wrapped
                                if isinstance(child_result, dict) and 'data' in child_result:
                                    child_result = child_result['data']
                                logger.info(f"PROACTIVE_COMPLETION_CHECK: Found meaningful result from step {step_name} in child {child_exec_id}: {child_result}")
                                break
                            except Exception as e:
                                logger.debug(f"PROACTIVE_COMPLETION_CHECK: Error parsing result from {step_name}: {e}")
                                continue

                    # Fallback: accept any non-empty action_completed result from the child
                    if child_result is None:
                        await cur.execute(
                            """
                            SELECT result FROM noetl.event_log
                            WHERE execution_id = %s
                              AND event_type = 'action_completed'
                              AND lower(status) IN ('completed','success')
                              AND result IS NOT NULL
                              AND result != '{}'
                              AND NOT (result::text LIKE '%%"skipped": true%%')
                              AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                            ORDER BY timestamp DESC
                            LIMIT 1
                            """,
                            (child_exec_id,)
                        )
                        row_any = await cur.fetchone()
                        if row_any:
                            try:
                                any_out = row_any[0] if isinstance(row_any, tuple) else row_any.get('result')
                                child_result = json.loads(any_out) if isinstance(any_out, str) else any_out
                                if isinstance(child_result, dict) and 'data' in child_result:
                                    child_result = child_result['data']
                                logger.info(f"PROACTIVE_COMPLETION_CHECK: Fallback accepted child {child_exec_id} result: {child_result}")
                            except Exception:
                                pass
                    
                    # Consider any non-empty result meaningful (playbook-agnostic)
                    def _is_meaningful(res: Any) -> bool:
                        if res is None:
                            return False
                        if isinstance(res, (list, str)):
                            return len(res) > 0
                        if isinstance(res, dict):
                            return len(res) > 0
                        return True

                    if child_result and _is_meaningful(child_result):
                        # Emit per-iteration 'result' event for the parent loop to aggregate
                        try:
                            event_service = get_event_service()
                            
                            # Get loop metadata from loop_iteration event if available
                            loop_metadata = {}
                            try:
                                await cur.execute(
                                    """
                                    SELECT loop_id, loop_name, iterator, current_index, current_item 
                                    FROM noetl.event_log
                                    WHERE execution_id = %s
                                      AND event_type = 'loop_iteration'
                                      AND node_name = %s
                                      AND context LIKE %s
                                    ORDER BY timestamp DESC
                                    LIMIT 1
                                    """,
                                    (parent_execution_id, parent_step, f'%"child_execution_id": "{child_exec_id}"%')
                                )
                                metadata_row = await cur.fetchone()
                                if metadata_row:
                                    if isinstance(metadata_row, tuple):
                                        loop_id, loop_name, iterator, current_index, current_item = metadata_row
                                    else:
                                        loop_id = metadata_row.get('loop_id')
                                        loop_name = metadata_row.get('loop_name')
                                        iterator = metadata_row.get('iterator')
                                        current_index = metadata_row.get('current_index')
                                        current_item = metadata_row.get('current_item')
                                    
                                    if loop_id:
                                        loop_metadata = {
                                            'loop_id': loop_id,
                                            'loop_name': loop_name,
                                            'iterator': iterator,
                                            'current_index': current_index,
                                            'current_item': current_item
                                        }
                            except Exception:
                                pass
                            
                            emit_data = {
                                'execution_id': parent_execution_id,
                                'event_type': 'result',
                                'status': 'COMPLETED',
                                'node_id': iter_node_id or f'{parent_execution_id}-step-X-iter-{child_exec_id}',
                                'node_name': parent_step,
                                'node_type': 'task',
                                'result': child_result,
                                'context': {
                                    'child_execution_id': child_exec_id,
                                    'parent_step': parent_step,
                                    'return_step': None
                                }
                            }
                            # Add loop metadata if available
                            emit_data.update(loop_metadata)
                            
                            # Idempotency guard: skip emit if a result for this child has already been recorded in parent
                            try:
                                await cur.execute(
                                    """
                                    SELECT COUNT(*) FROM noetl.event_log
                                    WHERE execution_id = %s
                                      AND event_type = 'result'
                                      AND node_name = %s
                                      AND context::text LIKE %s
                                    """,
                                    (parent_execution_id, parent_step, f'%"child_execution_id": "{child_exec_id}"%')
                                )
                                _cnt = await cur.fetchone()
                                already_emitted = bool(_cnt and int(_cnt[0]) > 0)
                            except Exception:
                                already_emitted = False
                            if not already_emitted:
                                await event_service.emit(emit_data)
                                logger.info(f"PROACTIVE_COMPLETION_CHECK: Emitted result for parent {parent_execution_id} step {parent_step} from child {child_exec_id} with result: {child_result} and loop metadata: {loop_metadata}")
                            else:
                                logger.debug(f"PROACTIVE_COMPLETION_CHECK: Skipping duplicate emit for child {child_exec_id} (already recorded)")
                        except Exception as e:
                            logger.error(f"PROACTIVE_COMPLETION_CHECK: Error emitting result event: {e}")
                    else:
                        logger.debug(f"PROACTIVE_COMPLETION_CHECK: No meaningful result found for child execution {child_exec_id}; will not emit mapping yet")
                        
    except Exception as e:
        logger.error(f"PROACTIVE_COMPLETION_CHECK: Error checking completed child executions: {e}")


async def check_distributed_loop_completion(execution_id: str, step_name: str) -> None:
    """
    Check if a distributed loop with the given step name has completed all its child executions.
    If so, perform aggregation and continue the workflow.
    """
    try:
        logger.info(f"DISTRIBUTED_COMPLETION: Checking if loop {step_name} in execution {execution_id} is complete")
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Check if all loop iterations have completed
                await cur.execute(
                    """
                    SELECT 
                        COUNT(*) as total_iterations,
                        COUNT(CASE WHEN el2.execution_id IS NOT NULL THEN 1 END) as completed_iterations
                    FROM noetl.event_log el1
                    LEFT JOIN noetl.event_log el2 ON 
                        el2.execution_id = (el1.context::json)->>'child_execution_id'
                        AND el2.event_type = 'execution_complete'
                        AND el2.status = 'COMPLETED'
                    WHERE el1.execution_id = %s
                      AND el1.event_type = 'loop_iteration'
                      AND el1.node_name = %s
                    """,
                    (execution_id, step_name)
                )
                
                result = await cur.fetchone()
                if not result:
                    logger.debug(f"DISTRIBUTED_COMPLETION: No loop iterations found for {step_name}")
                    return
                
                total_iterations, completed_iterations = result[0], result[1]
                logger.info(f"DISTRIBUTED_COMPLETION: Loop {step_name} has {completed_iterations}/{total_iterations} completed iterations")
                
                if completed_iterations < total_iterations:
                    logger.debug(f"DISTRIBUTED_COMPLETION: Loop {step_name} not yet complete")
                    return
                
                # All iterations complete - trigger loop completion processing
                logger.info(f"DISTRIBUTED_COMPLETION: All iterations complete for loop {step_name}, triggering completion processing")
                # The actual completion processing is handled by check_and_process_completed_loops
                
    except Exception as e:
        logger.error(f"DISTRIBUTED_COMPLETION: Error checking completion for {execution_id} step {step_name}: {e}")


async def _check_distributed_loop_completion(execution_id: str, step_name: str) -> None:
    """
    Check if a distributed loop with the given step name has completed all its child executions.
    If so, perform aggregation and continue the workflow.
    """
    try:
        logger.info(f"DISTRIBUTED_COMPLETION: Checking if loop {step_name} in execution {execution_id} is complete")
        
        dao = EventLog()
        expected_iterations = await dao.count_loop_iterations(execution_id, step_name)
        completed_iterations = await dao.count_completed_iterations_with_child(execution_id, step_name)
                
        logger.info(f"DISTRIBUTED_COMPLETION: Step {step_name} has {completed_iterations}/{expected_iterations} completed iterations")
        
        if expected_iterations > 0 and completed_iterations >= expected_iterations:
            # All iterations completed - aggregate results
            rows = await dao.fetch_action_completed_results_for_loop(execution_id, step_name)
            aggregated_results = []
            for val in rows:
                try:
                    result_data = json.loads(val) if isinstance(val, str) else val
                except Exception:
                    result_data = val
                aggregated_results.append(result_data)
            
            # Emit aggregated result
            from ..service import get_event_service
            event_service = get_event_service()
            await event_service.emit({
                'execution_id': execution_id,
                'event_type': 'action_completed',
                'status': 'COMPLETED',
                'node_name': step_name,
                'node_type': 'distributed_loop',
                'result': {
                    'results': aggregated_results,
                    'count': len(aggregated_results)
                },
                'context': {
                    'distributed_loop_completed': True,
                    'total_iterations': expected_iterations
                }
            })
            
            logger.info(f"DISTRIBUTED_COMPLETION: Completed distributed loop {step_name} with {len(aggregated_results)} aggregated results")
                    
    except Exception as e:
        logger.error(f"DISTRIBUTED_COMPLETION: Error checking completion for {execution_id} step {step_name}: {e}")