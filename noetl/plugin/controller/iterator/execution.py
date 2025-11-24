"""
Iterator per-iteration execution logic.

Handles executing nested tasks for each iteration with proper context
and optional per-item save operations.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def _resolve_task_kind(task_config: Dict[str, Any]) -> str:
    """
    Normalize the tool identifier from a nested task configuration.

    Args:
        task_config: Nested task configuration

    Returns:
        Lower-case tool identifier ('' if not present)
    """
    try:
        tool = task_config.get("tool")
        return tool.strip().lower() if isinstance(tool, str) else ""
    except Exception:
        return ""


def build_iteration_context(
    context: Dict[str, Any],
    iterator_name: str,
    item_for_task: Any,
    iter_index: int,
    total_count: int,
    enumerate_flag: bool,
    chunk_n: int,
    items_in_payload: List[Any],
    task_config: Dict[str, Any],
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
        if "work" in iter_ctx and isinstance(iter_ctx["work"], dict):
            iter_ctx["work"] = dict(iter_ctx["work"])

        # Set parent binding
        iter_ctx["parent"] = context
    except Exception as e:
        logger.warning(
            f"Failed to set parent binding or copy work section: {e}",
            exc_info=True
        )

    # Set element variable
    try:
        if isinstance(iter_ctx.get("work"), dict):
            iter_ctx["work"][iterator_name] = item_for_task
        iter_ctx[iterator_name] = item_for_task

        # Set loop metadata
        iter_ctx["_loop"] = {
            "current_index": iter_index,
            "index": iter_index,
            "item": item_for_task,
            "count": total_count,
        }

        # Expose <loop_step>.result_index during the body
        try:
            # Use step_name from parent context (e.g., 'http_loop'), not nested task config
            step_nm = context.get("step_name") or task_config.get("name") or task_config.get("task") or "iterator"
            iter_ctx[str(step_nm)] = {"result_index": iter_index}
        except Exception as e:
            logger.warning(
                f"Failed to expose step result_index in iteration context: {e}",
                exc_info=True
            )

        # Expose top-level index if enumerate flag set
        if enumerate_flag:
            iter_ctx["index"] = iter_index

        # Provide batch binding when chunking is enabled
        if chunk_n and chunk_n > 0:
            iter_ctx["batch"] = list(items_in_payload)
    except Exception:
        iter_ctx[iterator_name] = item_for_task

    return iter_ctx


def build_nested_args(
    nested_task: Dict[str, Any],
    iter_ctx: Dict[str, Any],
    item_for_task: Any,
    jinja_env: Environment,
) -> Dict[str, Any]:
    """
    Build args for nested task execution.

    Args:
        nested_task: Nested task configuration
        iter_ctx: Iteration context
        item_for_task: Item(s) for this iteration
        jinja_env: Jinja2 environment

    Returns:
        Nested args dictionary
    """
    nested_args = {}

    try:
        for k, v in (nested_task.get("args") or {}).items():
            try:
                # Special handling: if value is exactly "{{ varname }}" and varname exists in context,
                # pass the object directly without string rendering to preserve types (dicts, lists)
                if isinstance(v, str):
                    v_stripped = v.strip()
                    if v_stripped.startswith("{{") and v_stripped.endswith("}}"):
                        var_name = v_stripped[2:-2].strip()
                        logger.info(f"ITERATOR_ARGS_DEBUG: Checking var_name='{var_name}', in context={var_name in iter_ctx}, type={type(iter_ctx.get(var_name))}")
                        if var_name in iter_ctx:
                            # Pass the actual object, not string-rendered version
                            nested_args[k] = iter_ctx[var_name]
                            logger.info(f"ITERATOR_ARGS_DEBUG: Passed object directly for '{k}': type={type(nested_args[k])}")
                            continue
                    # Regular template rendering for string values
                    nested_args[k] = render_template(jinja_env, v, iter_ctx)
                    logger.info(f"ITERATOR_ARGS_DEBUG: Rendered string for '{k}': type={type(nested_args[k])}, value={nested_args[k][:100] if isinstance(nested_args[k], str) else nested_args[k]}")
                else:
                    nested_args[k] = v
            except Exception as e:
                logger.warning(f"ITERATOR_ARGS_DEBUG: Exception for key '{k}': {e}")
                nested_args[k] = v
    except Exception as e:
        logger.warning(f"ITERATOR_ARGS_DEBUG: Exception building args: {e}")
        nested_args = {}

    return nested_args


def _encode_nested_task(nested_task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Encode nested task configuration for execution.
    
    Applies base64 encoding to code/command fields required by some tools
    (postgres, duckdb, python) when executing nested tasks directly without
    going through the queue publisher.
    
    Args:
        nested_task: Nested task configuration
        
    Returns:
        Encoded nested task configuration
    """
    import base64
    
    if not isinstance(nested_task, dict):
        return nested_task
    
    encoded = dict(nested_task)
    
    try:
        # Encode Python code if present
        code_val = encoded.get("code")
        if isinstance(code_val, str) and code_val.strip():
            encoded["code_b64"] = base64.b64encode(
                code_val.encode("utf-8")
            ).decode("ascii")
            encoded.pop("code", None)
        
        # Encode command/commands for PostgreSQL and DuckDB
        for field in ("command", "commands"):
            cmd_val = encoded.get(field)
            if isinstance(cmd_val, str) and cmd_val.strip():
                encoded[f"{field}_b64"] = base64.b64encode(
                    cmd_val.encode("utf-8")
                ).decode("ascii")
                encoded.pop(field, None)
    except Exception as e:
        logger.debug(f"Failed to encode nested task fields: {e}", exc_info=True)
    
    return encoded


