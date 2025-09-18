"""
Loop controller action executor for NoETL jobs.

Executes a nested task over an iterable with per-iteration context and
optional per-item save (save_each).
"""

import uuid
import datetime
import json
from typing import Dict, Any, Optional, Callable, List
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
        # Fallback: single string item
        return [rendered_items]
    # Fallback single item
    return [rendered_items]


def execute_loop_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a loop controller task.

    Expected task_config keys:
      - iterator: name of the loop variable (default: item)
      - in: expression or list of items
      - mode: optional (currently sequential)
      - task: nested task configuration (required)
        - save: optional per-item save block
      - save: optional step-level save for aggregated results
    """
    task_id = str(uuid.uuid4())
    task_name = task_config.get('name') or task_config.get('task') or 'loop'
    start_time = datetime.datetime.now()

    try:
        iterator_name = task_config.get('iterator') or 'item'
        items_expr = task_config.get('in')
        nested_task = task_config.get('task') or {}

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

        results = []
        total = len(items)

        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'loop',
                'in_progress', 0, context, None,
                {'with_params': task_with, 'iterator': iterator_name, 'count': total}, None
            )

        # Iterate sequentially
        for idx, item in enumerate(items):
            # Per-iteration context
            iter_ctx = dict(context) if isinstance(context, dict) else {}
            try:
                # Maintain 'work' and expose iterator at top level
                if 'work' in iter_ctx and isinstance(iter_ctx['work'], dict):
                    iter_ctx['work'] = dict(iter_ctx['work'])
                    iter_ctx['work'][iterator_name] = item
                iter_ctx[iterator_name] = item
                # Provide _loop metadata
                iter_ctx['_loop'] = {
                    'current_index': idx,
                    'index': idx,
                    'item': item,
                    'count': total,
                }
            except Exception:
                iter_ctx[iterator_name] = item

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

            # Execute nested task
            try:
                # Lazy import to avoid circulars
                from noetl.worker import plugin as _plugin
                nested_result = _plugin.execute_task(nested_task, nested_task.get('name') or nested_task.get('task') or 'nested', iter_ctx, jinja_env, nested_with)
            except Exception as e_nested:
                logger.error(f"LOOP: Nested task failed at index {idx}: {e_nested}", exc_info=True)
                results.append({'status': 'error', 'error': str(e_nested), 'index': idx})
                continue

            # Save each item if nested task declares a save block
            nested_save = nested_task.get('save') or nested_task.get('save_each') or nested_task.get('saveEach')
            if nested_save:
                try:
                    # Provide 'this' and 'data' aliases for save mapping
                    ctx_for_save = dict(iter_ctx)
                    try:
                        ctx_for_save['this'] = nested_result
                        if isinstance(nested_result, dict):
                            ctx_for_save.setdefault('data', nested_result.get('data'))
                    except Exception:
                        pass
                    from noetl.worker.plugin.save import execute_save_task as _do_save
                    save_payload = {'save': nested_save}
                    _ = _do_save(save_payload, ctx_for_save, jinja_env, nested_with)
                except Exception:
                    logger.debug("LOOP: per-item save failed for iteration", exc_info=True)

            # Normalize appended result
            try:
                res = nested_result.get('data') if isinstance(nested_result, dict) and nested_result.get('data') is not None else nested_result
            except Exception:
                res = nested_result
            results.append({'index': idx, 'result': res})

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Build aggregated plain list
        final = [r.get('result') for r in results]

        if log_event_callback:
            log_event_callback(
                'task_complete', task_id, task_name, 'loop',
                'success', duration, context,
                {'results': final, 'count': len(final)},
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
                    save_ctx['result'] = final
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
                'count': len(final)
            }
        }

    except Exception as e:
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'loop',
                'error', duration, context, None,
                {'with_params': task_with, 'error': str(e)}, None
            )
        return {
            'id': task_id,
            'status': 'error',
            'error': str(e)
        }


__all__ = ['execute_loop_task']
