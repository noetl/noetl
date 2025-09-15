"""
Loop completion monitoring and processing.
Handles tracking of distributed loop executions and aggregation of results.
"""

import json
from typing import Any, Dict, List
from noetl.core.common import get_async_db_connection
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def check_and_process_completed_loops(parent_execution_id: str):
    """
    Check for completed loops and aggregate their results.
    Handles both tracking loop completion status and aggregating final results.
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
                
                from ..service import get_event_service
                
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
                    
                    await _process_loop_completion_status(
                        conn, cur, event_service, parent_execution_id, loop_step_name
                    )
                        
    except Exception as e:
        logger.error(f"LOOP_COMPLETION_CHECK: Error processing completed loops: {e}")


async def _process_loop_completion_status(conn, cur, event_service, parent_execution_id: str, loop_step_name: str):
    """Process the completion status of a loop and aggregate results if all iterations are complete."""
    
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
        return
    
    try:
        end_loop_context = json.loads(end_loop_row[0]) if isinstance(end_loop_row[0], str) else end_loop_row[0]
        child_executions_data = end_loop_context.get('child_executions', [])
        completed_count = end_loop_context.get('completed_count', 0)
        aggregated_results = end_loop_context.get('aggregated_results', [])
    except Exception:
        logger.error(f"LOOP_COMPLETION_CHECK: Error parsing end_loop context for {loop_step_name}")
        return
    
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
        child_result = await _get_child_execution_result(cur, child_exec_id)
        
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
        
        updated_children.append(child_data)
    
    # Step 4: Update end_loop tracking event
    if new_completed_count != completed_count:
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
        await _finalize_loop_completion(
            conn, cur, event_service, parent_execution_id, loop_step_name, 
            new_aggregated_results, child_executions_data
        )


async def _get_child_execution_result(cur, child_exec_id: str) -> Any:
    """Extract meaningful result from a completed child execution."""
    
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
            return child_result
        except Exception:
            logger.debug(f"LOOP_COMPLETION_CHECK: Failed to parse execution_complete result for child {child_exec_id}")
    
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
                logger.info(f"LOOP_COMPLETION_CHECK: Found step result from {step_name} in child {child_exec_id}: {step_result}")
                return step_result
        except Exception:
            logger.debug(f"LOOP_COMPLETION_CHECK: Failed to parse result from {step_name} in child {child_exec_id}")
            continue
    
    # Final fallback: accept any non-empty action_completed result from the child
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
            logger.info(f"LOOP_COMPLETION_CHECK: Fallback accepted child {child_exec_id} result: {any_res}")
            return any_res
        except Exception:
            pass
    
    return None


async def _finalize_loop_completion(conn, cur, event_service, parent_execution_id: str, 
                                  loop_step_name: str, new_aggregated_results: List[Dict], 
                                  child_executions_data: List[Dict]):
    """Finalize loop completion by emitting completion events and scheduling next steps."""
    
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
        return
    
    # Sort results by iteration index
    sorted_results = sorted(new_aggregated_results, key=lambda x: x.get('iteration_index', 0))
    final_results = [r['result'] for r in sorted_results]
    
    logger.info(f"LOOP_COMPLETION_CHECK: All children completed for {loop_step_name}: {len(child_executions_data)}/{len(child_executions_data)} total children")
    
    # All children completed -> emit a loop_completed marker and schedule aggregation job
    await _emit_loop_completion_events(event_service, parent_execution_id, loop_step_name, final_results)
    
    # After loop completion, enqueue aggregation and next steps
    await _schedule_post_loop_tasks(conn, cur, parent_execution_id, loop_step_name, final_results)


async def _emit_loop_completion_events(event_service, parent_execution_id: str, 
                                     loop_step_name: str, final_results: List):
    """Emit the completion events for a finished loop."""
    
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
    
    # Emit step_completed event after loop finishes
    try:
        await event_service.emit({
            'execution_id': parent_execution_id,
            'event_type': 'step_completed',
            'status': 'COMPLETED',
            'node_id': f"{parent_execution_id}:{loop_step_name}",
            'node_name': loop_step_name,
            'node_type': 'step',
            'result': {
                'data': final_results,
                'count': len(final_results)
            },
            'context': {
                'step_name': loop_step_name,
                'step_type': 'loop',
                'total_iterations': len(final_results)
            }
        })
        logger.info(f"LOOP_COMPLETION_CHECK: Emitted step_completed for {loop_step_name}")
    except Exception as e:
        logger.debug(f"LOOP_COMPLETION_CHECK: Failed to emit step_completed event: {e}", exc_info=True)
    
    logger.info(f"LOOP_COMPLETION_CHECK: Loop {loop_step_name} completed! Final aggregated results: {final_results}")


async def _schedule_post_loop_tasks(conn, cur, parent_execution_id: str, loop_step_name: str, final_results: List):
    """Schedule aggregation job and next workflow steps after loop completion."""
    
    # After loop completion, enqueue an aggregation job, then the next step(s)
    try:
        # Enqueue a single aggregation job if not already queued/leased/done
        await _enqueue_aggregation_job(conn, cur, parent_execution_id, loop_step_name)
        
        # After loop completion, enqueue the next step(s) following this loop step if defined
        await _enqueue_next_workflow_steps(conn, cur, parent_execution_id, loop_step_name)
        
    except Exception:
        logger.debug("LOOP_COMPLETION_CHECK: Failed to schedule post-loop tasks", exc_info=True)


async def _enqueue_aggregation_job(conn, cur, parent_execution_id: str, loop_step_name: str):
    """Enqueue an aggregation job for the completed loop."""
    
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


async def _enqueue_next_workflow_steps(conn, cur, parent_execution_id: str, loop_step_name: str):
    """Enqueue the next workflow steps after loop completion."""
    
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
        by_name = {}
        
        if playbook_path:
            try:
                from noetl.server.api.catalog import get_catalog_service
                catalog = get_catalog_service()
                entry = await catalog.fetch_entry(playbook_path, playbook_version or '')
                if entry and entry.get('content'):
                    import yaml as _yaml
                    pb = _yaml.safe_load(entry['content']) or {}
                    steps = pb.get('workflow') or pb.get('steps') or []
                    # Build by-name
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
            await _enqueue_next_step(conn, cur, parent_execution_id, next_step_name, next_with, by_name)
            
    except Exception:
        logger.debug("LOOP_COMPLETION_CHECK: Failed to enqueue next workflow steps", exc_info=True)


async def _enqueue_next_step(conn, cur, parent_execution_id: str, next_step_name: str, 
                           next_with: Dict, by_name: Dict, trigger_event_id: str | None = None):
    """Enqueue a specific next step in the workflow."""
    
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
                step_def = by_name.get(next_step_name) if by_name else None
            except Exception:
                step_def = None
                
            def _is_actionable(sd: Dict) -> bool:
                try:
                    t = str((sd or {}).get('type') or '').lower()
                    if not t:
                        return False
                    # Include 'save' so save steps run on workers
                    if t in {'http','python','duckdb','postgres','secrets','workbook','playbook','save'}:
                        if t == 'python':
                            return bool(sd.get('code') or sd.get('code_b64') or sd.get('code_base64'))
                        return True
                    return False
                except Exception:
                    return False

            if isinstance(step_def, dict) and _is_actionable(step_def):
                task_def = {
                    'name': next_step_name,
                    'type': step_def.get('type') or 'python',
                }
                for _fld in (
                    'task','code','command','commands','sql',
                    'url','endpoint','method','headers','params','data','payload',
                    'with','resource_path','content','path','loop','save'
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
            else:
                # Non-actionable next step: finalize control step immediately
                try:
                    from .broker import _finalize_result_step  # reuse helper via relative import path
                except Exception:
                    _finalize_result_step = None
                if _finalize_result_step and isinstance(step_def, dict):
                    try:
                        await _finalize_result_step(parent_execution_id, next_step_name, step_def, None, None)
                    except Exception:
                        logger.debug("LOOP_COMPLETION_CHECK: Failed to finalize non-actionable next step", exc_info=True)
                return
                        
            # Encode and enqueue
            encoded = _encode_task(task_def)
            # Load earliest workload context for this execution to provide rendering variables
            base_workload = {}
            try:
                await cur.execute(
                    """
                    SELECT context FROM noetl.event_log
                    WHERE execution_id = %s::bigint AND event_type IN ('execution_start','execution_started')
                    ORDER BY timestamp ASC LIMIT 1
                    """,
                    (parent_execution_id,)
                )
                _row = await cur.fetchone()
                if _row and _row[0]:
                    import json as _json
                    try:
                        _ctx0 = _json.loads(_row[0]) if isinstance(_row[0], str) else _row[0]
                        if isinstance(_ctx0, dict) and isinstance(_ctx0.get('workload'), dict):
                            base_workload = _ctx0.get('workload') or {}
                    except Exception:
                        base_workload = {}
            except Exception:
                base_workload = {}
            job_ctx = {
                'workload': base_workload,
                'step_name': next_step_name,
                'path': None,
                'version': 'latest'
            }
            try:
                if trigger_event_id:
                    job_ctx['_meta'] = {'parent_event_id': str(trigger_event_id)}
            except Exception:
                pass
            
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
            logger.info(f"LOOP_COMPLETION_CHECK: Enqueued next step '{next_step_name}' for execution {parent_execution_id}")
            
    except Exception:
        logger.debug(f"LOOP_COMPLETION_CHECK: Failed to enqueue next step {next_step_name}", exc_info=True)