def execute_nested_task(
    nested_task: Dict[str, Any],
    iter_ctx: Dict[str, Any],
    nested_args: Dict[str, Any],
    jinja_env: Environment,
    iter_index: int,
) -> Dict[str, Any]:
    """
    Execute nested task and return result.

    Args:
        nested_task: Nested task configuration
        iter_ctx: Iteration context
        nested_args: Nested args
        jinja_env: Jinja2 environment
        iter_index: Iteration index for logging

    Returns:
        Task execution result

    Raises:
        Exception: If nested task execution fails
    """
    from noetl import plugin as _plugin

    logger.info(
        f"ITERATOR: Executing nested task - tool={_resolve_task_kind(nested_task)}, "
        f"path={nested_task.get('path')}, iter_index={iter_index}"
    )

    # Encode nested task configuration (base64 encode code/command fields)
    encoded_nested_task = _encode_nested_task(nested_task)

    result = _plugin.execute_task(
        encoded_nested_task,
        nested_task.get("name") or nested_task.get("task") or "nested",
        iter_ctx,
        jinja_env,
        nested_args,
    )

    logger.info(
        f"ITERATOR: Nested task completed - iter_index={iter_index}, "
        f"result_status={result.get('status')}"
    )

    return result


def execute_per_item_sink(
    nested_task: Dict[str, Any],
    nested_result: Dict[str, Any],
    iter_ctx: Dict[str, Any],
    nested_args: Dict[str, Any],
    jinja_env: Environment,
    log_event_callback: Optional[Callable] = None,
    iter_index: int = 0,
) -> Dict[str, Any]:
    """
    Execute per-item save if configured in nested task.

    Save operates as a single transaction - if save fails, the entire action type fails.
    Emits explicit lifecycle events: save_started, save_completed/save_failed.

    Args:
        nested_task: Nested task configuration
        nested_result: Nested task result
        iter_ctx: Iteration context
        nested_args: Nested args
        jinja_env: Jinja2 environment
        log_event_callback: Optional callback for event reporting
        iter_index: Current iteration index for event identification

    Returns:
        Save result dictionary with 'status', 'data', 'meta', and optional 'error' keys

    Raises:
        Exception: If save fails (propagated to caller)
    """
    nested_sink = nested_task.get('sink')

    print(
        f"!!! ITERATOR.SINK: execute_per_item_sink called for iter_index={iter_index}"
    )
    print(
        f"!!! ITERATOR.SINK: nested_task keys={list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}"
    )
    print(f"!!! ITERATOR.SINK: nested_sink={nested_sink}")

    logger.critical(
        f"ITERATOR.SINK: execute_per_item_sink called for iter_index={iter_index}"
    )
    logger.critical(f"ITERATOR.SINK: nested_sink={nested_sink}")

    if not nested_sink:
        logger.critical("ITERATOR.SINK: No save configuration found - SKIPPING")
        return {"status": "skipped", "data": None, "meta": {}}

    logger.critical(
        f"ITERATOR.SINK: Executing per-item save for iteration {iter_index}"
    )

    # Emit explicit save_started event
    if log_event_callback:
        log_event_callback(
            "save_started",
            None,
            f"save_iter_{iter_index}",
            "save",
            "in_progress",
            0,
            iter_ctx,
            None,
            {"iteration_index": iter_index, "sink_config": nested_sink},
            None,
        )

    ctx_for_save = dict(iter_ctx)
    ctx_for_save["this"] = nested_result
    if isinstance(nested_result, dict):
        ctx_for_save.setdefault("data", nested_result.get("data"))
        # Add 'result' to context for template access in save blocks
        # For HTTP tasks: result.data contains the response body
        # For other tasks: result contains the full task result
        ctx_for_save["result"] = nested_result

    # Delegate to storage save executor
    try:
        from noetl.plugin.shared.storage import execute_sink_task as _do_sink

        logger.critical(f"ITERATOR.SINK: Imported execute_sink_task, calling now...")
        logger.critical(f"ITERATOR.SINK: Context keys available: {list(ctx_for_save.keys())}")
        # Check if step name is in context
        step_nm = nested_args.get("name") or nested_args.get("task") or "iterator"
        if step_nm in ctx_for_save:
            logger.critical(f"ITERATOR.SINK: {step_nm} = {ctx_for_save[step_nm]}")
        sink_result = _do_sink(
            {'sink': nested_sink}, ctx_for_save, jinja_env, nested_args
        )
        logger.critical(f"ITERATOR.SINK: execute_sink_task returned: {sink_result}")

        logger.info(
            f"ITERATOR: Save completed with status: {sink_result.get('status') if isinstance(sink_result, dict) else 'unknown'}"
        )

        # Check save result and raise exception if failed
        if isinstance(sink_result, dict) and sink_result.get("status") == "error":
            error_msg = sink_result.get("error", "Save operation failed")
            logger.error(
                f"ITERATOR: per-item save failed for iteration {iter_index}: {error_msg}"
            )

            # Emit explicit save_failed event
            if log_event_callback:
                log_event_callback(
                    "save_failed",
                    None,
                    f"save_iter_{iter_index}",
                    "save",
                    "error",
                    0,
                    iter_ctx,
                    None,
                    {"iteration_index": iter_index, "error": error_msg},
                    None,
                )

            raise Exception(f"Save failed: {error_msg}")

        # Emit explicit save_completed event
        if log_event_callback:
            log_event_callback(
                "save_completed",
                None,
                f"save_iter_{iter_index}",
                "save",
                "success",
                0,
                iter_ctx,
                sink_result,
                {"iteration_index": iter_index},
                None,
            )

        return sink_result

    except Exception as e:
        # Emit explicit save_error event for unexpected failures
        if log_event_callback:
            log_event_callback(
                "save_error",
                None,
                f"save_iter_{iter_index}",
                "save",
                "error",
                0,
                iter_ctx,
                None,
                {"iteration_index": iter_index, "error": str(e)},
                None,
            )
        raise


