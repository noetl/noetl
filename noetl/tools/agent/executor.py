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
import os
from typing import Any, Dict, Optional, Tuple

from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger


# Default catalog path for the self-troubleshoot agent. Override at the
# task level via ``on_failure.troubleshoot_path`` when a deployment
# wants a different diagnostic agent (e.g. a domain-specific one).
_DEFAULT_TROUBLESHOOT_PATH = "automation/agents/troubleshoot/diagnose_execution"

# Global env-level opt-in. Per-task ``on_failure.troubleshoot: false``
# always wins over the env var so operators can disable the auto-
# dispatch for individual playbooks even when the deployment turns
# it on globally.
_AUTO_TROUBLESHOOT_ENV = "NOETL_AGENT_AUTO_TROUBLESHOOT"

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
    # `noetl` invokes a peer NoETL playbook as an agent — no Python
    # entrypoint loading; the entrypoint is read as a catalog playbook
    # path and dispatched as a sub-playbook. See
    # `_invoke_noetl_playbook` below and the
    # sync/issues/2026-05-03-noetl-as-ai-os-architecture-spike.md
    # write-up for the full framing (Gap 1: playbook ≡ agent).
    if framework not in {"adk", "langchain", "custom", "noetl"}:
        raise ValueError(
            "agent.framework must be one of: adk, langchain, custom, noetl "
            f"(got: {framework!r})"
        )
    return framework


def _should_auto_troubleshoot(
    *,
    task_config: Dict[str, Any],
    entrypoint: str,
    troubleshoot_path: str,
) -> bool:
    """Decide whether to auto-dispatch the troubleshoot agent on failure.

    Three-way precedence:

    1. **Per-task explicit setting** — ``task_config.on_failure.troubleshoot``
       (bool). If present, this wins regardless of the env. Operators
       set ``troubleshoot: false`` on individual agents that should
       never auto-diagnose (e.g. tight inner loops where the cost of a
       diagnosis call would dominate).
    2. **Env-level default** — ``NOETL_AGENT_AUTO_TROUBLESHOOT`` truthy
       turns auto-diagnosis on for every ``tool: agent framework=noetl``
       call that doesn't override at the task level.
    3. **Default off** — diagnostics opt-in only when the operator
       explicitly turns them on. Avoids surprise cost / latency on
       deployments that haven't onboarded the troubleshoot agent.

    Always skipped (regardless of the above) when the failing entrypoint
    is *itself* the troubleshoot path — we don't troubleshoot the
    troubleshooter. Without this guard a failed troubleshoot run would
    re-dispatch itself, recursing until the worker hits a stack limit
    or a per-execution duration ceiling.
    """
    if entrypoint == troubleshoot_path:
        return False

    on_failure = task_config.get("on_failure") if isinstance(task_config, dict) else None
    if isinstance(on_failure, dict) and "troubleshoot" in on_failure:
        return bool(on_failure.get("troubleshoot"))

    env_value = os.environ.get(_AUTO_TROUBLESHOOT_ENV, "").strip().lower()
    return env_value in ("1", "true", "yes", "on")


