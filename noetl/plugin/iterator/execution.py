"""
Iterator per-iteration execution logic.

Handles executing nested tasks for each iteration with proper context
and optional per-item save operations.
"""

from typing import Dict, Any, List, Tuple, Optional, Callable
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def build_iteration_context(
    context: Dict[str, Any],
    iterator_name: str,
    item_for_task: Any,
    iter_index: int,
    total_count: int,
    enumerate_flag: bool,
    chunk_n: int,
    items_in_payload: List[Any],
    task_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build execution context for a single iteration.
    
    Args:
        context: Parent execution context
        iterator_name: Element variable name
        item_for_task: Item(s) to process (single item or batch)
        iter_index: Iteration index
        total_count: Total number of iterations
        enumerate_flag: Whether to expose top-level {{ index }}
        chunk_n: Chunk size (0 if no chunking)
        items_in_payload: All items in this iteration
        task_config: Task configuration
        
    Returns:
        Iteration context dictionary
    """
    iter_ctx = dict(context) if isinstance(context, dict) else {}
    
    try:
        # Maintain 'work' section
        if 'work' in iter_ctx and isinstance(iter_ctx['work'], dict):
            iter_ctx['work'] = dict(iter_ctx['work'])
        
        # Set parent binding
        iter_ctx['parent'] = context
    except Exception:
        pass
    
    # Set element variable
    try:
        if isinstance(iter_ctx.get('work'), dict):
            iter_ctx['work'][iterator_name] = item_for_task
        iter_ctx[iterator_name] = item_for_task
        
        # Set loop metadata
        iter_ctx['_loop'] = {
            'current_index': iter_index,
            'index': iter_index,
            'item': item_for_task,
            'count': total_count,
        }
        
        # Expose <loop_step>.result_index during the body
        try:
            step_nm = task_config.get('name') or task_config.get('task') or 'iterator'
            iter_ctx[str(step_nm)] = {'result_index': iter_index}
        except Exception:
            pass
        
        # Expose top-level index if enumerate flag set
        if enumerate_flag:
            iter_ctx['index'] = iter_index
        
        # Provide batch binding when chunking is enabled
        if chunk_n and chunk_n > 0:
            iter_ctx['batch'] = list(items_in_payload)
    except Exception:
        iter_ctx[iterator_name] = item_for_task
    
    return iter_ctx


def build_nested_with_params(
    nested_task: Dict[str, Any],
    iter_ctx: Dict[str, Any],
    item_for_task: Any,
    jinja_env: Environment
) -> Dict[str, Any]:
    """
    Build with-parameters for nested task execution.
    
    Args:
        nested_task: Nested task configuration
        iter_ctx: Iteration context
        item_for_task: Item(s) for this iteration
        jinja_env: Jinja2 environment
        
    Returns:
        Nested with-parameters dictionary
    """
    nested_with = {}
    
    try:
        for k, v in (nested_task.get('with') or {}).items():
            try:
                nested_with[k] = (render_template(jinja_env, v, iter_ctx) 
                                 if isinstance(v, str) else v)
            except Exception:
                nested_with[k] = v
    except Exception:
        nested_with = {}
    
    # For Python nested tasks, provide conventional kwargs
    try:
        nested_type = str(nested_task.get('type') or '').strip().lower()
    except Exception:
        nested_type = ''
    
    if nested_type == 'python':
        # Back-compat: expose element as 'value' for simple functions
        if 'value' not in nested_with:
            nested_with['value'] = item_for_task
        
        # Expose batch if available
        if 'batch' in iter_ctx and 'batch' not in nested_with:
            nested_with['batch'] = iter_ctx.get('batch')
    
    return nested_with


def execute_nested_task(
    nested_task: Dict[str, Any],
    iter_ctx: Dict[str, Any],
    nested_with: Dict[str, Any],
    jinja_env: Environment,
    iter_index: int
) -> Dict[str, Any]:
    """
    Execute nested task and return result.
    
    Args:
        nested_task: Nested task configuration
        iter_ctx: Iteration context
        nested_with: Nested with-parameters
        jinja_env: Jinja2 environment
        iter_index: Iteration index for logging
        
    Returns:
        Task execution result
        
    Raises:
        Exception: If nested task execution fails
    """
    from noetl import plugin as _plugin
    
    logger.info(
        f"ITERATOR: Executing nested task - type={nested_task.get('type')}, "
        f"path={nested_task.get('path')}, iter_index={iter_index}"
    )
    
    result = _plugin.execute_task(
        nested_task,
        nested_task.get('name') or nested_task.get('task') or 'nested',
        iter_ctx,
        jinja_env,
        nested_with
    )
    
    logger.info(
        f"ITERATOR: Nested task completed - iter_index={iter_index}, "
        f"result_status={result.get('status')}"
    )
    
    return result


def execute_per_item_save(
    nested_task: Dict[str, Any],
    nested_result: Dict[str, Any],
    iter_ctx: Dict[str, Any],
    nested_with: Dict[str, Any],
    jinja_env: Environment,
    log_event_callback: Optional[Callable] = None,
    iter_index: int = 0
) -> Dict[str, Any]:
    """
    Execute per-item save if configured in nested task.
    
    Save operates as a single transaction - if save fails, the entire action type fails.
    Emits explicit lifecycle events: save_started, save_completed/save_failed.
    
    Args:
        nested_task: Nested task configuration
        nested_result: Nested task result
        iter_ctx: Iteration context
        nested_with: Nested with-parameters
        jinja_env: Jinja2 environment
        log_event_callback: Optional callback for event reporting
        iter_index: Current iteration index for event identification
        
    Returns:
        Save result dictionary with 'status', 'data', 'meta', and optional 'error' keys
        
    Raises:
        Exception: If save fails (propagated to caller)
    """
    nested_save = nested_task.get('save')
    
    print(f"!!! ITERATOR.SAVE: execute_per_item_save called for iter_index={iter_index}")
    print(f"!!! ITERATOR.SAVE: nested_task keys={list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}")
    print(f"!!! ITERATOR.SAVE: nested_save={nested_save}")
    
    logger.critical(f"ITERATOR.SAVE: execute_per_item_save called for iter_index={iter_index}")
    logger.critical(f"ITERATOR.SAVE: nested_save={nested_save}")
    
    if not nested_save:
        logger.critical("ITERATOR.SAVE: No save configuration found - SKIPPING")
        return {'status': 'skipped', 'data': None, 'meta': {}}
    
    logger.critical(f"ITERATOR.SAVE: Executing per-item save for iteration {iter_index}")
    
    # Emit explicit save_started event
    if log_event_callback:
        log_event_callback(
            'save_started', None, f'save_iter_{iter_index}', 'save',
            'in_progress', 0, iter_ctx, None,
            {'iteration_index': iter_index, 'save_config': nested_save},
            None
        )
    
    ctx_for_save = dict(iter_ctx)
    try:
        ctx_for_save['this'] = nested_result
        if isinstance(nested_result, dict):
            ctx_for_save.setdefault('data', nested_result.get('data'))
    except Exception:
        pass
    
    logger.critical(f"ITERATOR.SAVE: About to call execute_save_task")
    logger.critical(f"ITERATOR.SAVE: Save task_config={{'save': nested_save}}")
    logger.critical(f"ITERATOR.SAVE: Context keys={list(ctx_for_save.keys())}")
    
    try:
        from noetl.plugin.save import execute_save_task as _do_save
        logger.critical(f"ITERATOR.SAVE: Imported execute_save_task, calling now...")
        save_result = _do_save(
            {'save': nested_save}, 
            ctx_for_save, 
            jinja_env, 
            nested_with
        )
        logger.critical(f"ITERATOR.SAVE: execute_save_task returned: {save_result}")
        
        logger.info(f"ITERATOR: Save completed with status: {save_result.get('status') if isinstance(save_result, dict) else 'unknown'}")
        
        # Check save result and raise exception if failed
        if isinstance(save_result, dict) and save_result.get('status') == 'error':
            error_msg = save_result.get('error', 'Save operation failed')
            logger.error(f"ITERATOR: per-item save failed for iteration {iter_index}: {error_msg}")
            
            # Emit explicit save_failed event
            if log_event_callback:
                log_event_callback(
                    'save_failed', None, f'save_iter_{iter_index}', 'save',
                    'error', 0, iter_ctx, None,
                    {'iteration_index': iter_index, 'error': error_msg},
                    None
                )
            
            raise Exception(f"Save failed: {error_msg}")
        
        # Emit explicit save_completed event
        if log_event_callback:
            log_event_callback(
                'save_completed', None, f'save_iter_{iter_index}', 'save',
                'success', 0, iter_ctx, save_result,
                {'iteration_index': iter_index},
                None
            )
        
        return save_result
        
    except Exception as e:
        # Emit explicit save_error event for unexpected failures
        if log_event_callback:
            log_event_callback(
                'save_error', None, f'save_iter_{iter_index}', 'save',
                'error', 0, iter_ctx, None,
                {'iteration_index': iter_index, 'error': str(e)},
                None
            )
        raise


def run_one_iteration(
    iter_index: int,
    iter_payload: List[Tuple[int, Any]],
    context: Dict[str, Any],
    task_config: Dict[str, Any],
    config: Dict[str, Any],
    jinja_env: Environment,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute one logical iteration (per item or per batch).
    
    Emits explicit lifecycle events: iteration_started, iteration_completed/iteration_failed.
    
    Args:
        iter_index: Logical iteration index
        iter_payload: List of (original_index, item) tuples for this iteration
        context: Parent execution context
        task_config: Task configuration
        config: Extracted iterator configuration
        jinja_env: Jinja2 environment
        log_event_callback: Optional callback for event reporting
        
    Returns:
        Iteration result dictionary with keys:
        - index: Logical iteration index
        - original_indices: Original item indices
        - result: Nested task result data
        - status: 'success' or 'error'
        - error: Error message (if status='error')
    """
    iterator_name = config['iterator_name']
    nested_task = config['nested_task']
    enumerate_flag = config['enumerate_flag']
    chunk_n = config['chunk_n']
    
    print(f"\n!!! RUN_ONE_ITERATION START: iter_index={iter_index}")
    print(f"!!! nested_task keys={list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}")
    print(f"!!! has_save={bool(nested_task.get('save'))}\n")
    
    logger.critical(f"ITERATOR.EXECUTION: run_one_iteration iter_index={iter_index}")
    logger.critical(f"ITERATOR.EXECUTION: nested_task keys={list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}")
    logger.critical(f"ITERATOR.EXECUTION: nested_task.get('save')={nested_task.get('save')}")
    logger.critical(f"ITERATOR.EXECUTION: has_save={bool(nested_task.get('save'))}")
    
    # Emit explicit iteration_started event
    if log_event_callback:
        log_event_callback(
            'iteration_started', None, f'iter_{iter_index}', 'iteration',
            'in_progress', 0, context, None,
            {'iteration_index': iter_index, 'has_save': bool(nested_task.get('save'))},
            None
        )
    
    # Extract items from payload
    items_in_payload = [it for _, it in iter_payload]
    
    # Determine item format (single item vs batch)
    if chunk_n and chunk_n > 0:
        # When chunking, always provide batch list (even if length 1)
        item_for_task = list(items_in_payload)
    else:
        # No chunking: per-item execution
        item_for_task = items_in_payload[0]
    
    # Build iteration context
    iter_ctx = build_iteration_context(
        context, iterator_name, item_for_task, iter_index,
        config.get('total_count', len(iter_payload)),
        enumerate_flag, chunk_n, items_in_payload, task_config
    )
    
    # Build nested with-parameters
    nested_with = build_nested_with_params(
        nested_task, iter_ctx, item_for_task, jinja_env
    )
    
    # Execute nested task
    try:
        nested_result = execute_nested_task(
            nested_task, iter_ctx, nested_with, jinja_env, iter_index
        )
    except Exception as e_nested:
        logger.error(
            f"ITERATOR: Nested task failed at logical index {iter_index}: {e_nested}", 
            exc_info=True
        )
        
        # Emit explicit iteration_failed event
        if log_event_callback:
            log_event_callback(
                'iteration_failed', None, f'iter_{iter_index}', 'iteration',
                'error', 0, context, None,
                {'iteration_index': iter_index, 'error': str(e_nested)},
                None
            )
        
        return {
            'index': iter_index,
            'original_indices': [i for i, _ in iter_payload],
            'error': str(e_nested),
            'status': 'error'
        }
    
    # Execute per-item save if configured (as single transaction with task)
    print(f"\n!!! BEFORE SAVE CALL: iter_index={iter_index}")
    print(f"!!! nested_task keys={list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}")
    print(f"!!! has_save={bool(nested_task.get('save'))}")
    print(f"!!! save_config={nested_task.get('save')}\n")
    
    logger.critical(f"ITERATOR.EXECUTION: About to call execute_per_item_save")
    logger.critical(f"ITERATOR.EXECUTION: nested_task keys before save: {list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}")
    logger.critical(f"ITERATOR.EXECUTION: nested_task['save'] = {nested_task.get('save')}")
    try:
        save_result = execute_per_item_save(
            nested_task, nested_result, iter_ctx, nested_with, jinja_env,
            log_event_callback, iter_index
        )
    except Exception as e_save:
        logger.error(
            f"ITERATOR: Save failed at logical index {iter_index}: {e_save}", 
            exc_info=True
        )
        
        # Emit explicit iteration_failed event (save failure fails the iteration)
        if log_event_callback:
            log_event_callback(
                'iteration_failed', None, f'iter_{iter_index}', 'iteration',
                'error', 0, context, None,
                {'iteration_index': iter_index, 'error': f"Save failed: {str(e_save)}"},
                None
            )
        return {
            'index': iter_index,
            'original_indices': [i for i, _ in iter_payload],
            'error': f"Save failed: {str(e_save)}",
            'status': 'error'
        }
    
    # Normalize result
    try:
        res = (nested_result.get('data') 
              if isinstance(nested_result, dict) and nested_result.get('data') is not None 
              else nested_result)
    except Exception:
        res = nested_result
    
    # Include save metadata in result if save was executed
    result_dict = {
        'index': iter_index,
        'original_indices': [i for i, _ in iter_payload],
        'result': res,
        'status': 'success'
    }
    
    # Add save info to result metadata if save was performed
    if isinstance(save_result, dict) and save_result.get('status') == 'success':
        result_dict['save_meta'] = save_result.get('meta', {})
    
    # Emit explicit iteration_completed event
    if log_event_callback:
        log_event_callback(
            'iteration_completed', None, f'iter_{iter_index}', 'iteration',
            'success', 0, context, result_dict,
            {'iteration_index': iter_index, 'has_save': bool(nested_task.get('save'))},
            None
        )
    
    return result_dict
