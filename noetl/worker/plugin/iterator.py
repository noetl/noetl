"""
Iterator task executor for NoETL jobs.

Executes a nested task over an iterable with per-iteration (or per-batch) context
and optional per-item save, supporting sequential or async execution with
bounded concurrency while preserving output order.
"""

import uuid
import datetime
import json
from typing import Dict, Any, Optional, Callable, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def _coerce_items(rendered_items: Any) -> List[Any]:
    if isinstance(rendered_items, list):
        return rendered_items
    if isinstance(rendered_items, tuple):
        return list(rendered_items)
    if isinstance(rendered_items, str):
        s = rendered_items.strip()
        if not s:
            return []
        # Try JSON first
        try:
            obj = json.loads(s)
            if isinstance(obj, list):
                return obj
        except Exception:
            pass
        # Fallback: treat as a single item (do not iterate characters)
        return [rendered_items]
    # Fallback single item
    return [rendered_items]


def _truthy(val: Any) -> bool:
    try:
        if isinstance(val, bool):
            return val
        if val is None:
            return False
        if isinstance(val, (int, float)):
            return val != 0
        s = str(val).strip().lower()
        if s in {"true", "yes", "y", "on", "1"}:
            return True
        if s in {"false", "no", "n", "off", "0", "", "none", "null"}:
            return False
        # Non-empty strings default to True
        return True
    except Exception:
        return False