def _dispatch_troubleshoot_diagnosis(
    *,
    failed_execution_id: Optional[str],
    failed_entrypoint: str,
    troubleshoot_path: str,
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Any,
) -> Optional[Dict[str, Any]]:
    """Run the troubleshoot agent against a freshly failed sub-execution.

    Returns the diagnosis dict (the inner ``data`` field of the
    troubleshoot agent's envelope, which carries
    ``{category, confidence, root_cause, suggested_action, source}``)
    or ``None`` if the diagnosis itself fails. We swallow exceptions
    here because a failing diagnostic should never *replace* the
    original failure with a diagnosis-tool error — the original error
    is what the caller actually wants to see.

    The troubleshoot agent's workload knobs flow through
    ``task_config.on_failure``: operators can pin a specific Ollama
    model, raise / lower the confidence threshold, or disable
    escalation per-call. The contract mirrors the troubleshoot
    agent's own workload schema (see
    ``automation/agents/troubleshoot/diagnose_execution.yaml``).
    """
    if not failed_execution_id:
        # Without an execution_id the troubleshoot agent has nothing
        # to diagnose. The fetch_events step would 422; surface the
        # absence here so we don't waste a worker on a guaranteed bad
        # call.
        logger.warning(
            "AGENT.EXECUTE auto-troubleshoot skipped: failed sub-playbook "
            "did not return an execution_id (entrypoint=%s)",
            failed_entrypoint,
        )
        return None

    try:
        from noetl.core.workflow.playbook import execute_playbook_task
    except Exception:
        logger.exception("AGENT.EXECUTE auto-troubleshoot import failed")
        return None

    on_failure = task_config.get("on_failure") if isinstance(task_config, dict) else {}
    on_failure = on_failure if isinstance(on_failure, dict) else {}

    diagnose_input: Dict[str, Any] = {
        "execution_id": str(failed_execution_id),
    }
    # Pass-through workload overrides: operators can pin Ollama model,
    # tighten the confidence threshold, swap escalation target. We
    # filter to the troubleshoot agent's known knobs to avoid
    # accidentally leaking arbitrary on_failure config into the
    # workload (where it would be silently ignored anyway).
    for key in (
        "ollama_model",
        "ollama_mcp_server",
        "confidence_threshold",
        "escalate_to",
        "openai_credential",
        "openai_model",
        "noetl_url",
    ):
        if key in on_failure:
            diagnose_input[key] = on_failure[key]

    sub_task_config: Dict[str, Any] = {
        "task": "agent_auto_troubleshoot",
        "path": troubleshoot_path,
        "input": diagnose_input,
    }

    try:
        sub_result = execute_playbook_task(
            sub_task_config,
            context,
            jinja_env,
            diagnose_input,
        )
    except Exception:
        logger.exception(
            "AGENT.EXECUTE auto-troubleshoot dispatch failed for execution_id=%s",
            failed_execution_id,
        )
        return None

    if not isinstance(sub_result, dict):
        return None
    if sub_result.get("status") not in ("success", "ok"):
        # Diagnostic itself failed; leave the envelope untouched.
        return None

    data = sub_result.get("data")
    return data if isinstance(data, dict) else None


