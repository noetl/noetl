"""
Broker execution and workflow coordination.
Handles server-side workflow evaluation, step routing, and task enqueueing.
"""

import asyncio
import json
import yaml
from noetl.core.common import get_async_db_connection, snowflake_id_to_int
from noetl.core.logger import setup_logger
from noetl.server.api.event.event_log import EventLog
from .workflow import populate_workflow_tables
from ..service import get_event_service

logger = setup_logger(__name__, include_location=True)


async def evaluate_broker_for_execution(
    execution_id: str,
    get_async_db_connection=get_async_db_connection,
    get_catalog_service=None,
    AsyncClientClass=None,
    trigger_event_id: str | None = None,
):
    """Server-side broker evaluator.

    - Builds execution context (workload + results) from event
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

        # INITIAL DISPATCH LOGIC: enqueue first actionable step if nothing queued/completed yet
        await _handle_initial_dispatch(execution_id, get_async_db_connection, trigger_event_id)

        # PROACTIVE COMPLETION HANDLERS
        from .child_executions import check_and_process_completed_child_executions
        from .loop_completion import check_and_process_completed_loops, ensure_direct_loops_finalized
        
        # PROACTIVE COMPLETION HANDLER: Check for completed child executions and process their results
        await check_and_process_completed_child_executions(execution_id)
        
        # LOOP COMPLETION HANDLER: Check for completed loops and emit end_loop events
        await check_and_process_completed_loops(execution_id)
        # Also proactively finalize direct (non-child) loops using per-iteration results
        await ensure_direct_loops_finalized(execution_id)

        # NON-LOOP PROGRESSION: Advance workflow for completed non-loop steps
        await _advance_non_loop_steps(execution_id, trigger_event_id)

        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Basic broker evaluation completed for {execution_id}")
        
    except Exception as e:
        print(f"!!! BROKER EVALUATION EXCEPTION: {e} !!!")
        logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Exception in broker evaluation: {e}")
        logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Unhandled exception", exc_info=True)
        return


def _evaluate_broker_for_execution(execution_id: str):
    """Legacy sync wrapper for evaluate_broker_for_execution - use async version instead."""
    import asyncio
    return asyncio.create_task(evaluate_broker_for_execution(execution_id))


async def _handle_initial_dispatch(execution_id: str, get_async_db_connection, trigger_event_id: str | None = None):
    """Handle initial workflow dispatch if no progress has been made."""
    
    try:
        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Starting initial dispatch for {execution_id}")
        
        from noetl.server.api.broker import encode_task_for_queue
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Check if there is already a queued/leased job for this execution
                await cur.execute(
                    """
                    SELECT COUNT(*) FROM noetl.queue
                    WHERE execution_id = %s AND status IN ('queued','leased')
                    """,
                    (execution_id,)
                )
                qrow = await cur.fetchone()
                has_pending = bool(qrow and int(qrow[0]) > 0)
                
                # Check if any action already completed for this execution
                await cur.execute(
                    """
                    SELECT COUNT(*) FROM noetl.event
                    WHERE execution_id = %s AND event_type IN ('action_completed','execution_completed')
                    """,
                    (execution_id,)
                )
                erow = await cur.fetchone()
                has_progress = bool(erow and int(erow[0]) > 0)
                
                logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: has_pending={has_pending}, has_progress={has_progress} for {execution_id}")
                
                if not has_pending and not has_progress:
                    # Load workload context
                    await cur.execute("SELECT data FROM noetl.workload WHERE execution_id = %s", (execution_id,))
                    wrow = await cur.fetchone()
                    workload_ctx = {}
                    if wrow and wrow[0]:
                        try:
                            workload_ctx = json.loads(wrow[0]) if isinstance(wrow[0], str) else (wrow[0] or {})
                        except Exception:
                            workload_ctx = {}
                    
                    pb_path = (workload_ctx or {}).get('path') or (workload_ctx or {}).get('resource_path')
                    pb_ver = (workload_ctx or {}).get('version')
                    
                    if not pb_path:
                        # Try to get path from execution_start event
                        await cur.execute(
                            """
                            SELECT context FROM noetl.event
                            WHERE execution_id = %s AND event_type IN ('execution_start','execution_started')
                            ORDER BY created_at DESC LIMIT 1
                            """,
                            (execution_id,)
                        )
                        er = await cur.fetchone()
                        if er and er[0]:
                            try:
                                c = json.loads(er[0]) if isinstance(er[0], str) else (er[0] or {})
                                pb_path = c.get('path')
                                pb_ver = pb_ver or c.get('version')
                            except Exception:
                                pass
                    
                    if pb_path:
                        # Get catalog service and fetch playbook
                        from noetl.server.api.catalog import get_catalog_service
                        catalog = get_catalog_service()
                        
                        if not pb_ver:
                            try:
                                pb_ver = await catalog.get_latest_version(pb_path)
                            except Exception:
                                pb_ver = '0.1.0'
                        
                        entry = await catalog.fetch_entry(pb_path, pb_ver)
                        if entry and entry.get('content'):
                            try:
                                pb = yaml.safe_load(entry['content']) or {}
                            except Exception:
                                pb = {}
                            
                            steps = pb.get('workflow') or pb.get('steps') or []
                            
                            # Populate workflow tables
                            try:
                                await populate_workflow_tables(cur, execution_id, pb_path, pb)
                            except Exception as e:
                                try:
                                    await conn.rollback()
                                except Exception:
                                    pass
                                logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: Failed to populate workflow tables: {e}")
                            
                            # Build by-name index and find first step
                            by_name = {}
                            for s in steps:
                                try:
                                    nm = s.get('step') or s.get('name')
                                    if nm:
                                        by_name[str(nm)] = s
                                except Exception:
                                    continue
                            
                            # Find 'start' step and determine first actionable step
                            start_step = by_name.get('start') or next((s for s in steps if (s.get('step') == 'start')), None)
                            next_step_name = None
                            next_with = {}
                            
                            if start_step:
                                # Normalize start step: ensure it has type 'start' if no type specified
                                # This makes it explicit that it's a control flow router
                                if not start_step.get('type'):
                                    start_step['type'] = 'start'
                                
                                # Start step is ALWAYS a router, never actionable
                                # Even if someone incorrectly adds an action type, we treat it as a router
                                # Find next actionable step from start's next field
                                nxt_list = start_step.get('next') or []
                                if isinstance(nxt_list, list) and nxt_list:
                                        # Simple logic: take first item for now
                                        first = nxt_list[0] or {}
                                        if isinstance(first, str):
                                            next_step_name = first
                                        elif isinstance(first, dict):
                                            next_step_name = first.get('step') or first.get('name')
                                            # Build transition payload with precedence: input > payload > with > data
                                            merged = {}
                                            try:
                                                w = first.get('with') if isinstance(first.get('with'), dict) else None
                                                if w:
                                                    merged.update(w)
                                            except Exception:
                                                pass
                                            try:
                                                p = first.get('payload') if isinstance(first.get('payload'), dict) else None
                                                if p:
                                                    merged.update(p)
                                            except Exception:
                                                pass
                                            try:
                                                i = first.get('input') if isinstance(first.get('input'), dict) else None
                                                if i:
                                                    merged.update(i)
                                            except Exception:
                                                pass
                                            try:
                                                # IMPORTANT: Also check for 'data' attribute in next step transition
                                                d = first.get('data') if isinstance(first.get('data'), dict) else None
                                                if d:
                                                    merged['data'] = d
                                            except Exception:
                                                pass
                                            next_with = merged
                            
                            if next_step_name and next_step_name in by_name:
                                step_def = by_name[next_step_name]
                                # If step is not actionable (e.g., end with only result), finalize execution
                                if not _is_actionable_step(step_def):
                                    try:
                                        await _finalize_result_step(execution_id, next_step_name, step_def, pb_path, pb_ver)
                                    except Exception:
                                        logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to finalize non-actionable step", exc_info=True)
                                    return
                                # Build task for actionable step
                                step_type = step_def.get('type') or 'python'
                                
                                # If step has a save block but type is not 'save', treat it as a save task
                                # This ensures save blocks are handled by the save plugin
                                if step_def.get('save') and step_type not in {'save', 'http', 'python', 'duckdb', 'postgres', 'secrets', 'workbook', 'playbook', 'iterator'}:
                                    step_type = 'save'
                                
                                task = {
                                    'name': next_step_name,
                                    'type': step_type,
                                }
                                for fld in (
                                    'task','run','code','command','commands','sql',
                                    'url','endpoint','method','headers','params',
                                    # iterator fields
                                    'collection','element','mode','concurrency','enumerate','where','limit','chunk','order_by',
                                    # unified payload fields (prefer input/payload over legacy with later)
                                    'input','payload','with','auth',
                                    'data',  # some steps embed data payloads directly
                                    'resource_path','content','path','loop','save','credential','credentials',
                                    # retry configuration
                                    'retry'
                                ):
                                    if step_def.get(fld) is not None:
                                        task[fld] = step_def.get(fld)
                                # Merge transition payload: support new data overlay and legacy input/payload/with
                                if next_with:
                                    try:
                                        # If next_with carries a 'data' overlay, apply over step's own data
                                        nx_data = next_with.get('data') if isinstance(next_with, dict) else None
                                        try:
                                            if isinstance(nx_data, dict):
                                                base_data = {}
                                                try:
                                                    if isinstance(task.get('data'), dict):
                                                        base_data.update(task['data'])
                                                except Exception:
                                                    pass
                                                base_data.update(nx_data)  # transition wins
                                                task['data'] = base_data
                                        except Exception:
                                            pass
                                        # Maintain legacy compatibility by building 'input' from with/payload/input
                                        existing_with = task.get('with') if isinstance(task.get('with'), dict) else {}
                                        merged_with = {**existing_with, **({k: v for k, v in next_with.items() if k != 'data'})}
                                        if merged_with:
                                            task['with'] = merged_with

                                        base = {}
                                        w = task.get('with') if isinstance(task.get('with'), dict) else None
                                        if w:
                                            base.update(w)
                                        p = task.get('payload') if isinstance(task.get('payload'), dict) else None
                                        if p:
                                            base.update(p)
                                        i = task.get('input') if isinstance(task.get('input'), dict) else None
                                        if i:
                                            base.update(i)
                                        if base:
                                            task['input'] = base
                                    except Exception:
                                        task['with'] = {k: v for k, v in (next_with or {}).items() if k != 'data'}

                                # Normalize aliases to data and loop->iterator early
                                try:
                                    from noetl.core.dsl.normalize import normalize_step as _normalize_step
                                    task = _normalize_step(task)
                                except Exception:
                                    pass
                                # Check if this step has a loop
                                loop_cfg = task.get('loop') or {}
                                has_loop = bool(loop_cfg.get('in'))
                                if has_loop:
                                    # Legacy loop support removed — require iterator step usage.
                                    logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Step '{next_step_name}' uses legacy 'loop' config; wrap the nested action in a 'type: iterator' step with 'collection' and 'element'")
                                    try:
                                        await cur.execute(
                                            """
                                            SELECT 1 FROM noetl.event
                                            WHERE execution_id = %s AND event_type = 'loop_iteration' AND node_name = %s
                                            LIMIT 1
                                            """,
                                            (execution_id, next_step_name)
                                        )
                                        if await cur.fetchone():
                                            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Loop '{next_step_name}' already initialized; skipping duplicate setup")
                                        else:
                                            # Emit a step_started event for loop step (marker for UI/control), only if not already emitted
                                            try:
                                                await cur.execute(
                                                    """
                                                    SELECT 1 FROM noetl.event
                                                    WHERE execution_id = %s AND node_name = %s AND event_type = 'step_started'
                                                    LIMIT 1
                                                    """,
                                                    (execution_id, next_step_name)
                                                )
                                                exists = await cur.fetchone() is not None
                                            except Exception:
                                                exists = False
                                            if not exists:
                                                try:
                                                    await get_event_service().emit({
                                                        'execution_id': execution_id,
                                                        'event_type': 'step_started',
                                                        'node_name': next_step_name,
                                                        'node_type': 'step',
                                                        'status': 'RUNNING',
                                                        'context': {
                                                            'path': pb_path,
                                                            'version': pb_ver or 'latest',
                                                            'step_name': next_step_name,
                                                        }
                                                    })
                                                except Exception:
                                                    logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to emit step_started for loop step", exc_info=True)
                                            # Loop processing: expand items and create individual tasks
                                            await _handle_loop_step(cur, conn, execution_id, next_step_name, task, loop_cfg, pb_path, pb_ver, workload_ctx, next_with, trigger_event_id)
                                    except Exception:
                                        logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Loop initialization idempotency check failed", exc_info=True)
                                else:
                                    # Non-loop step: single task
                                    # Create execution context
                                    ctx = {
                                        'workload': (workload_ctx.get('workload') if isinstance(workload_ctx, dict) else None) or {},
                                        'step_name': next_step_name,
                                        'path': pb_path,
                                        'version': pb_ver or 'latest',
                                    }
                                    if next_with:
                                        ctx.update(next_with)
                                    # Attach trigger metadata for worker lineage
                                    try:
                                        if trigger_event_id:
                                            ctx['_meta'] = {'parent_event_id': str(trigger_event_id)}
                                    except Exception:
                                        pass
                                    
                                    # Emit a step_started event for this non-loop step (only once)
                                    try:
                                        await cur.execute(
                                            """
                                            SELECT 1 FROM noetl.event
                                            WHERE execution_id = %s AND node_name = %s AND event_type = 'step_started'
                                            LIMIT 1
                                            """,
                                            (execution_id, next_step_name)
                                        )
                                        exists = await cur.fetchone() is not None
                                    except Exception:
                                        exists = False
                                    if not exists:
                                        try:
                                            await get_event_service().emit({
                                                'execution_id': execution_id,
                                                'event_type': 'step_started',
                                                'node_name': next_step_name,
                                                'node_type': 'step',
                                                'status': 'RUNNING',
                                                'context': ctx
                                            })
                                        except Exception:
                                            logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to emit step_started for non-loop step", exc_info=True)

                                    # Debug visibility: log keys for iterator tasks
                                    try:
                                        if (task.get('type') or '').lower() == 'iterator':
                                            logger.debug(f"EVALUATE_BROKER_FOR_EXECUTION: iterator step '{next_step_name}' task keys={list(task.keys())} collection={task.get('collection')} element={task.get('element')}")
                                    except Exception:
                                        pass

                                    # Encode and enqueue task
                                    encoded = encode_task_for_queue(task)
                                    
                                    # Extract max_attempts from retry config
                                    max_attempts = 3  # default
                                    retry_config = task.get('retry')
                                    if isinstance(retry_config, bool):
                                        max_attempts = 3 if retry_config else 1
                                    elif isinstance(retry_config, int):
                                        max_attempts = retry_config
                                    elif isinstance(retry_config, dict):
                                        max_attempts = retry_config.get('max_attempts', 3)
                                    
                                    # Get catalog_id from execution's first event
                                    await cur.execute("SELECT catalog_id FROM noetl.event WHERE execution_id = %s ORDER BY created_at LIMIT 1", (snowflake_id_to_int(execution_id),))
                                    catalog_row = await cur.fetchone()
                                    if not catalog_row:
                                        raise ValueError(f"No catalog_id found for execution {execution_id}")
                                    catalog_id = catalog_row[0]
                                    
                                    # Add catalog_id to context for worker
                                    ctx['catalog_id'] = catalog_id
                                    
                                    await cur.execute(
                                        """
                                        INSERT INTO noetl.queue (execution_id, catalog_id, node_id, action, context, priority, max_attempts, available_at)
                                        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, now())
                                        ON CONFLICT (execution_id, node_id) DO NOTHING
                                        RETURNING queue_id
                                        """,
                                        (
                                            snowflake_id_to_int(execution_id),
                                            catalog_id,
                                            f"{execution_id}:{next_step_name}",
                                            json.dumps(encoded),
                                            json.dumps(ctx),
                                            5,
                                            max_attempts,
                                        )
                                    )
                                    await conn.commit()
                                    logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Enqueued single step '{next_step_name}' for execution {execution_id}")
                            else:
                                logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: No valid first step found for {execution_id}")
                        else:
                            logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: No playbook content found for {pb_path}")
                    else:
                        logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: No playbook path found for {execution_id}")
                        
    except Exception as e:
        logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Initial dispatch failed: {e}")
        logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Initial dispatch failed", exc_info=True)


async def _handle_loop_step(cur, conn, execution_id, step_name, task, loop_cfg, pb_path, pb_ver, workload_ctx, next_with, trigger_event_id: str | None = None):
    """Handle loop step by expanding items and creating individual tasks."""
    
    try:
        from noetl.core.dsl.render import render_template
        from jinja2 import Environment, StrictUndefined
        from noetl.server.api.broker import encode_task_for_queue
        
        jenv = Environment(undefined=StrictUndefined)
        iterator = loop_cfg.get('iterator') or 'item'
        items_tmpl = loop_cfg.get('in')
        loop_mode = loop_cfg.get('mode') or 'async'
        
        # Build rendering context
        items_ctx = {
            'workload': (workload_ctx.get('workload') if isinstance(workload_ctx, dict) else None) or {}
        }
        
        # Include variables passed via 'with' from previous step
        if next_with:
            try:
                rendered_next_with = render_template(jenv, next_with, items_ctx)
                if isinstance(rendered_next_with, dict):
                    items_ctx.update(rendered_next_with)
                else:
                    items_ctx.update(next_with)
            except Exception:
                logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to render next_with; using raw values", exc_info=True)
                items_ctx.update(next_with)
        
        # Render loop items
        items = []
        try:
            rendered_items = render_template(jenv, items_tmpl, items_ctx)
            if isinstance(rendered_items, list):
                items = rendered_items
            elif rendered_items is not None:
                items = [rendered_items]
        except Exception:
            logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to render loop items; defaulting to empty list", exc_info=True)
            items = []
        
        count = len(items)
        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Processing loop '{step_name}' over {count} items (iterator={iterator}, mode={loop_mode}) for execution {execution_id}")
        
        # Remove loop config from task for workers
        task_loop_free = dict(task)
        task_loop_free.pop('loop', None)

        # If loop defines an item-level save, propagate it into the per-iteration task
        # so the worker performs an inline save after executing the action.
        try:
            loop_save = loop_cfg.get('save') if isinstance(loop_cfg, dict) else None
            if isinstance(loop_save, dict) and not task_loop_free.get('save'):
                task_loop_free['save'] = loop_save
        except Exception:
            pass
        encoded_task = encode_task_for_queue(task_loop_free)
        
        # Process each loop item
        for idx, item in enumerate(items):
            ctx = {
                'workload': (workload_ctx.get('workload') if isinstance(workload_ctx, dict) else None) or {},
                'step_name': step_name,
                'path': pb_path,
                'version': pb_ver or 'latest',
                iterator: item,  # Set the iterator variable (e.g., city_item)
                '_iterator': {
                    'collection': iterator,
                    'current_index': idx,
                    'current_item': item,
                    'items_count': count,
                },
            }
            if next_with:
                try:
                    ctx.update(next_with)
                except Exception:
                    pass
            # Attach trigger metadata
            try:
                if trigger_event_id:
                    meta = ctx.get('_meta') or {}
                    meta['parent_event_id'] = str(trigger_event_id)
                    ctx['_meta'] = meta
            except Exception:
                pass

            # Get catalog_id from execution's first event and add to context
            try:
                await cur.execute("SELECT catalog_id FROM noetl.event WHERE execution_id = %s ORDER BY created_at LIMIT 1", (snowflake_id_to_int(execution_id),))
                catalog_row = await cur.fetchone()
                if catalog_row:
                    catalog_id = catalog_row[0]
                    ctx['catalog_id'] = catalog_id
                else:
                    raise ValueError(f"No catalog_id found for execution {execution_id}")
            except Exception as e:
                logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Failed to get catalog_id for loop item {idx}: {e}")
                continue

            # Priority: sequential mode uses index-based priority, async mode uses same priority
            priority = 5 - idx if loop_mode == 'sequential' else 5

            # Emit loop_iteration event for observability and loop trackers
            try:
                await get_event_service().emit({
                    'execution_id': execution_id,
                    'event_type': 'loop_iteration',
                    'node_name': step_name,
                    'node_type': 'loop',
                    'status': 'RUNNING',
                    'context': {
                        'index': idx,
                        'item': item,
                        'iterator': iterator,
                        'path': pb_path,
                        'version': pb_ver or 'latest',
                        '_meta': {'parent_event_id': str(trigger_event_id)} if trigger_event_id else {},
                    },
                    'iterator': iterator,
                    'current_index': idx,
                    'current_item': item,
                })
            except Exception:
                logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to emit loop_iteration", exc_info=True)

            try:
                # catalog_id is already in context, use it for queue insert
                catalog_id = ctx.get('catalog_id')
                if not catalog_id:
                    raise ValueError(f"No catalog_id available for execution {execution_id}")
                
                await cur.execute(
                    """
                    INSERT INTO noetl.queue (execution_id, catalog_id, node_id, action, context, priority, max_attempts, available_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, now())
                    ON CONFLICT (execution_id, node_id) DO NOTHING
                    RETURNING queue_id
                    """,
                    (
                        snowflake_id_to_int(execution_id),
                        catalog_id,
                        f"{execution_id}:{step_name}:{idx}",
                        json.dumps(encoded_task),
                        json.dumps(ctx),
                        priority,
                        3,
                    )
                )
            except Exception as e:
                logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Queue insert failed for loop item {idx} of step '{step_name}': {e}")
        
        await conn.commit()
        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Enqueued {count} loop jobs for step '{step_name}' (mode: {loop_mode}) in execution {execution_id}")
        
    except Exception as e:
        logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Loop processing failed for step '{step_name}': {e}")
        logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Loop processing failed", exc_info=True)


async def _advance_non_loop_steps(execution_id: str, trigger_event_id: str | None = None) -> None:
    """Advance workflow for completed non-loop steps by emitting step_completed and allowing controllers to enqueue next.

    Idempotent by design: dedup guards skip if step_completed already exists.
    Runs even without a trigger id so action_completed alone can progress the workflow.
    """
    print(f"!!! ADVANCE_NON_LOOP CALLED FOR {execution_id} !!!")
    logger.info(f"ADVANCE_NON_LOOP: Starting for execution_id={execution_id}")
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Fetch recently completed non-loop steps  
                # Include both action_completed and step_result events to handle workbook steps
                await cur.execute(
                    """
                    SELECT DISTINCT node_name, node_id, event_type
                    FROM noetl.event
                    WHERE execution_id = %s
                      AND event_type IN ('action_completed', 'step_result')
                """,
                    (execution_id,)
                )
                rows = await cur.fetchall()
                completed_steps = set()
                
                logger.info(f"ADVANCE_NON_LOOP: Found {len(rows)} potential completed events for {execution_id}")
                
                for row in rows:
                    node_name = row[0] if not isinstance(row, dict) else row.get('node_name')
                    node_id = row[1] if not isinstance(row, dict) else row.get('node_id')
                    event_type = row[2] if not isinstance(row, dict) else row.get('event_type')
                    
                    logger.info(f"ADVANCE_NON_LOOP: Processing {event_type} event for node_name={node_name}, node_id={node_id}")
                    
                    if event_type == 'action_completed':
                        completed_steps.add(node_name)
                        logger.info(f"ADVANCE_NON_LOOP: Added action_completed step: {node_name}")
                    elif event_type == 'step_result' and node_id:
                        # For step_result events, extract the step name from node_id
                        # node_id format: "execution_id:step_name"
                        try:
                            if ':' in str(node_id):
                                step_name = str(node_id).split(':', 1)[1]
                                completed_steps.add(step_name)
                                logger.info(f"ADVANCE_NON_LOOP: Added step_result step: {step_name} (from node_id: {node_id})")
                        except Exception as e:
                            logger.info(f"ADVANCE_NON_LOOP: Failed to extract step name from node_id {node_id}: {e}")
                
                completed_steps = list(completed_steps)
                logger.info(f"ADVANCE_NON_LOOP: Final completed_steps list: {completed_steps}")

                if not completed_steps:
                    return

                # Determine playbook path/version to read transitions
                pb_path = None
                pb_ver = None
                await cur.execute(
                    """
                    SELECT meta, context FROM noetl.event
                    WHERE execution_id = %s AND event_type IN ('execution_start','execution_started')
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (execution_id,)
                )
                row = await cur.fetchone()
                if row:
                    try:
                        m = row[0]
                        c = row[1]
                        if m:
                            import json as _json
                            md = _json.loads(m) if isinstance(m, str) else m
                            pb_path = md.get('playbook_path') or md.get('resource_path') or pb_path
                            pb_ver = md.get('resource_version') or pb_ver
                        if c and not pb_path:
                            import json as _json
                            cd = _json.loads(c) if isinstance(c, str) else c
                            pb_path = cd.get('path') or pb_path
                            pb_ver = cd.get('version') or pb_ver
                    except Exception:
                        pass

                # Build by_name index from catalog
                by_name = {}
                if pb_path:
                    try:
                        from noetl.server.api.catalog import get_catalog_service
                        catalog = get_catalog_service()
                        if not pb_ver:
                            try:
                                pb_ver = await catalog.get_latest_version(pb_path)
                            except Exception:
                                pb_ver = '0.1.0'
                        entry = await catalog.fetch_entry(pb_path, pb_ver)
                        if entry and entry.get('content'):
                            import yaml as _yaml
                            pb = _yaml.safe_load(entry['content']) or {}
                            steps = pb.get('workflow') or pb.get('steps') or []
                            for s in steps:
                                try:
                                    nm = s.get('step') or s.get('name')
                                    if nm:
                                        by_name[str(nm)] = s
                                except Exception:
                                    pass
                    except Exception:
                        logger.debug("ADVANCE_NON_LOOP: Failed to fetch playbook content", exc_info=True)

                for step_name in completed_steps:
                    if not step_name:
                        continue
                    # Skip if step_completed already recorded
                    await cur.execute(
                        """
                        SELECT 1 FROM noetl.event
                        WHERE execution_id = %s AND node_name = %s AND event_type = 'step_completed'
                        LIMIT 1
                        """,
                        (execution_id, step_name)
                    )
                    if await cur.fetchone():
                        continue

                    # Emit step_completed marker
                    try:
                        await get_event_service().emit({
                            'execution_id': execution_id,
                            'event_type': 'step_completed',
                            'node_name': step_name,
                            'node_type': 'step',
                            'status': 'COMPLETED',
                            'context': {'step_name': step_name}
                        })
                    except Exception:
                        logger.debug("ADVANCE_NON_LOOP: Failed to emit step_completed", exc_info=True)

                    # Let the step controller handle choosing and enqueuing the next transition
    except Exception as e:
        logger.error(f"ADVANCE_NON_LOOP: Unhandled exception in _advance_non_loop_steps: {e}")
        logger.debug("ADVANCE_NON_LOOP: Unhandled exception", exc_info=True)