def run_one_iteration(
    iter_index: int,
    iter_payload: List[Tuple[int, Any]],
    context: Dict[str, Any],
    task_config: Dict[str, Any],
    config: Dict[str, Any],
    jinja_env: Environment,
    log_event_callback: Optional[Callable] = None,
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
    iterator_name = config["iterator_name"]
    nested_task = config["nested_task"]
    enumerate_flag = config["enumerate_flag"]
    chunk_n = config["chunk_n"]

    print(f"\n!!! RUN_ONE_ITERATION START: iter_index={iter_index}")
    print(
        f"!!! nested_task keys={list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}"
    )
    print(f"!!! has_sink={bool(nested_task.get('sink'))}\n")

    logger.critical(f"ITERATOR.EXECUTION: run_one_iteration iter_index={iter_index}")
    logger.critical(
        f"ITERATOR.EXECUTION: nested_task keys={list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}"
    )
    logger.critical(
        f"ITERATOR.EXECUTION: nested_task.get('sink')={nested_task.get('sink')}"
    )
    logger.critical(f"ITERATOR.EXECUTION: has_sink={bool(nested_task.get('sink'))}")

    # Emit explicit iteration_started event
    if log_event_callback:
        log_event_callback(
            "iteration_started",
            None,
            f"iter_{iter_index}",
            "iteration",
            "in_progress",
            0,
            context,
            None,
            {"iteration_index": iter_index, "has_sink": bool(nested_task.get('sink'))},
            None,
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
        context,
        iterator_name,
        item_for_task,
        iter_index,
        config.get("total_count", len(iter_payload)),
        enumerate_flag,
        chunk_n,
        items_in_payload,
        task_config,
    )

    # Build nested args
    nested_args = build_nested_args(
        nested_task, iter_ctx, item_for_task, jinja_env
    )

    # Execute nested task
    try:
        nested_result = execute_nested_task(
            nested_task, iter_ctx, nested_args, jinja_env, iter_index
        )
    except Exception as e_nested:
        logger.error(
            f"ITERATOR: Nested task failed at logical index {iter_index}: {e_nested}",
            exc_info=True,
        )

        # Emit explicit iteration_failed event
        if log_event_callback:
            log_event_callback(
                "iteration_failed",
                None,
                f"iter_{iter_index}",
                "iteration",
                "error",
                0,
                context,
                None,
                {"iteration_index": iter_index, "error": str(e_nested)},
                None,
            )

        return {
            "index": iter_index,
            "original_indices": [i for i, _ in iter_payload],
            "error": str(e_nested),
            "status": "error",
        }

    # Execute per-item save if configured (as single transaction with task)
    print(f"\n!!! BEFORE SAVE CALL: iter_index={iter_index}")
    print(
        f"!!! nested_task keys={list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}"
    )
    print(f"!!! has_sink={bool(nested_task.get('sink'))}")
    print(f"!!! sink_config={nested_task.get('sink')}\n")

    logger.critical(f"ITERATOR.EXECUTION: About to call execute_per_item_sink")
    logger.critical(
        f"ITERATOR.EXECUTION: nested_task keys before save: {list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}"
    )
    logger.critical(
        f"ITERATOR.EXECUTION: nested_task['sink'] = {nested_task.get('sink')}"
    )
    try:
        sink_result = execute_per_item_sink(
            nested_task,
            nested_result,
            iter_ctx,
            nested_args,
            jinja_env,
            log_event_callback,
            iter_index,
        )
    except Exception as e_save:
        logger.error(
            f"ITERATOR: Save failed at logical index {iter_index}: {e_save}",
            exc_info=True,
        )

        # Emit explicit iteration_failed event (save failure fails the iteration)
        if log_event_callback:
            log_event_callback(
                "iteration_failed",
                None,
                f"iter_{iter_index}",
                "iteration",
                "error",
                0,
                context,
                None,
                {"iteration_index": iter_index, "error": f"Save failed: {str(e_save)}"},
                None,
            )
        return {
            "index": iter_index,
            "original_indices": [i for i, _ in iter_payload],
            "error": f"Save failed: {str(e_save)}",
            "status": "error",
        }

    # Normalize result
    try:
        res = (
            nested_result.get("data")
            if isinstance(nested_result, dict) and nested_result.get("data") is not None
            else nested_result
        )
    except Exception:
        res = nested_result

    # Include save metadata in result if save was executed
    result_dict = {
        "index": iter_index,
        "original_indices": [i for i, _ in iter_payload],
        "result": res,
        "status": "success",
    }

    # Add save info to result metadata if save was performed
    if isinstance(sink_result, dict) and sink_result.get("status") == "success":
        result_dict["save_meta"] = sink_result.get("meta", {})

    # Emit explicit iteration_completed event
    if log_event_callback:
        log_event_callback(
            "iteration_completed",
            None,
            f"iter_{iter_index}",
            "iteration",
            "success",
            0,
            context,
            result_dict,
            {"iteration_index": iter_index, "has_sink": bool(nested_task.get('sink'))},
            None,
        )

    return result_dict
