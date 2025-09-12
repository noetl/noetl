"""
Background processing functions for broker evaluation and loop completion.
"""

import json
import os
import asyncio
from typing import Any, Dict
from noetl.core.common import get_async_db_connection, get_snowflake_id_str, get_snowflake_id
from noetl.server.api.catalog import get_catalog_service
from noetl.core.logger import setup_logger
from noetl.server.api.event.event_log import EventLog

logger = setup_logger(__name__, include_location=True)


async def _populate_workflow_tables(cursor, execution_id: str, playbook_path: str, playbook: Dict[str, Any]) -> None:
    """
    Populate workflow, transition, and workbook tables for the given execution.
    
    Args:
        cursor: Database cursor
        execution_id: Execution ID 
        playbook_path: Path to the playbook
        playbook: Parsed playbook content
    """
    try:
        # Get workflow steps
        workflow_steps = playbook.get('workflow', []) or playbook.get('steps', [])
        if not workflow_steps:
            return
            
        # Insert workflow steps
        for step in workflow_steps:
            step_name = step.get('step') or step.get('name')
            if not step_name:
                continue
                
            step_id = step.get('id') or step_name
            description = step.get('description')
            await cursor.execute(
                """
                INSERT INTO noetl.workflow (execution_id, step_id, step_name, step_type, description, raw_config)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (execution_id, step_id) DO NOTHING
                """,
                (
                    execution_id,
                    step_id,
                    step_name,
                    step.get('type', 'unknown'),
                    description,
                    json.dumps(step)
                )
            )
            
            # Insert transitions for this step
            next_steps = step.get('next', [])
            if isinstance(next_steps, list):
                for next_item in next_steps:
                    if isinstance(next_item, dict):
                        next_step_name = next_item.get('step')
                        condition = next_item.get('when')
                    elif isinstance(next_item, str):
                        next_step_name = next_item
                        condition = None
                    else:
                        continue
                        
                    if next_step_name:
                        with_params = None
                        try:
                            # Persist 'with' parameters on the transition if provided
                            if isinstance(next_item, dict) and next_item.get('with') is not None:
                                with_params = json.dumps(next_item.get('with'))
                        except Exception:
                            with_params = None
                        # Ensure condition is non-null because it's part of the PK in schema
                        _cond = condition if (condition is not None and condition != 'null') else ''
                        await cursor.execute(
                            """
                            INSERT INTO noetl.transition (execution_id, from_step, to_step, condition, with_params)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (execution_id, from_step, to_step, condition) DO NOTHING
                            """,
                            (execution_id, step_name, next_step_name, _cond, with_params)
                        )
        
        # Insert workbook actions
        workbook_actions = playbook.get('workbook', [])
        for action in workbook_actions:
            action_name = action.get('name')
            if not action_name:
                continue
                
            task_id = action.get('id') or action_name
            await cursor.execute(
                """
                INSERT INTO noetl.workbook (execution_id, task_id, task_name, task_type, raw_config)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (execution_id, task_id) DO NOTHING
                """,
                (
                    execution_id,
                    task_id,
                    action_name,
                    action.get('type', 'unknown'),
                    json.dumps(action)
                )
            )
            
    except Exception as e:
        logger.error(f"Error populating workflow tables for {execution_id}: {e}")
        # Re-raise to allow outer logic to rollback aborted transaction before continuing
        raise


def _evaluate_broker_for_execution(execution_id: str):
    """Placeholder stub; real implementation assigned later in the file."""
    return None


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
            from .service import get_event_service
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
                
                from .service import get_event_service
                
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