def _is_actionable_step(step_def: dict) -> bool:
    """
    Determine if a step is actionable (should be executed by a worker).
    
    Steps named 'start' or 'end' are NEVER actionable - they are control flow routers.
    Even if someone incorrectly adds a type to them, we treat them as routers.
    """
    try:
        # Check step name first - 'start' and 'end' are always control flow routers
        step_name = str((step_def or {}).get('step') or (step_def or {}).get('name') or '').lower()
        if step_name in {'start', 'end'}:
            return False
        
        t = str((step_def or {}).get('type') or '').lower()
        if not t:
            return False
        
        # Check if step has a save block - if so, it's actionable regardless of type
        if step_def.get('save'):
            return True
            
        # Include 'save' so save steps run on workers
        if t in {'http','python','duckdb','postgres','secrets','workbook','playbook','save','iterator'}:
            # For python, require code in step_def
            if t == 'python':
                c = step_def.get('code') or step_def.get('code_b64') or step_def.get('code_base64')
                return bool(c)
            return True
        return False
    except Exception:
        return False


async def _finalize_result_step(execution_id: str, step_name: str, step_def: dict, pb_path: str | None, pb_ver: str | None) -> None:
    """Handle non-actionable result-only steps by computing their result and emitting execution_complete.

    If no result mapping is present, emit a control step-completed marker only.
    """
    try:
        from jinja2 import Environment, StrictUndefined, BaseLoader
        from noetl.core.dsl.render import render_template
        # Build base context: workload + prior results
        workload = {}
        results = {}
        dao = EventLog()
        first_ctx = await dao.get_earliest_context(execution_id)
        if first_ctx:
            import json as _json
            try:
                ctx_first = _json.loads(first_ctx) if isinstance(first_ctx, str) else first_ctx
                workload = ctx_first.get('workload', {}) if isinstance(ctx_first, dict) else {}
            except Exception:
                workload = {}
        node_results_map = await dao.get_all_node_results(execution_id)
        if isinstance(node_results_map, dict):
            import json as _json
            for k, v in node_results_map.items():
                try:
                    val = _json.loads(v) if isinstance(v, str) else v
                except Exception:
                    val = v
                # Flatten common action envelope one level so `step.data.*` resolves naturally
                try:
                    if isinstance(val, dict) and isinstance(val.get('data'), (dict, list)) and (
                        ('status' in val) or ('id' in val)
                    ):
                        val = val.get('data')
                except Exception:
                    pass
                results[str(k)] = val
        # Render result mapping if present
        result_mapping = step_def.get('result')
        rendered_result = None
        if isinstance(result_mapping, dict):
            env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
            base_ctx = {'workload': workload, 'work': workload, 'context': workload}
            # Expose results by step name
            try:
                base_ctx.update(results)
            except Exception:
                pass
            try:
                rendered_result = render_template(env, result_mapping, base_ctx, rules=None, strict_keys=False)
            except Exception:
                rendered_result = result_mapping
        # Emit final event(s)
        es = get_event_service()
        if rendered_result is not None:
            await es.emit({
                'execution_id': execution_id,
                'event_type': 'execution_complete',
                'status': 'COMPLETED',
                'node_name': step_name,
                'node_type': 'playbook',
                'result': rendered_result,
                'context': {'reason': 'control_step'}
            })
        else:
            # Fallback: just mark step completed (control)
            await es.emit({
                'execution_id': execution_id,
                'event_type': 'step_completed',
                'status': 'COMPLETED',
                'node_name': step_name,
                'node_type': 'step',
                'context': {'reason': 'control_step'}
            })
    except Exception as e:
        logger.debug(f"FINALIZE_RESULT_STEP: Failed to finalize result step {step_name}: {e}", exc_info=True)