def _invoke_noetl_playbook(
    *,
    entrypoint: str,
    payload: Any,
    invoke_kwargs: Dict[str, Any],
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Any,
) -> Dict[str, Any]:
    """Dispatch a peer NoETL playbook as the agent runtime.

    `entrypoint` is interpreted as a catalog playbook path (e.g.
    ``agents/local_llm/gemma_chat``). The dispatch goes through the
    same machinery `tool: kind: playbook` uses for fire-and-forget
    execution — `execute_playbook_task` from
    `noetl.core.workflow.playbook`. Result shape is normalised back
    into the agent envelope (`status`, `data`, `execution_id`,
    `duration`, optional `error`).

    Why not promote this to `nats_worker._execute_tool` and use
    `self._execute_playbook` (return-step semantics)? Because the
    agent executor needs to be importable from the local rust
    binary's runtime path too (no `self`); routing through the
    plugin function keeps the call surface symmetrical. Callers
    that need block-on-result semantics with a particular sub-step
    output should use `tool: kind: playbook` with `return_step:`
    directly.
    """
    from noetl.core.workflow.playbook import execute_playbook_task

    # The plugin's task_config contract expects `path` (catalog
    # playbook path) plus an optional `input` dict. Build that out
    # of `entrypoint` + the agent's payload + invoke_kwargs.
    sub_input: Dict[str, Any] = {}
    if isinstance(payload, dict):
        sub_input.update(payload)
    elif payload is not None:
        sub_input["input"] = payload
    if isinstance(invoke_kwargs, dict):
        # invoke_kwargs win — they're the agent caller's per-call
        # overrides on top of whatever the payload carries.
        sub_input.update(invoke_kwargs)

    sub_task_config: Dict[str, Any] = {
        "task": task_config.get("name") or "agent_noetl_playbook",
        "path": entrypoint,
        "input": sub_input,
    }
    # Carry through caller-supplied catalog version if present so an
    # agent invocation pinned to a specific playbook revision stays
    # pinned through the dispatch.
    if "version" in task_config:
        sub_task_config["version"] = task_config["version"]

    sub_result = execute_playbook_task(
        sub_task_config,
        context,
        jinja_env,
        sub_input,
    )

    # Normalise the plugin's status-wording into the agent envelope.
    # execute_playbook_task returns 'success'/'error'; agent callers
    # expect 'ok'/'error'.
    if isinstance(sub_result, dict):
        plugin_status = sub_result.get("status")
        normalised_status = "ok" if plugin_status == "success" else (
            plugin_status if plugin_status else "error"
        )
        envelope: Dict[str, Any] = {
            "status": normalised_status,
            "framework": "noetl",
            "entrypoint": entrypoint,
            "data": sub_result.get("data"),
            "execution_id": sub_result.get("execution_id"),
            "duration": sub_result.get("duration"),
        }
        if normalised_status != "ok":
            envelope["error"] = {
                "kind": "agent.execution",
                "code": "PLAYBOOK_FAILED",
                "message": sub_result.get("error") or "sub-playbook returned non-success status",
                "retryable": False,
            }

            # Gap 4.1: auto-dispatch the troubleshoot agent on failure
            # when opt-in is set. The diagnosis attaches under
            # ``error.diagnosis`` so callers don't have to look for a
            # separate envelope — the failure and its analysis travel
            # together. Best-effort: if the troubleshoot agent itself
            # fails or isn't registered, the original error stays
            # exactly as it was.
            on_failure = task_config.get("on_failure") if isinstance(task_config, dict) else {}
            on_failure = on_failure if isinstance(on_failure, dict) else {}
            troubleshoot_path = str(
                on_failure.get("troubleshoot_path") or _DEFAULT_TROUBLESHOOT_PATH
            )
            if _should_auto_troubleshoot(
                task_config=task_config,
                entrypoint=entrypoint,
                troubleshoot_path=troubleshoot_path,
            ):
                diagnosis = _dispatch_troubleshoot_diagnosis(
                    failed_execution_id=envelope.get("execution_id"),
                    failed_entrypoint=entrypoint,
                    troubleshoot_path=troubleshoot_path,
                    task_config=task_config,
                    context=context,
                    jinja_env=jinja_env,
                )
                if diagnosis is not None:
                    envelope["error"]["diagnosis"] = diagnosis
        return envelope

    # Defensive: plugin returned something unexpected.
    return {
        "status": "error",
        "framework": "noetl",
        "entrypoint": entrypoint,
        "error": {
            "kind": "agent.execution",
            "code": "UNEXPECTED_RESULT_SHAPE",
            "message": f"execute_playbook_task returned non-dict: {type(sub_result).__name__}",
            "retryable": False,
        },
    }


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

    # `framework: noetl` short-circuits the Python-entrypoint path
    # entirely — entrypoint is treated as a catalog playbook path
    # and dispatched as a sub-playbook. This is the playbook-as-
    # agent path; see _invoke_noetl_playbook above and the
    # sync/issues spike for context.
    if framework == "noetl":
        if not entrypoint or not isinstance(entrypoint, str):
            return {
                "status": "error",
                "error": {
                    "kind": "agent.configuration",
                    "code": "INVALID_ENTRYPOINT",
                    "message": (
                        "agent.framework=noetl requires agent.entrypoint to be a "
                        "catalog playbook path string (got: "
                        f"{type(entrypoint).__name__})"
                    ),
                    "retryable": False,
                },
            }
        try:
            return _invoke_noetl_playbook(
                entrypoint=entrypoint,
                payload=payload,
                invoke_kwargs=invoke_kwargs,
                task_config=merged,
                context=context or {},
                jinja_env=jinja_env,
            )
        except Exception as exc:
            logger.error(
                "AGENT.EXECUTE noetl-framework dispatch failed: entrypoint=%s error=%s",
                entrypoint, exc, exc_info=True,
            )
            return {
                "status": "error",
                "framework": "noetl",
                "entrypoint": entrypoint,
                "error": {
                    "kind": "agent.execution",
                    "code": type(exc).__name__,
                    "message": str(exc),
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