async def check_and_process_completed_loops(parent_execution_id: str):
    """
    Comprehensive loop completion handler that works for any action type:
    1. Creates end_loop events to track all child executions for each loop
    2. Detects when all children complete and aggregates their results
    3. Emits final loop result events with aggregated data
    """
    try:
        logger.info(f"LOOP_COMPLETION_CHECK: Processing loop completion for execution {parent_execution_id}")
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Step 1: Find all loops that need processing (loops without end_loop events OR with TRACKING end_loop events)
                await cur.execute(
                    """
                    SELECT DISTINCT 
                        node_name as loop_step_name,
                        COUNT(*) as total_iterations
                    FROM noetl.event_log 
                    WHERE execution_id = %s 
                      AND event_type = 'loop_iteration'
                      AND (
                          node_name NOT IN (
                              SELECT DISTINCT node_name 
                              FROM noetl.event_log 
                              WHERE execution_id = %s 
                                AND event_type = 'end_loop'
                          )
                          OR node_name IN (
                              SELECT DISTINCT node_name 
                              FROM noetl.event_log 
                              WHERE execution_id = %s 
                                AND event_type = 'end_loop' 
                                AND status = 'TRACKING'
                          )
                      )
                    GROUP BY node_name
                    """,
                    (parent_execution_id, parent_execution_id, parent_execution_id)
                )
                active_loops = await cur.fetchall()
                
                from .service import get_event_service
                
                for loop_step_name, total_iterations in active_loops:
                    logger.info(f"LOOP_COMPLETION_CHECK: Processing loop {loop_step_name} with {total_iterations} iterations")
                    
                    # Initialize event service for this loop processing
                    event_service = get_event_service()
                    
                    # Get all child execution IDs for this loop from both loop_iteration and action_completed events
                    await cur.execute(
                        """
                        SELECT * FROM (
                            -- Get child executions from loop_iteration events
                            SELECT 
                                (context::json)->>'child_execution_id' as child_exec_id,
                                node_id as iter_node_id,
                                event_id as iter_event_id,
                                COALESCE((context::json)->>'index', '0') as iteration_index,
                                'loop_iteration' as source_event
                            FROM noetl.event_log 
                            WHERE execution_id = %s 
                              AND event_type = 'loop_iteration'
                              AND node_name = %s
                              AND context::text LIKE '%%child_execution_id%%'
                            
                            UNION ALL
                            
                            -- Get child executions from action_completed events (these contain the actual playbook results)
                            SELECT 
                                (context::json)->>'child_execution_id' as child_exec_id,
                                node_id as iter_node_id,
                                event_id as iter_event_id,
                                '0' as iteration_index,
                                'action_completed' as source_event
                            FROM noetl.event_log 
                            WHERE execution_id = %s 
                              AND event_type = 'action_completed'
                              AND node_name = %s
                              AND context::text LIKE '%%child_execution_id%%'
                        ) AS combined_results
                        ORDER BY source_event, CAST(iteration_index AS INTEGER)
                        """,
                        (parent_execution_id, loop_step_name, parent_execution_id, loop_step_name)
                    )
                    child_executions = await cur.fetchall()
                    
                    if not child_executions:
                        logger.debug(f"LOOP_COMPLETION_CHECK: No child executions found for loop {loop_step_name}")
                        continue
                    
                    # Step 2: Check if we need to create an end_loop tracking event
                    await cur.execute(
                        """
                        SELECT 1 FROM noetl.event_log 
                        WHERE execution_id = %s 
                          AND event_type = 'end_loop'
                          AND node_name = %s
                        """,
                        (parent_execution_id, loop_step_name)
                    )
                    end_loop_exists = await cur.fetchone() is not None
                    
                    if not end_loop_exists:
                        # Create end_loop tracking event - prioritize action_completed events as they contain real results
                        child_exec_data = []
                        seen_child_ids = set()
                        
                        for child_exec_id, iter_node_id, iter_event_id, iteration_index, source_event in child_executions:
                            if child_exec_id and child_exec_id not in seen_child_ids:
                                child_exec_data.append({
                                    'child_execution_id': child_exec_id,
                                    'iter_node_id': iter_node_id,
                                    'iter_event_id': iter_event_id,
                                    'iteration_index': int(iteration_index) if iteration_index else 0,
                                    'source_event': source_event,
                                    'completed': False
                                })
                                seen_child_ids.add(child_exec_id)
                        
                        await event_service.emit({
                            'execution_id': parent_execution_id,
                            'event_type': 'end_loop',
                            'node_name': loop_step_name,
                            'node_type': 'loop_tracker',
                            'status': 'TRACKING',
                            'context': {
                                'loop_step_name': loop_step_name,
                                'total_iterations': len(child_exec_data),
                                'child_executions': child_exec_data,
                                'completed_count': 0,
                                'aggregated_results': []
                            }
                        })
                        logger.info(f"LOOP_COMPLETION_CHECK: Created end_loop tracking event for {loop_step_name} with {len(child_exec_data)} children")
                        continue
                    
                    # Step 3: Check completion status and aggregate results
                    await cur.execute(
                        """
                        SELECT context FROM noetl.event_log 
                        WHERE execution_id = %s 
                          AND event_type = 'end_loop'
                          AND node_name = %s
                        ORDER BY timestamp DESC
                        LIMIT 1
                        """,
                        (parent_execution_id, loop_step_name)
                    )
                    end_loop_row = await cur.fetchone()
                    if not end_loop_row:
                        continue
                    
                    try:
                        end_loop_context = json.loads(end_loop_row[0]) if isinstance(end_loop_row[0], str) else end_loop_row[0]
                        child_executions_data = end_loop_context.get('child_executions', [])
                        completed_count = end_loop_context.get('completed_count', 0)
                        aggregated_results = end_loop_context.get('aggregated_results', [])
                    except Exception:
                        logger.error(f"LOOP_COMPLETION_CHECK: Error parsing end_loop context for {loop_step_name}")
                        continue
                    
                    # Check each child execution for completion and meaningful results
                    updated_children = []
                    new_completed_count = 0
                    new_aggregated_results = list(aggregated_results)
                    
                    for child_data in child_executions_data:
                        child_exec_id = child_data.get('child_execution_id')
                        was_completed = child_data.get('completed', False)
                        
                        if was_completed:
                            new_completed_count += 1
                            updated_children.append(child_data)
                            continue
                        
                        if not child_exec_id:
                            updated_children.append(child_data)
                            continue
                        
                        # Check if this child execution has completed and get its return value
                        child_result = None
                        logger.info(f"LOOP_COMPLETION_CHECK: Checking child execution {child_exec_id} for completion")
                        
                        # First check for execution_complete event which should have the final return value
                        await cur.execute(
                            """
                            SELECT result FROM noetl.event_log
                            WHERE execution_id = %s
                              AND event_type = 'execution_complete'
                              AND lower(status) IN ('completed','success')
                              AND result IS NOT NULL
                              AND result != '{}'
                            ORDER BY timestamp DESC
                            LIMIT 1
                            """,
                            (child_exec_id,)
                        )
                        exec_complete_row = await cur.fetchone()
                        
                        if exec_complete_row:
                            result_data = exec_complete_row[0] if isinstance(exec_complete_row, tuple) else exec_complete_row.get('result')
                            try:
                                child_result = json.loads(result_data) if isinstance(result_data, str) else result_data
                                logger.info(f"LOOP_COMPLETION_CHECK: Found execution_complete result for child {child_exec_id}: {child_result}")
                            except Exception:
                                logger.debug(f"LOOP_COMPLETION_CHECK: Failed to parse execution_complete result for child {child_exec_id}")
                        else:
                            # Fallback: Look for any meaningful step result from any completed action
                            await cur.execute(
                                """
                                SELECT node_name, result FROM noetl.event_log
                                WHERE execution_id = %s
                                  AND event_type = 'action_completed'
                                  AND lower(status) IN ('completed','success')
                                  AND result IS NOT NULL
                                  AND result != '{}'
                                  AND NOT (result::text LIKE '%%"skipped": true%%')
                                  AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                                ORDER BY timestamp DESC
                                """,
                                (child_exec_id,)
                            )
                            step_results = await cur.fetchall()
                            
                            for step_name, step_output in step_results:
                                try:
                                    step_result = json.loads(step_output) if isinstance(step_output, str) else step_output
                                    # Extract data if wrapped
                                    if isinstance(step_result, dict) and 'data' in step_result:
                                        step_result = step_result['data']
                                    if step_result:  # Any non-empty result
                                        child_result = step_result
                                        logger.info(f"LOOP_COMPLETION_CHECK: Found step result from {step_name} in child {child_exec_id}: {child_result}")
                                        break
                                except Exception:
                                    logger.debug(f"LOOP_COMPLETION_CHECK: Failed to parse result from {step_name} in child {child_exec_id}")
                                    continue
                        
                        if child_result:
                            # Mark as completed and add to aggregated results
                            child_data['completed'] = True
                            child_data['result'] = child_result
                            new_completed_count += 1
                            new_aggregated_results.append({
                                'iteration_index': child_data.get('iteration_index', 0),
                                'child_execution_id': child_exec_id,
                                'result': child_result
                            })
                            logger.info(f"LOOP_COMPLETION_CHECK: Child {child_exec_id} completed with result: {child_result}")
                        else:
                            # Fallback: accept any non-empty action_completed result from the child
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
                                    any_res = json.loads(any_out) if isinstance(any_out, str) else any_out
                                    if isinstance(any_res, dict) and 'data' in any_res:
                                        any_res = any_res['data']
                                    child_data['completed'] = True
                                    child_data['result'] = any_res
                                    new_completed_count += 1
                                    new_aggregated_results.append({
                                        'iteration_index': child_data.get('iteration_index', 0),
                                        'child_execution_id': child_exec_id,
                                        'result': any_res
                                    })
                                    logger.info(f"LOOP_COMPLETION_CHECK: Fallback accepted child {child_exec_id} result: {any_res}")
                                except Exception:
                                    pass
                        
                        updated_children.append(child_data)
                    
                    # Step 4: Update end_loop tracking event
                    if new_completed_count != completed_count:
                        event_service = get_event_service()
                        await event_service.emit({
                            'execution_id': parent_execution_id,
                            'event_type': 'end_loop',
                            'node_name': loop_step_name,
                            'node_type': 'loop_tracker',
                            'status': 'COMPLETED' if new_completed_count == len(child_executions_data) else 'TRACKING',
                            'context': {
                                'loop_step_name': loop_step_name,
                                'total_iterations': len(child_executions_data),
                                'child_executions': updated_children,
                                'completed_count': new_completed_count,
                                'aggregated_results': new_aggregated_results
                            }
                        })
                        logger.info(f"LOOP_COMPLETION_CHECK: Updated end_loop tracking for {loop_step_name}: {new_completed_count}/{len(child_executions_data)} completed")
                    
                    # Step 5: If all children completed, emit final loop result event (only once!)
                    if new_completed_count == len(child_executions_data):
                        # Check if we already emitted the final action_completed event for this specific loop completion
                        # to prevent infinite recursion, but allow legitimate workflow transition events
                        await cur.execute(
                            """
                            SELECT COUNT(*) as final_completion_count FROM noetl.event_log
                            WHERE execution_id = %s
                              AND event_type = 'action_completed'
                              AND node_name = %s
                              AND lower(status) = 'completed'
                              AND context::text LIKE '%%loop_completed%%'
                              AND context::text LIKE '%%true%%'
                            """,
                            (parent_execution_id, loop_step_name)
                        )
                        final_completion_row = await cur.fetchone()
                        final_completion_count = final_completion_row[0] if final_completion_row else 0
                        
                        if final_completion_count > 0:
                            logger.info(f"LOOP_COMPLETION_CHECK: Loop {loop_step_name} already has {final_completion_count} final completion events - skipping to prevent infinite recursion")
                            continue
                        
                        # Sort results by iteration index
                        sorted_results = sorted(new_aggregated_results, key=lambda x: x.get('iteration_index', 0))
                        final_results = [r['result'] for r in sorted_results]
                        
                        logger.info(f"LOOP_COMPLETION_CHECK: All children completed for {loop_step_name}: {new_completed_count}/{len(child_executions_data)} total children")
                        
                        # All children completed -> emit a loop_completed marker and schedule aggregation job; actual aggregation runs in worker
                        # Emit loop_completed marker first
                        loop_final_data = {
                            'execution_id': parent_execution_id,
                            'event_type': 'action_completed',
                            'node_name': loop_step_name,
                            'node_type': 'loop',
                            'status': 'COMPLETED',
                            'result': {
                                'data': {
                                    'results': final_results,
                                    'result': final_results,
                                    'count': len(final_results)
                                },
                                'results': final_results,
                                'result': final_results,
                                'count': len(final_results)
                            },
                            'context': {
                                'loop_completed': True,
                                'total_iterations': len(final_results),
                                'aggregated_results': final_results
                            },
                            # Add loop metadata for final aggregation event
                            'loop_id': f"{parent_execution_id}:{loop_step_name}",
                            'loop_name': loop_step_name
                        }
                        await event_service.emit(loop_final_data)
                        # Also emit a 'result' marker for easy querying
                        await event_service.emit({
                            'execution_id': parent_execution_id,
                            'event_type': 'result',
                            'node_name': loop_step_name,
                            'node_type': 'loop',
                            'status': 'COMPLETED',
                            'result': {
                                'data': {
                                    'results': final_results,
                                    'result': final_results,
                                    'count': len(final_results)
                                },
                                'results': final_results,
                                'result': final_results,
                                'count': len(final_results)
                            },
                            'context': {
                                'loop_completed': True,
                                'total_iterations': len(final_results),
                                'aggregated_results': final_results
                            },
                            # Add loop metadata
                            'loop_id': f"{parent_execution_id}:{loop_step_name}",
                            'loop_name': loop_step_name
                        })
                        logger.info(f"LOOP_COMPLETION_CHECK: Loop {loop_step_name} completed! Final aggregated results: {final_results}")
                        # After loop completion, enqueue an aggregation job, then the next step(s)
                        try:
                            # Enqueue a single aggregation job if not already queued/leased/done
                            try:
                                agg_node_id = f"{parent_execution_id}:{loop_step_name}:aggregate"
                                await cur.execute(
                                    """
                                    SELECT COUNT(*) FROM noetl.queue
                                    WHERE execution_id = %s AND node_id = %s AND status IN ('queued','leased')
                                    """,
                                    (parent_execution_id, agg_node_id)
                                )
                                _agg_cntrow = await cur.fetchone()
                                _agg_already = bool(_agg_cntrow and int(_agg_cntrow[0]) > 0)
                            except Exception:
                                _agg_already = False
                            if not _agg_already:
                                from noetl.server.api.broker.endpoint import encode_task_for_queue as _encode_task
                                # Collect iteration event IDs for context
                                iter_event_ids = []
                                try:
                                    await cur.execute(
                                        """
                                        SELECT event_id FROM noetl.event_log
                                        WHERE execution_id = %s AND event_type = 'loop_iteration' AND node_name = %s
                                        ORDER BY timestamp
                                        """,
                                        (parent_execution_id, loop_step_name)
                                    )
                                    _rows = await cur.fetchall()
                                    iter_event_ids = [r[0] if isinstance(r, tuple) else r.get('event_id') for r in _rows or []]
                                except Exception:
                                    iter_event_ids = []
                                agg_task = {
                                    'name': f"{loop_step_name}_aggregate",
                                    'type': 'result_aggregation',
                                    'with': {
                                        'loop_step': loop_step_name
                                    }
                                }
                                agg_encoded = _encode_task(agg_task)
                                agg_ctx = {
                                    'workload': {},
                                    'step_name': f"{loop_step_name}_aggregate",
                                    'path': None,
                                    'version': 'latest',
                                    '_meta': {
                                        'parent_execution_id': parent_execution_id,
                                        'loop_step': loop_step_name,
                                        'iteration_event_ids': iter_event_ids
                                    }
                                }
                                await cur.execute(
                                    """
                                    INSERT INTO noetl.queue (execution_id, node_id, action, context, priority, max_attempts, available_at)
                                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                                    RETURNING id
                                    """,
                                    (
                                        parent_execution_id,
                                        agg_node_id,
                                        json.dumps(agg_encoded),
                                        json.dumps(agg_ctx),
                                        5,
                                        3,
                                    )
                                )
                                await conn.commit()
                                logger.info(f"LOOP_COMPLETION_CHECK: Enqueued aggregation job for loop '{loop_step_name}' in execution {parent_execution_id}")
                        except Exception:
                            logger.debug("LOOP_COMPLETION_CHECK: Failed to enqueue aggregation job after loop", exc_info=True)
                        # After loop completion, enqueue the next step(s) following this loop step if defined
                        try:
                            # Determine playbook path/version from earliest event
                            playbook_path = None
                            playbook_version = None
                            try:
                                await cur.execute(
                                    """
                                    SELECT context, metadata FROM noetl.event_log
                                    WHERE execution_id = %s
                                    ORDER BY timestamp ASC
                                    LIMIT 1
                                    """,
                                    (parent_execution_id,)
                                )
                                _first = await cur.fetchone()
                                if _first:
                                    try:
                                        _ctx0 = json.loads(_first[0]) if _first and _first[0] else {}
                                    except Exception:
                                        _ctx0 = {}
                                    try:
                                        _meta0 = json.loads(_first[1]) if _first and _first[1] else {}
                                    except Exception:
                                        _meta0 = {}
                                    playbook_path = (_ctx0.get('path') if isinstance(_ctx0, dict) else None) or (_meta0.get('playbook_path') if isinstance(_meta0, dict) else None) or (_meta0.get('resource_path') if isinstance(_meta0, dict) else None)
                                    playbook_version = (_ctx0.get('version') if isinstance(_ctx0, dict) else None) or (_meta0.get('resource_version') if isinstance(_meta0, dict) else None)
                            except Exception:
                                pass

                            next_step_name = None
                            next_with = {}
                            if playbook_path:
                                try:
                                    catalog = get_catalog_service()
                                    entry = await catalog.fetch_entry(playbook_path, playbook_version or '')
                                    if entry and entry.get('content'):
                                        import yaml as _yaml
                                        pb = _yaml.safe_load(entry['content']) or {}
                                        steps = pb.get('workflow') or pb.get('steps') or []
                                        # Build by-name
                                        by_name = {}
                                        for s in steps:
                                            try:
                                                nm = s.get('step') or s.get('name')
                                                if nm:
                                                    by_name[str(nm)] = s
                                            except Exception:
                                                pass
                                        cur_step = by_name.get(loop_step_name)
                                        if isinstance(cur_step, dict):
                                            nxt_list = cur_step.get('next') or []
                                            if isinstance(nxt_list, list) and nxt_list:
                                                # choose first item without evaluating conditions
                                                choice = nxt_list[0]
                                                if isinstance(choice, dict):
                                                    next_step_name = choice.get('step') or choice.get('name')
                                                    if isinstance(choice.get('with'), dict):
                                                        next_with = choice.get('with') or {}
                                                else:
                                                    next_step_name = str(choice)
                                except Exception:
                                    logger.debug("LOOP_COMPLETION_CHECK: Failed to resolve next step after loop", exc_info=True)

                            if next_step_name:
                                try:
                                    # Avoid duplicate enqueues: check if a job for this next step is already pending
                                    await cur.execute(
                                        """
                                        SELECT COUNT(*) FROM noetl.queue
                                        WHERE execution_id = %s AND node_id = %s AND status IN ('queued','leased')
                                        """,
                                        (parent_execution_id, f"{parent_execution_id}:{next_step_name}")
                                    )
                                    _cntrow = await cur.fetchone()
                                    _already = bool(_cntrow and int(_cntrow[0]) > 0)
                                    if not _already:
                                        from noetl.server.api.broker.endpoint import encode_task_for_queue as _encode_task
                                        # Build task definition for next step
                                        task_def = {}
                                        try:
                                            step_def = by_name.get(next_step_name) if 'by_name' in locals() else None
                                        except Exception:
                                            step_def = None
                                        if isinstance(step_def, dict):
                                            task_def = {
                                                'name': next_step_name,
                                                'type': step_def.get('type') or 'python',
                                            }
                                            for _fld in (
                                                'task','code','command','commands','sql',
                                                'url','endpoint','method','headers','params','data','payload',
                                                'with','resource_path','content','path','loop'
                                            ):
                                                if step_def.get(_fld) is not None:
                                                    task_def[_fld] = step_def.get(_fld)
                                            # Merge 'with' from transition
                                            if next_with:
                                                try:
                                                    existing_with = task_def.get('with') or {}
                                                    if isinstance(existing_with, dict):
                                                        existing_with.update(next_with)
                                                        task_def['with'] = existing_with
                                                    else:
                                                        task_def['with'] = dict(next_with)
                                                except Exception:
                                                    task_def['with'] = next_with
                                        # Encode and enqueue
                                        encoded = _encode_task(task_def)
                                        job_ctx = {
                                            'workload': _ctx0.get('workload', {}) if isinstance(_ctx0, dict) else {},
                                            'step_name': next_step_name,
                                            'path': playbook_path,
                                            'version': playbook_version or 'latest',
                                        }
                                        await cur.execute(
                                            """
                                            INSERT INTO noetl.queue (execution_id, node_id, action, context, priority, max_attempts, available_at)
                                            VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                                            RETURNING id
                                            """,
                                            (
                                                parent_execution_id,
                                                f"{parent_execution_id}:{next_step_name}",
                                                json.dumps(encoded),
                                                json.dumps(job_ctx),
                                                5,
                                                3,
                                            )
                                        )
                                        await conn.commit()
                                        logger.info(f"LOOP_COMPLETION_CHECK: Enqueued next step '{next_step_name}' after loop {loop_step_name} for execution {parent_execution_id}")
                                except Exception:
                                    logger.debug("LOOP_COMPLETION_CHECK: Failed to enqueue next step after loop", exc_info=True)
                        except Exception:
                            logger.debug("LOOP_COMPLETION_CHECK: Post-loop next-step scheduling failed", exc_info=True)
                        # Emit an explicit loop_completed marker event too
                        try:
                            await event_service.emit({
                                'execution_id': parent_execution_id,
                                'event_type': 'loop_completed',
                                'node_name': loop_step_name,
                                'node_type': 'loop_control',
                                'status': 'COMPLETED',
                                'result': {
                                    'data': {
                                        'results': final_results,
                                        'result': final_results,
                                        'count': len(final_results)
                                    },
                                    'results': final_results,
                                    'result': final_results,
                                    'count': len(final_results)
                                },
                                'context': {
                                    'loop_completed': True,
                                    'total_iterations': len(final_results),
                                    'aggregated_results': final_results
                                },
                                # Add loop metadata
                                'loop_id': f"{parent_execution_id}:{loop_step_name}",
                                'loop_name': loop_step_name
                            })
                        except Exception:
                            logger.debug("LOOP_COMPLETION_CHECK: Failed to emit loop_completed marker", exc_info=True)
                        
    except Exception as e:
        print(f"!!! BROKER EVALUATION EXCEPTION: {e} !!!")
        logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Exception in broker evaluation: {e}")
        logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Unhandled exception", exc_info=True)
        return


