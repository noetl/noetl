"""
Agent framework bridge executor for NoETL jobs.

This tool provides a thin compatibility layer for orchestrating external
agent runtimes (for example Google ADK and LangChain) from NoETL steps.

Expected config shape:

tool:
  kind: agent
  framework: adk | langchain | custom
  entrypoint: "python.module.path:attribute"
  entrypoint_mode: factory | callable  # default: factory
  entrypoint_args: {}                  # kwargs passed to factory
  invoke_method: "run_async"           # optional explicit method override
  payload: {...}                       # input payload for invocation
  invoke_kwargs: {}                    # extra kwargs for invocation
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any, Dict, Optional, Tuple

from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def _parse_entrypoint(entrypoint: str) -> Tuple[str, str]:
    """Parse `module:attribute` entrypoint notation."""
    if not isinstance(entrypoint, str) or not entrypoint.strip():
        raise ValueError("agent.entrypoint is required and must be a non-empty string")
    if ":" not in entrypoint:
        raise ValueError(
            "agent.entrypoint must use 'module.path:attribute' notation "
            f"(got: {entrypoint!r})"
        )
    module_name, attribute_name = entrypoint.split(":", 1)
    module_name = module_name.strip()
    attribute_name = attribute_name.strip()
    if not module_name or not attribute_name:
        raise ValueError(
            "agent.entrypoint must include both module path and attribute name "
            f"(got: {entrypoint!r})"
        )
    return module_name, attribute_name


def _load_entrypoint(entrypoint: str) -> Any:
    """Import module and resolve configured entrypoint attribute."""
    module_name, attribute_name = _parse_entrypoint(entrypoint)
    module = importlib.import_module(module_name)
    if not hasattr(module, attribute_name):
        raise AttributeError(
            f"Entrypoint attribute '{attribute_name}' not found in module '{module_name}'"
        )
    return getattr(module, attribute_name)


def _coerce_framework(value: Any) -> str:
    framework = str(value or "custom").strip().lower()
    if framework not in {"adk", "langchain", "custom"}:
        raise ValueError(
            "agent.framework must be one of: adk, langchain, custom "
            f"(got: {framework!r})"
        )
    return framework


def _call_plan(
    fn: Any,
    payload: Any,
    kwargs: Optional[Dict[str, Any]],
    preferred_input_key: Optional[str] = None,
) -> Tuple[tuple[Any, ...], Dict[str, Any]]:
    """Build a best-effort call plan using signature inspection."""
    kwargs = dict(kwargs or {})
    sig = inspect.signature(fn)
    params = sig.parameters
    has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    has_positional = any(
        p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
        for p in params.values()
    )

    if not has_var_keyword:
        kwargs = {k: v for k, v in kwargs.items() if k in params}

    if payload is None:
        return (), kwargs

    if isinstance(payload, dict):
        payload_kwargs = dict(payload)
        if not has_var_keyword:
            payload_kwargs = {k: v for k, v in payload_kwargs.items() if k in params}
        for key, value in payload_kwargs.items():
            kwargs.setdefault(key, value)
        if payload_kwargs:
            return (), kwargs

    for key in (preferred_input_key, "input", "payload", "state", "request", "message", "query"):
        if not key:
            continue
        if has_var_keyword or key in params:
            kwargs[key] = payload
            return (), kwargs

    for key in ("new_message", "new_input", "content", "prompt"):
        if has_var_keyword or key in params:
            kwargs[key] = payload
            return (), kwargs

    if has_positional:
        return (payload,), kwargs

    raise TypeError(
        f"Callable '{getattr(fn, '__name__', type(fn).__name__)}' does not accept payload input"
    )


async def _invoke_callable(
    fn: Any,
    payload: Any = None,
    kwargs: Optional[Dict[str, Any]] = None,
    preferred_input_key: Optional[str] = None,
) -> Any:
    """Invoke sync or async callable with inferred payload argument mapping."""
    args, call_kwargs = _call_plan(
        fn=fn,
        payload=payload,
        kwargs=kwargs,
        preferred_input_key=preferred_input_key,
    )
    if inspect.isasyncgenfunction(fn):
        result = fn(*args, **call_kwargs)
    elif inspect.iscoroutinefunction(fn):
        result = await fn(*args, **call_kwargs)
    else:
        result = fn(*args, **call_kwargs)
    if inspect.isawaitable(result):
        result = await result
    return await _materialize_result(result)


def _serialize_result_item(item: Any) -> Any:
    if hasattr(item, "model_dump") and callable(getattr(item, "model_dump")):
        try:
            return item.model_dump()
        except Exception:
            return item
    if hasattr(item, "dict") and callable(getattr(item, "dict")):
        try:
            return item.dict()
        except Exception:
            return item
    return item


async def _materialize_result(result: Any) -> Any:
    if inspect.isasyncgen(result):
        items = []
        async for item in result:
            items.append(_serialize_result_item(item))
        return items
    if inspect.isgenerator(result):
        return [_serialize_result_item(item) for item in result]
    return _serialize_result_item(result)


def _framework_methods(framework: str) -> list[str]:
    if framework == "langchain":
        return ["ainvoke", "invoke", "arun", "run"]
    if framework == "adk":
        return ["run_async", "arun", "run", "execute", "ainvoke", "invoke"]
    return ["ainvoke", "invoke", "run_async", "run", "execute"]


async def _invoke_runtime(
    runtime_obj: Any,
    framework: str,
    payload: Any,
    invoke_kwargs: Optional[Dict[str, Any]],
    invoke_method: Optional[str],
    preferred_input_key: Optional[str],
) -> Any:
    """Invoke runtime object based on framework defaults or explicit method."""
    if invoke_method:
        method = getattr(runtime_obj, invoke_method, None)
        if method is None or not callable(method):
            raise AttributeError(
                f"Configured invoke_method '{invoke_method}' is not callable on runtime object"
            )
        return await _invoke_callable(
            method,
            payload=payload,
            kwargs=invoke_kwargs,
            preferred_input_key=preferred_input_key,
        )

    for method_name in _framework_methods(framework):
        method = getattr(runtime_obj, method_name, None)
        if method is None or not callable(method):
            continue
        return await _invoke_callable(
            method,
            payload=payload,
            kwargs=invoke_kwargs,
            preferred_input_key=preferred_input_key,
        )

    if callable(runtime_obj):
        return await _invoke_callable(
            runtime_obj,
            payload=payload,
            kwargs=invoke_kwargs,
            preferred_input_key=preferred_input_key,
        )

    raise TypeError(
        "Agent runtime object is not invokable. Provide invoke_method or return a callable runtime."
    )


async def execute_agent_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback=None,
) -> Dict[str, Any]:
    """
    Execute external agent runtime (ADK/LangChain/custom).

    Returns:
      - {"status": "ok", "data": ...} on success
      - {"status": "error", "error": {...}} on recoverable execution/setup failures
    """
    del log_event_callback  # reserved for parity with other tool executors

    merged = dict(task_config or {})
    if isinstance(task_with, dict):
        merged.update(task_with)

    # Render all templates once against current context.
    rendered = render_template(jinja_env, merged, context or {})
    if not isinstance(rendered, dict):
        rendered = merged

    framework = _coerce_framework(rendered.get("framework"))
    entrypoint = rendered.get("entrypoint")
    entrypoint_mode = str(rendered.get("entrypoint_mode", "factory")).strip().lower()
    entrypoint_args = rendered.get("entrypoint_args") or {}
    payload = rendered.get("payload", rendered.get("input"))
    invoke_kwargs = rendered.get("invoke_kwargs") or {}
    invoke_method = rendered.get("invoke_method")
    input_arg = rendered.get("input_arg")

    if entrypoint_mode not in {"factory", "callable"}:
        return {
            "status": "error",
            "error": {
                "kind": "agent.configuration",
                "code": "INVALID_ENTRYPOINT_MODE",
                "message": (
                    "agent.entrypoint_mode must be 'factory' or 'callable' "
                    f"(got: {entrypoint_mode!r})"
                ),
                "retryable": False,
            },
        }

    if not isinstance(entrypoint_args, dict):
        return {
            "status": "error",
            "error": {
                "kind": "agent.configuration",
                "code": "INVALID_ENTRYPOINT_ARGS",
                "message": "agent.entrypoint_args must be an object",
                "retryable": False,
            },
        }

    if not isinstance(invoke_kwargs, dict):
        return {
            "status": "error",
            "error": {
                "kind": "agent.configuration",
                "code": "INVALID_INVOKE_KWARGS",
                "message": "agent.invoke_kwargs must be an object",
                "retryable": False,
            },
        }

    try:
        entry = _load_entrypoint(entrypoint)

        if entrypoint_mode == "factory":
            # Factory mode: entrypoint builds runtime object.
            if inspect.isclass(entry):
                runtime_obj = entry(**entrypoint_args)
            elif callable(entry):
                runtime_obj = await _invoke_callable(
                    entry,
                    payload=None,
                    kwargs=entrypoint_args,
                    preferred_input_key=None,
                )
            else:
                runtime_obj = entry
        else:
            # Callable mode: entrypoint itself is runtime callable/object.
            runtime_obj = entry

        result = await _invoke_runtime(
            runtime_obj=runtime_obj,
            framework=framework,
            payload=payload,
            invoke_kwargs=invoke_kwargs,
            invoke_method=invoke_method,
            preferred_input_key=input_arg,
        )

        return {
            "status": "ok",
            "framework": framework,
            "entrypoint": entrypoint,
            "data": result,
        }

    except Exception as exc:
        logger.error(
            "AGENT.EXECUTE failed framework=%s entrypoint=%s error=%s",
            framework,
            entrypoint,
            exc,
            exc_info=True,
        )
        return {
            "status": "error",
            "framework": framework,
            "entrypoint": entrypoint,
            "error": {
                "kind": "agent.execution",
                "code": type(exc).__name__,
                "message": str(exc),
                "retryable": False,
            },
        }