def execute_loop_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a loop controller task.

    Expected task_config keys (standard only):
      - type: iterator
      - collection: expression or list of items
      - element: name of the per-item variable
      - mode: 'sequential' (default) or 'async'
      - concurrency: int (default 8 when mode=async)
      - enumerate: bool (default false) — exposes top-level {{ index }}
      - where: predicate expression for filtering
      - limit: int — max items to process after filtering/sorting
      - chunk: int — batch size; body executes per batch
      - order_by: expression used to sort items before processing
      - task: nested task configuration (required)
        - save: optional per-item save block
      - save: optional step-level save for aggregated results
    """
    task_id = str(uuid.uuid4())
    task_name = task_config.get('name') or task_config.get('task') or 'iterator'
    start_time = datetime.datetime.now()

    try:
        # Strict: only new standard keys supported
        iterator_name = task_config.get('element')
        items_expr = task_config.get('collection')
        if iterator_name is None or items_expr is None:
            raise ValueError("Iterator requires 'element' and 'collection' keys (type: iterator)")
        nested_task = task_config.get('task') or {}
        if not isinstance(nested_task, dict) or not nested_task:
            raise ValueError("Iterator requires a nested 'task' block to execute per element/batch")

        # Optional behavior controls
        mode = str(task_config.get('mode') or 'sequential').strip().lower()
        if mode == 'parallel':
            mode = 'async'
        concurrency = int(task_config.get('concurrency') or (8 if mode == 'async' else 1))
        enumerate_flag = bool(task_config.get('enumerate') or False)
        where_expr = task_config.get('where')
        limit_val = task_config.get('limit')
        try:
            limit_n = int(limit_val) if limit_val is not None else None
        except Exception:
            limit_n = None
        chunk_val = task_config.get('chunk')
        try:
            chunk_n = int(chunk_val) if chunk_val is not None else None
        except Exception:
            chunk_n = None
        order_by_expr = task_config.get('order_by')

        # Build richer context for items rendering
        loop_ctx = dict(context) if isinstance(context, dict) else {}
        try:
            if isinstance(context, dict):
                work = context.get('work')
                if isinstance(work, dict):
                    for k, v in work.items():
                        loop_ctx.setdefault(k, v)
                workload = context.get('workload')
                if isinstance(workload, dict):
                    for k, v in workload.items():
                        loop_ctx.setdefault(k, v)
                inp = context.get('input')
                if isinstance(inp, dict):
                    for k, v in inp.items():
                        loop_ctx.setdefault(k, v)
        except Exception:
            pass
        try:
            if isinstance(task_with, dict):
                for k, v in task_with.items():
                    loop_ctx.setdefault(k, v)
        except Exception:
            pass

        # Render items expression if it's a string template
        try:
            rendered_items = render_template(jinja_env, items_expr, loop_ctx) if isinstance(items_expr, str) else items_expr
        except Exception:
            rendered_items = items_expr
        items = _coerce_items(rendered_items)

        # Apply filtering (where), ordering, and limit
        indexed_items: List[Tuple[int, Any]] = list(enumerate(items))
        if where_expr is not None:
            filtered: List[Tuple[int, Any]] = []
            for orig_idx, it in indexed_items:
                # Build a light eval context
                eval_ctx = dict(loop_ctx)
                try:
                    eval_ctx[iterator_name] = it
                    eval_ctx['parent'] = context
                except Exception:
                    pass
                try:
                    pred_val = render_template(jinja_env, where_expr, eval_ctx)
                except Exception:
                    pred_val = False
                if _truthy(pred_val):
                    filtered.append((orig_idx, it))
            indexed_items = filtered

        if order_by_expr is not None:
            def _key(t: Tuple[int, Any]):
                idx0, it0 = t
                key_ctx = dict(loop_ctx)
                try:
                    key_ctx[iterator_name] = it0
                    key_ctx['parent'] = context
                except Exception:
                    pass
                try:
                    k = render_template(jinja_env, order_by_expr, key_ctx)
                except Exception:
                    k = None
                return (k, idx0)  # stable
            try:
                indexed_items = sorted(indexed_items, key=_key)
            except Exception:
                # best-effort; keep original order
                pass

        if limit_n is not None and limit_n >= 0:
            indexed_items = indexed_items[:limit_n]

        # Chunking: default is per-item iterations (no chunking)
        batches: List[List[Tuple[int, Any]]]
        if chunk_n and chunk_n > 0:
            batches = [indexed_items[i:i+chunk_n] for i in range(0, len(indexed_items), chunk_n)]
        else:
            # One logical iteration per item
            batches = [[pair] for pair in indexed_items]

        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        # total logical iterations (per batch)
        total = len(batches)

        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'iterator',
                'in_progress', 0, context, None,
                {'with_params': task_with, 'iterator': iterator_name, 'mode': mode, 'concurrency': concurrency, 'count': total}, None
            )

        # Helper to run one iteration (per item or per batch)
        def _run_one(iter_index: int, iter_payload: List[Tuple[int, Any]]) -> Dict[str, Any]:
            # When chunking, iter_payload is a list of (orig_idx, item). Without chunking, it's a list with one pair.
            # Build per-iteration context
            iter_ctx = dict(context) if isinstance(context, dict) else {}
            try:
                # Maintain 'work'
                if 'work' in iter_ctx and isinstance(iter_ctx['work'], dict):
                    iter_ctx['work'] = dict(iter_ctx['work'])
                # Parent binding
                iter_ctx['parent'] = context
            except Exception:
                pass

            # Single item vs batch
            items_in_payload = [it for _, it in iter_payload]
            orig_idx = iter_payload[0][0]
            if chunk_n and chunk_n > 0:
                # When chunking, always provide batch list (even if length 1)
                item_for_task = list(items_in_payload)
            else:
                # No chunking: per-item execution
                item_for_task = items_in_payload[0]

            try:
                if isinstance(iter_ctx.get('work'), dict):
                    iter_ctx['work'][iterator_name] = item_for_task
                iter_ctx[iterator_name] = item_for_task
                iter_ctx['_loop'] = {
                    'current_index': iter_index,
                    'index': iter_index,
                    'item': item_for_task,
                    'count': total,
                }
                if enumerate_flag:
                    iter_ctx['index'] = iter_index
                # Provide batch binding when chunking is enabled
                if chunk_n and chunk_n > 0:
                    iter_ctx['batch'] = list(items_in_payload)
            except Exception:
                iter_ctx[iterator_name] = item_for_task

            # Determine nested with-params
            nested_with = {}
            try:
                for k, v in (nested_task.get('with') or {}).items():
                    try:
                        nested_with[k] = render_template(jinja_env, v, iter_ctx) if isinstance(v, str) else v
                    except Exception:
                        nested_with[k] = v
            except Exception:
                nested_with = {}

            # For Python nested tasks, ensure the element and optional batch are passed as kwargs
            try:
                nested_type = str(nested_task.get('type') or '').strip().lower()
            except Exception:
                nested_type = ''
            if nested_type == 'python':
                # For Python tasks pass conventional kwargs only
                # Back-compat: expose element as 'value' for simple functions
                if 'value' not in nested_with:
                    nested_with['value'] = item_for_task
                if 'batch' in iter_ctx and 'batch' not in nested_with:
                    nested_with['batch'] = iter_ctx.get('batch')

            # Execute nested task
            try:
                from noetl.worker import plugin as _plugin
                nested_result = _plugin.execute_task(
                    nested_task,
                    nested_task.get('name') or nested_task.get('task') or 'nested',
                    iter_ctx,
                    jinja_env,
                    nested_with
                )
            except Exception as e_nested:
                logger.error(f"ITERATOR: Nested task failed at logical index {iter_index}: {e_nested}", exc_info=True)
                return {
                    'index': iter_index,
                    'original_indices': [i for i, _ in iter_payload],
                    'error': str(e_nested),
                    'status': 'error'
                }

            # Save each item if nested task declares a save block
            nested_save = nested_task.get('save')
            if nested_save:
                try:
                    ctx_for_save = dict(iter_ctx)
                    try:
                        ctx_for_save['this'] = nested_result
                        if isinstance(nested_result, dict):
                            ctx_for_save.setdefault('data', nested_result.get('data'))
                    except Exception:
                        pass
                    from noetl.worker.plugin.save import execute_save_task as _do_save
                    _ = _do_save({'save': nested_save}, ctx_for_save, jinja_env, nested_with)
                except Exception:
                    logger.debug("ITERATOR: per-item save failed for iteration", exc_info=True)

            # Normalize appended result
            try:
                res = nested_result.get('data') if isinstance(nested_result, dict) and nested_result.get('data') is not None else nested_result
            except Exception:
                res = nested_result
            return {
                'index': iter_index,
                'original_indices': [i for i, _ in iter_payload],
                'result': res,
                'status': 'success'
            }

        # Build logical iterations (per batch)
        logical_iters: List[List[Tuple[int, Any]]] = batches

        if mode == 'async' and concurrency > 1 and len(logical_iters) > 1:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                future_to_idx = {
                    pool.submit(_run_one, idx, payload): idx
                    for idx, payload in enumerate(logical_iters)
                }
                # Collect preserving original order: store in a temp dict
                temp: Dict[int, Dict[str, Any]] = {}
                for fut in as_completed(future_to_idx):
                    idx = future_to_idx[fut]
                    try:
                        out = fut.result()
                    except Exception as ee:
                        out = {'index': idx, 'status': 'error', 'error': str(ee)}
                    temp[idx] = out
                for i in range(len(logical_iters)):
                    rec = temp.get(i) or {'index': i, 'status': 'error', 'error': 'missing result'}
                    if rec.get('status') == 'error':
                        errors.append({'index': rec.get('index'), 'message': rec.get('error')})
                    results.append(rec)
        else:
            for idx, payload in enumerate(logical_iters):
                rec = _run_one(idx, payload)
                if rec.get('status') == 'error':
                    errors.append({'index': rec.get('index'), 'message': rec.get('error')})
                results.append(rec)

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Build aggregated plain list in original logical order
        final = [r.get('result') for r in results]

        if log_event_callback:
            log_event_callback(
                'task_complete', task_id, task_name, 'iterator',
                'success', duration, context,
                {'results': final, 'items': final, 'count': len(final), 'errors': errors},
                {'with_params': task_with, 'iterator': iterator_name, 'count': len(final)}, event_id
            )

        # Optional step-level aggregated save
        try:
            step_save = task_config.get('save')
            if step_save:
                from noetl.worker.plugin.save import execute_save_task as _do_save
                save_ctx = dict(context) if isinstance(context, dict) else {}
                try:
                    save_ctx['results'] = final
                    save_ctx['items'] = final
                    save_ctx['result'] = final
                    save_ctx['errors'] = errors
                    save_ctx.setdefault('count', len(final))
                except Exception:
                    pass
                _ = _do_save({'save': step_save}, save_ctx, jinja_env, task_with)
        except Exception:
            logger.debug("LOOP: step-level aggregated save failed", exc_info=True)

        return {
            'id': task_id,
            'status': 'success',
            'data': {
                'results': final,
                'items': final,
                'count': len(final),
                'errors': errors
            }
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


__all__ = ['execute_loop_task']
