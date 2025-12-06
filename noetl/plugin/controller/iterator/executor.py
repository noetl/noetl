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
    Execute an iterator/loop controller task - EVENT-DRIVEN ARCHITECTURE.
    
    This executor DOES NOT execute iterations in-process. Instead:
    1. Analyzes collection (resolve, filter, sort, count)
    2. Extracts nested task configuration
    3. Emits iterator_started event via server API
    4. Server receives event → enqueues N iteration jobs
    5. Workers pick up iteration jobs → execute → report completion
    6. Server tracks completion → emits iterator_completed → continues workflow
    
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
        Task result dictionary indicating event was emitted (server handles execution)
    """
    logger.critical("=" * 80)
    logger.critical("ITERATOR.EXECUTOR: execute_loop_task CALLED (EVENT-DRIVEN)")
    logger.critical(f"ITERATOR.EXECUTOR: task_config keys: {list(task_config.keys()) if isinstance(task_config, dict) else 'not dict'}")
    logger.critical("=" * 80)
    
    task_id = str(uuid.uuid4())
    task_name = task_config.get('name') or task_config.get('task') or 'iterator'
    start_time = datetime.datetime.now()
    
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
        
        # Step 2: Resolve and analyze collection
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
        
        # Extract just the items (not indices) for serialization
        final_items = [item for _, item in indexed_items]
        total = len(final_items)
        
        logger.info(f"ITERATOR: Analyzed collection - {total} items after filtering/sorting/limit")
        
        # Step 6: Emit iterator_started event via server API
        # This tells the server to enqueue iteration jobs
        if log_event_callback:
            event_data = {
                'iterator_name': iterator_name,
                'collection': final_items,  # Send resolved collection to server
                'nested_task': nested_task,
                'mode': mode,
                'concurrency': concurrency,
                'chunk_size': chunk_n,
                'enumerate': enumerate_flag,
                'total_count': total
            }
            
            log_event_callback(
                'iterator_started', task_id, task_name, 'iterator',
                'RUNNING', 0, context, None,
                event_data,
                None
            )
            
            logger.info(
                f"ITERATOR: Emitted iterator_started event - server will enqueue {total} iteration jobs"
            )
        
        # Return success immediately - server will handle iteration execution
        duration = (datetime.datetime.now() - start_time).total_seconds()
        
        return {
            'id': task_id,
            'status': 'success',
            'data': {
                'iterator_started': True,
                'total_iterations': total,
                'message': 'Iterator analysis complete, server will execute iterations'
            }
        }
        
    except Exception as e:
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.error(f"ITERATOR: Failed to analyze collection: {e}", exc_info=True)
        
        if log_event_callback:
            log_event_callback(
                'iterator_failed', task_id, task_name, 'iterator',
                'FAILED', duration, context, None,
                {'error': str(e)}, str(e)
            )
        
        return {
            'id': task_id,
            'status': 'error',
            'error': f"Iterator analysis failed: {str(e)}"
        }