# The large evaluate_broker_for_execution function will be implemented here
# For now, creating a minimal implementation to avoid circular imports
async def evaluate_broker_for_execution(
    execution_id: str,
    get_async_db_connection=get_async_db_connection,
    get_catalog_service=get_catalog_service,
    AsyncClientClass=None,
):
    """Server-side broker evaluator.

    - Builds execution context (workload + results) from event_log
    - Parses playbook and advances to the next actionable step
    - Evaluates step-level pass/when using server-side rendering (minimal for now)
    - Enqueues the first actionable step to the queue for workers
    """
    print(f"!!! BROKER EVALUATION CALLED FOR {execution_id} !!!")
    logger.info(f"=== EVALUATE_BROKER_FOR_EXECUTION: Starting for execution_id={execution_id} ===")
    try:
        print(f"!!! STEP 1: Inside try block for {execution_id} !!!")
        
        # Guard to prevent re-enqueuing post-loop steps per-item immediately
        await asyncio.sleep(0.2)
        
        # Return early if execution has failed
        dao = EventLog()
        rows = await dao.get_statuses(execution_id)
        for s in [str(x or '').lower() for x in rows]:
            if ('failed' in s) or ('error' in s):
                logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Found error status '{s}' for {execution_id}; stop scheduling")
                return

        # --------------------
        # INITIAL DISPATCH LOGIC (minimal): enqueue first actionable step if nothing queued/completed yet
        # --------------------
        try:
            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Starting initial dispatch for {execution_id}")
            import json as _json
            import yaml as _yaml
            from noetl.core.common import snowflake_id_to_int as _sf_to_int
            from noetl.server.api.broker import encode_task_for_queue as _encode_task
            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Imports successful for {execution_id}")

            async with get_async_db_connection() as _conn:
                logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Database connection established for {execution_id}")
                async with _conn.cursor() as _cur:
                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Cursor created for {execution_id}")
                    # If there is already a queued/leased job for this execution, skip initial dispatch
                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Checking for pending queue items for {execution_id}")
                    await _cur.execute(
                        """
                        SELECT COUNT(*) FROM noetl.queue
                        WHERE execution_id = %s AND status IN ('queued','leased')
                        """,
                        (execution_id,)
                    )
                    _qrow = await _cur.fetchone()
                    has_pending = bool(_qrow and int(_qrow[0]) > 0)
                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: has_pending={has_pending} for {execution_id}")

                    # If any action already completed for this execution (not just execution_start), skip initial dispatch
                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Checking for progress events for {execution_id}")
                    await _cur.execute(
                        """
                        SELECT COUNT(*) FROM noetl.event_log
                        WHERE execution_id = %s AND event_type IN ('action_completed','execution_completed')
                        """,
                        (execution_id,)
                    )
                    _erow = await _cur.fetchone()
                    has_progress = bool(_erow and int(_erow[0]) > 0)
                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: has_progress={has_progress} for {execution_id}")

                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Condition check complete - proceed with dispatch: {not has_pending and not has_progress} for {execution_id}")

                    if not has_pending and not has_progress:
                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Entering dispatch block for {execution_id}")
                        # Load workload context persisted at execution_start
                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Loading workload context for {execution_id}")
                        await _cur.execute("SELECT data FROM noetl.workload WHERE execution_id = %s", (execution_id,))
                        _wrow = await _cur.fetchone()
                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Workload query result: {_wrow} for {execution_id}")
                        _workload_ctx = {}
                        if _wrow and _wrow[0]:
                            try:
                                _workload_ctx = _json.loads(_wrow[0]) if isinstance(_wrow[0], str) else (_wrow[0] or {})
                            except Exception:
                                _workload_ctx = {}
                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Parsed workload context for {execution_id}: {_workload_ctx}")
                        _pb_path = (_workload_ctx or {}).get('path') or (_workload_ctx or {}).get('resource_path')
                        _pb_ver = (_workload_ctx or {}).get('version')
                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Extracted path={_pb_path}, version={_pb_ver} for {execution_id}")
                        # Fetch playbook from catalog
                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Getting catalog service for {execution_id}")
                        catalog = get_catalog_service()
                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Catalog service obtained for {execution_id}")
                        if not _pb_path:
                            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: No path found, attempting fallback for {execution_id}")
                            # Best-effort: derive from last execution_start event
                            try:
                                await _cur.execute(
                                    """
                                    SELECT context FROM noetl.event_log
                                    WHERE execution_id = %s AND event_type IN ('execution_start','execution_started')
                                    ORDER BY timestamp DESC LIMIT 1
                                    """,
                                    (execution_id,)
                                )
                                _er = await _cur.fetchone()
                                if _er and _er[0]:
                                    _c = _json.loads(_er[0]) if isinstance(_er[0], str) else (_er[0] or {})
                                    _pb_path = _c.get('path')
                                    _pb_ver = _pb_ver or _c.get('version')
                            except Exception:
                                pass
                        if _pb_path:
                            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Have path, proceeding with catalog fetch for {execution_id}: {_pb_path}")
                            if not _pb_ver:
                                try:
                                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Getting latest version for {_pb_path}")
                                    _pb_ver = await catalog.get_latest_version(_pb_path)
                                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Got latest version: {_pb_ver}")
                                except Exception as e:
                                    logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Failed to get latest version: {e}")
                                    _pb_ver = '0.1.0'
                            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Fetching entry from catalog: {_pb_path} v{_pb_ver}")
                            entry = await catalog.fetch_entry(_pb_path, _pb_ver)
                            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Catalog entry result: {entry is not None} for {execution_id}")
                            if entry and entry.get('content'):
                                logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Entry has content, parsing YAML for {execution_id}")
                                try:
                                    _pb = _yaml.safe_load(entry['content']) or {}
                                except Exception:
                                    _pb = {}
                                logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Parsed playbook for {execution_id}: {len(_pb)} keys")
                                _steps = (_pb.get('workflow') or _pb.get('steps') or [])
                                logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Found {len(_steps)} steps for {execution_id}")
                                
                                # Populate workflow, transition, and workbook tables for child execution
                                try:
                                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Populating workflow tables for {execution_id}")
                                    await _populate_workflow_tables(_cur, execution_id, _pb_path, _pb)
                                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Workflow tables populated for {execution_id}")
                                except Exception as e:
                                    # If population fails, the transaction may be left in aborted state; rollback before continuing
                                    try:
                                        logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: Failed to populate workflow tables for {execution_id}: {e}")
                                        await _conn.rollback()
                                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Transaction rolled back after workflow population error for {execution_id}")
                                    except Exception:
                                        logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Rollback after workflow population error failed", exc_info=True)
                                
                                # Build by-name index
                                _by_name = {}
                                for _s in _steps:
                                    try:
                                        _nm = _s.get('step') or _s.get('name')
                                        if _nm:
                                            _by_name[str(_nm)] = _s
                                    except Exception:
                                        continue
                                # Determine first actionable step from 'start' using conditional branches (when/then/else)
                                _start = _by_name.get('start') or next((s for s in _steps if (s.get('step') == 'start')), None)
                                _next_step_name = None
                                _next_with = {}
                                if _start:
                                    _nxt_list = _start.get('next') or []
                                    if isinstance(_nxt_list, list) and _nxt_list:
                                        try:
                                            # Build minimal Jinja environment for evaluating conditions
                                            from jinja2 import Environment, StrictUndefined
                                            from noetl.core.dsl.render import render_template
                                            jenv = Environment(undefined=StrictUndefined)
                                            # Prepare context for evaluation
                                            _ctx_for_when = {
                                                'workload': (_workload_ctx.get('workload') if isinstance(_workload_ctx, dict) else None) or {},
                                            }
                                            chosen = None
                                            for _entry in _nxt_list:
                                                if not isinstance(_entry, dict):
                                                    # simple form: {step: 'name'} or string
                                                    if isinstance(_entry, str):
                                                        chosen = {'step': _entry}
                                                    else:
                                                        chosen = _entry
                                                    break
                                                _when_expr = _entry.get('when')
                                                _then = _entry.get('then')
                                                _else = _entry.get('else')
                                                matched = False
                                                if _when_expr is not None:
                                                    try:
                                                        res = render_template(jenv, str(_when_expr), _ctx_for_when)
                                                        matched = bool(res)
                                                    except Exception:
                                                        matched = False
                                                else:
                                                    # No condition means default branch
                                                    matched = True
                                                if matched:
                                                    if isinstance(_then, list) and _then:
                                                        chosen = _then[0]
                                                    elif isinstance(_then, dict):
                                                        chosen = _then
                                                    elif _entry.get('step'):
                                                        chosen = _entry
                                                    else:
                                                        # fallback to first element
                                                        chosen = _entry
                                                    break
                                            if chosen is None and isinstance(_else, (list, dict)):
                                                # Pick from top-level else if defined (rare)
                                                chosen = _else[0] if isinstance(_else, list) and _else else (_else or None)
                                            if chosen:
                                                _next_step_name = (chosen.get('step') if isinstance(chosen, dict) else None) or (chosen.get('name') if isinstance(chosen, dict) else None) or (str(chosen) if isinstance(chosen, str) else None)
                                                _nw = (chosen.get('with') if isinstance(chosen, dict) else {}) or {}
                                                if isinstance(_nw, dict):
                                                    _next_with = _nw
                                        except Exception:
                                            # Fallback to previous naive behavior
                                            _first = _nxt_list[0] or {}
                                            _next_step_name = _first.get('step') or _first.get('name') or (str(_first) if isinstance(_first, str) else None)
                                            _nw = _first.get('with') if isinstance(_first, dict) else {}
                                            if isinstance(_nw, dict):
                                                _next_with = _nw
                                if _next_step_name and _next_step_name in _by_name:
                                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Creating task for step '{_next_step_name}' in execution {execution_id}")
                                    _def = _by_name[_next_step_name]
                                    _task = {
                                        'name': _next_step_name,
                                        'type': _def.get('type') or 'python',
                                    }
                                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Task base config: {_task}")
                                    # Copy key fields into task config for worker
                                    for _fld in (
                                        'task','code','command','commands','sql',
                                        'url','endpoint','method','headers','params','data','payload',
                                        'with','resource_path','content','path','loop'
                                    ):
                                        if _def.get(_fld) is not None:
                                            _task[_fld] = _def.get(_fld)
                                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Task after field copy: {_task}")
                                    # Merge 'with' from start->next transition into task config so workers receive kwargs
                                    if _next_with:
                                        try:
                                            existing_with = _task.get('with') or {}
                                            if isinstance(existing_with, dict):
                                                merged_with = {**existing_with, **_next_with}
                                            else:
                                                # If step.with is not a dict, prefer transition with
                                                merged_with = dict(_next_with)
                                            _task['with'] = merged_with
                                        except Exception:
                                            _task['with'] = _next_with
                                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Task after with merge: {_task}")

                                    # Determine if this step should be distributed over a loop
                                    _loop_cfg = (_def.get('loop') or {}) if isinstance(_def.get('loop'), dict) else {}
                                    _do_distribute = bool(_loop_cfg.get('distribution'))

                                    if _do_distribute:
                                        try:
                                            from noetl.core.dsl.render import render_template as _render
                                            from jinja2 import Environment, StrictUndefined
                                            _jenv = jenv if 'jenv' in locals() else Environment(undefined=StrictUndefined)

                                            _iterator = _loop_cfg.get('iterator') or 'item'
                                            _items_tmpl = _loop_cfg.get('in')
                                            _items_ctx = {
                                                'workload': (_workload_ctx.get('workload') if isinstance(_workload_ctx, dict) else None) or {}
                                            }
                                            # Include variables passed via 'with' from previous step
                                            if _next_with:
                                                # Render the _next_with templates first to resolve template strings like "{{ workload.cities }}"
                                                try:
                                                    rendered_next_with = _render(_jenv, _next_with, _items_ctx)
                                                    if isinstance(rendered_next_with, dict):
                                                        _items_ctx.update(rendered_next_with)
                                                    else:
                                                        _items_ctx.update(_next_with)
                                                except Exception:
                                                    logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to render _next_with; using raw values", exc_info=True)
                                                    _items_ctx.update(_next_with)
                                            _items = []
                                            try:
                                                _rendered_items = _render(_jenv, _items_tmpl, _items_ctx)
                                                if isinstance(_rendered_items, list):
                                                    _items = _rendered_items
                                                elif _rendered_items is not None:
                                                    _items = [_rendered_items]
                                            except Exception:
                                                logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to render loop items; defaulting to empty list", exc_info=True)
                                                _items = []

                                            _count = len(_items)
                                            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Distributing step '{_next_step_name}' over {_count} items (iterator={_iterator}) for execution {execution_id}")

                                            # For distributed jobs, we remove the loop config from the task passed to workers
                                            _task_dist = dict(_task)
                                            try:
                                                _task_dist.pop('loop', None)
                                            except Exception:
                                                pass
                                            _encoded_task = _encode_task(_task_dist)

                                            for _idx, _item in enumerate(_items):
                                                _ctx = {
                                                    'workload': (_workload_ctx.get('workload') if isinstance(_workload_ctx, dict) else None) or {},
                                                    'step_name': _next_step_name,
                                                    'path': _pb_path,
                                                    'version': _pb_ver or 'latest',
                                                    _iterator: _item,
                                                    '_loop': {
                                                        'loop_id': f"{execution_id}:{_next_step_name}",
                                                        'loop_name': _next_step_name,
                                                        'iterator': _iterator,
                                                        'current_index': _idx,
                                                        'current_item': _item,
                                                        'items_count': _count,
                                                    },
                                                }
                                                if _next_with:
                                                    try:
                                                        _ctx.update(_next_with)
                                                    except Exception:
                                                        pass

                                                # Emit a loop_iteration event per item and chain subsequent action events to it
                                                try:
                                                    # Idempotency: do not emit duplicate loop_iteration for same index
                                                    await _cur.execute(
                                                        """
                                                        SELECT COUNT(*) FROM noetl.event_log
                                                        WHERE execution_id = %s
                                                          AND event_type = 'loop_iteration'
                                                          AND node_name = %s
                                                          AND context::json->>'index' = %s
                                                        """,
                                                        (execution_id, _next_step_name, str(_idx))
                                                    )
                                                    _row = await _cur.fetchone()
                                                    _exists = bool(_row and int(_row[0]) > 0)
                                                    if not _exists:
                                                        from .service import get_event_service as _get_es
                                                        _es = _get_es()
                                                        _iter_event_id = get_snowflake_id_str()
                                                        await _es.emit({
                                                            'execution_id': execution_id,
                                                            'event_type': 'loop_iteration',
                                                            'status': 'RUNNING',
                                                            'node_id': f"{execution_id}:{_next_step_name}:{_idx}",
                                                            'node_name': _next_step_name,
                                                            'node_type': 'loop',
                                                            'event_id': _iter_event_id,
                                                            'context': {
                                                                'index': _idx,
                                                                'item': _item
                                                            },
                                                            'loop_id': f"{execution_id}:{_next_step_name}",
                                                            'loop_name': _next_step_name,
                                                            'iterator': _iterator,
                                                            'current_index': _idx,
                                                            'current_item': _item,
                                                        })
                                                        # Attach parent_event_id for worker to chain events correctly
                                                        _ctx['_meta'] = {'parent_event_id': _iter_event_id}
                                                    else:
                                                        logger.debug(f"EVALUATE_BROKER_FOR_EXECUTION: loop_iteration already exists for {execution_id}:{_next_step_name} index {_idx}; skipping emit")
                                                except Exception:
                                                    logger.debug('EVALUATE_BROKER_FOR_EXECUTION: Failed to emit loop_iteration event', exc_info=True)

                                                try:
                                                    await _cur.execute(
                                                        """
                                                        INSERT INTO noetl.queue (execution_id, node_id, action, context, priority, max_attempts, available_at)
                                                        VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                                                        RETURNING id
                                                        """,
                                                        (
                                                            _sf_to_int(execution_id),
                                                            f"{execution_id}:{_next_step_name}:{_idx}",
                                                            _json.dumps(_encoded_task),
                                                            _json.dumps(_ctx),
                                                            5,
                                                            3,
                                                        )
                                                    )
                                                except Exception as e:
                                                    logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Queue insert failed for distributed item {_idx} of step '{_next_step_name}': {e}")
                                            try:
                                                await _conn.commit()
                                            except Exception as e:
                                                logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Commit failed for distributed step '{_next_step_name}': {e}")
                                            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Enqueued {_count} distributed jobs for step '{_next_step_name}' in execution {execution_id}")
                                        except Exception:
                                            logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Distribution handling failed; falling back to single job", exc_info=True)
                                            _do_distribute = False

                                    if not _do_distribute:
                                        # Non-distributed path: enqueue a single job
                                        _ctx = {
                                            'workload': (_workload_ctx.get('workload') if isinstance(_workload_ctx, dict) else None) or {},
                                            'step_name': _next_step_name,
                                            'path': _pb_path,
                                            'version': _pb_ver or 'latest',
                                        }
                                        if _next_with:
                                            _ctx.update(_next_with)
                                        # Encode task payload for safe transport
                                        _encoded = _encode_task(_task)
                                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Encoded task: {_encoded}")
                                        try:
                                            await _cur.execute(
                                                """
                                                INSERT INTO noetl.queue (execution_id, node_id, action, context, priority, max_attempts, available_at)
                                                VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                                                RETURNING id
                                                """,
                                                (
                                                    _sf_to_int(execution_id),
                                                    f"{execution_id}:{_next_step_name}",
                                                    _json.dumps(_encoded),
                                                    _json.dumps(_ctx),
                                                    5,
                                                    3,
                                                )
                                            )
                                            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Queue insert successful for step '{_next_step_name}'")
                                        except Exception as e:
                                            logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Queue insert failed for step '{_next_step_name}': {e}")
                                        try:
                                            await _conn.commit()
                                            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Commit successful for step '{_next_step_name}'")
                                        except Exception as e:
                                            logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Commit failed for step '{_next_step_name}': {e}")
                                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Enqueued first step '{_next_step_name}' for execution {execution_id}")
                                else:
                                    logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: Step '{_next_step_name}' not found in by_name index or step name is None")
        except Exception as e:
            logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Initial dispatch failed with exception: {e}")
            logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Initial dispatch failed", exc_info=True)

        # PROACTIVE COMPLETION HANDLER: Check for completed child executions and process their results
        await check_and_process_completed_child_executions(execution_id)
        
        # LOOP COMPLETION HANDLER: Check for completed loops and emit end_loop events
        await check_and_process_completed_loops(execution_id)

        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Basic broker evaluation completed for {execution_id}")
        
    except Exception as e:
        print(f"!!! BROKER EVALUATION EXCEPTION: {e} !!!")
        logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Exception in broker evaluation: {e}")
        logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Unhandled exception", exc_info=True)
        return
