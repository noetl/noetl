"""
Iterator task executor.

Main orchestrator for iterator tasks that executes nested tasks over
collections with configurable execution mode (sequential/async), filtering,
sorting, and aggregation.
"""

import uuid
import datetime
from typing import Dict, Any, Optional, Callable, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger
from .utils import coerce_items, create_batches
from .config import (
    extract_config,
    resolve_collection,
    build_loop_context,
    apply_filtering,
    apply_sorting
)
from .execution import run_one_iteration

logger = setup_logger(__name__, include_location=True)


def execute_loop_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute an iterator/loop controller task.
    
    This executor:
    1. Extracts and validates configuration
    2. Resolves collection from various sources
    3. Applies filtering (where), sorting (order_by), and limit
    4. Creates batches (if chunking enabled)
    5. Executes iterations (sequential or async with concurrency)
    6. Aggregates results preserving order
    7. Executes optional step-level save
    
    Expected task_config keys (standard only):
      - tool: iterator
      - data|collection: expression or list of items
      - element: name of the per-item variable
      - mode: 'sequential' (default) or 'async'
      - concurrency: int (default 8 when mode=async)
      - enumerate: bool (default false) — exposes top-level {{ index }}
      - where: predicate expression for filtering
      - limit: int — max items to process after filtering/sorting
      - chunk: int — batch size; body executes per batch
      - order_by: expression used to sort items before processing
      - task: nested task configuration (required)
        - sink: optional per-item sink block
      - sink: optional step-level sink for aggregated results
    
    Args:
        task_config: Task configuration
        context: Execution context
        jinja_env: Jinja2 environment
        task_with: With-parameters
        log_event_callback: Optional event logging callback
        
    Returns:
        Task result dictionary with keys:
        - id: Task ID
        - status: 'success' or 'error'
        - data: List of iteration results (if success)
        - error: Error message (if error)
    """
    logger.critical("=" * 80)
    logger.critical("ITERATOR.EXECUTOR: execute_loop_task CALLED")
    logger.critical(f"ITERATOR.EXECUTOR: task_config keys: {list(task_config.keys()) if isinstance(task_config, dict) else 'not dict'}")
    logger.critical(f"ITERATOR.EXECUTOR: task_config.get('task'): {task_config.get('task')}")
    logger.critical("=" * 80)
    
    task_id = str(uuid.uuid4())
    task_name = task_config.get('name') or task_config.get('task') or 'iterator'
    start_time = datetime.datetime.now()
    
    # Emit explicit iterator_started event
    if log_event_callback:
        log_event_callback(
            'iterator_started', task_id, task_name, 'iterator',
            'in_progress', 0, context, None,
            {'task_config': task_config},
            None
        )
    
    try:
        # Step 1: Extract configuration
        config = extract_config(task_config)
        
        iterator_name = config['iterator_name']
        nested_task = config['nested_task']
        collection_expr = config.get('collection')
        mode = config['mode']
        concurrency = config['concurrency']
        enumerate_flag = config['enumerate_flag']
        where_expr = config['where_expr']
        limit_n = config['limit_n']
        chunk_n = config['chunk_n']
        order_by_expr = config['order_by_expr']
        pagination_config = config.get('pagination_config')
        
        # Check for pagination mode - if configured, delegate to pagination executor
        if pagination_config:
            logger.info("ITERATOR.EXECUTOR: Pagination detected, delegating to pagination executor")
            from .pagination import execute_paginated_http
            
            # Execute paginated HTTP
            result_data = execute_paginated_http(
                nested_task,
                pagination_config,
                context,
                jinja_env
            )
            
            # Build success result
            if log_event_callback:
                log_event_callback(
                    'iterator_completed', task_id, task_name, 'iterator',
                    'success', 1, context, None,
                    {'result': result_data},
                    None
                )
            
            return {
                'id': task_id,
                'status': 'success',
                'data': result_data
            }
        
        # Standard iterator execution (non-paginated)
        
        # Step 2: Resolve collection (use from config if available, otherwise resolve from task_config)
        if collection_expr is not None:
            items_expr = collection_expr
        else:
            items_expr = resolve_collection(
                task_config, context, task_with, iterator_name
            )
        
        # Step 3: Build loop context for rendering
        loop_ctx = build_loop_context(context, task_with)
        
        # Step 4: Render items expression if it's a string template
        try:
            rendered_items = (render_template(jinja_env, items_expr, loop_ctx) 
                            if isinstance(items_expr, str) else items_expr)
        except Exception:
            rendered_items = items_expr
        
        items = coerce_items(rendered_items)
        
        # Step 5: Apply filtering (where), ordering, and limit
        indexed_items = list(enumerate(items))
        
        if where_expr is not None:
            indexed_items = apply_filtering(
                indexed_items, where_expr, iterator_name, 
                loop_ctx, context, jinja_env
            )
        
        if order_by_expr is not None:
            indexed_items = apply_sorting(
                indexed_items, order_by_expr, iterator_name,
                loop_ctx, context, jinja_env
            )
        
        if limit_n is not None and limit_n >= 0:
            indexed_items = indexed_items[:limit_n]
        
        # Step 6: Create batches
        batches = create_batches(indexed_items, chunk_n)
        
        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        total = len(batches)
        
        # Store total count in config for iteration context
        config['total_count'] = total
        
        # Log start event
        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'iterator',
                'in_progress', 0, context, None,
                {
                    'with_params': task_with, 
                    'iterator': iterator_name, 
                    'mode': mode, 
                    'concurrency': concurrency, 
                    'count': total
                }, 
                None
            )
        
        # Step 7: Execute iterations
        if mode == 'async' and concurrency > 1 and len(batches) > 1:
            # Async execution with bounded concurrency
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                future_to_idx = {
                    pool.submit(
                        run_one_iteration, idx, payload, context, 
                        task_config, config, jinja_env, log_event_callback
                    ): idx
                    for idx, payload in enumerate(batches)
                }
                
                # Collect results preserving original order
                temp: Dict[int, Dict[str, Any]] = {}
                for fut in as_completed(future_to_idx):
                    idx = future_to_idx[fut]
                    try:
                        out = fut.result()
                    except Exception as ee:
                        out = {
                            'index': idx, 
                            'status': 'error', 
                            'error': str(ee)
                        }
                    temp[idx] = out
                
                # Reconstruct in original order
                for i in range(len(batches)):
                    rec = temp.get(i) or {
                        'index': i, 
                        'status': 'error', 
                        'error': 'missing result'
                    }
                    if rec.get('status') == 'error':
                        errors.append({
                            'index': rec.get('index'), 
                            'message': rec.get('error')
                        })
                    results.append(rec)
        else:
            # Sequential execution
            for idx, payload in enumerate(batches):
                rec = run_one_iteration(
                    idx, payload, context, task_config, config, jinja_env, log_event_callback
                )
                if rec.get('status') == 'error':
                    errors.append({
                        'index': rec.get('index'), 
                        'message': rec.get('error')
                    })
                results.append(rec)
        
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Build aggregated plain list in original logical order
        final = [r.get('result') for r in results]
        
        # Determine overall status based on errors
        overall_status = 'error' if errors else 'success'
        
        # Log completion event
        if log_event_callback:
            log_event_callback(
                'task_complete', task_id, task_name, 'iterator',
                overall_status, duration, context,
                {
                    'results': final, 
                    'items': final, 
                    'count': len(final), 
                    'errors': errors
                },
                {
                    'with_params': task_with, 
                    'iterator': iterator_name, 
                    'count': len(final)
                }, 
                event_id
            )
        
        # Step 8: Optional step-level aggregated save (single transaction)
        # For NEW format (loop attribute), sink is always per-item only, not aggregated
        # For OLD format (tool: iterator), sink at step level is aggregated
        has_loop_attribute = 'loop' in task_config
        step_sink = task_config.get('sink') if not has_loop_attribute else None
        
        if step_sink:
            try:
                from noetl.plugin.shared.storage import execute_sink_task as _do_sink
                sink_ctx = dict(context) if isinstance(context, dict) else {}
                try:
                    sink_ctx['results'] = final
                    sink_ctx['items'] = final
                    sink_ctx['result'] = final
                    sink_ctx['errors'] = errors
                    sink_ctx.setdefault('count', len(final))
                except Exception:
                    pass
                
                sink_result = _do_sink({'sink': step_sink}, sink_ctx, jinja_env, task_with)
                
                # Check sink result and fail entire iterator if sink failed
                if isinstance(sink_result, dict) and sink_result.get('status') == 'error':
                    error_msg = sink_result.get('error', 'Step-level sink operation failed')
                    logger.error(f"LOOP: step-level aggregated sink failed: {error_msg}")
                    raise Exception(f"Step-level sink failed: {error_msg}")
                    
            except Exception as e_sink:
                logger.error("LOOP: step-level aggregated sink failed", exc_info=True)
                # Re-raise to fail the entire iterator task
                raise e_sink
        
        # Return canonical result
        logger.debug(
            f"LOOP: Completed iterator '{task_name}' with {len(final)} results "
            f"(errors={len(errors)})"
        )
        
        # Return error status if any iteration failed
        if errors:
            return {
                'id': task_id,
                'status': 'error',
                'data': final,
                'error': f"{len(errors)} iteration(s) failed",
                'errors': errors
            }
        
        return {
            'id': task_id,
            'status': 'success',
            'data': final
        }
        
    except Exception as e:
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'iterator',
                'error', duration, context, None,
                {'with_params': task_with, 'error': str(e)}, None
            )
        
        return {
            'id': task_id,
            'status': 'error',
            'error': str(e)
        }
