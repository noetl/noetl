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
import time
from typing import Any, Callable, Dict, Optional, Tuple

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


def _wait_for_sub_execution_terminal(
    execution_id: str,
    *,
    timeout_seconds: float = 300.0,
    poll_interval_seconds: float = 1.0,
) -> Dict[str, Any]:
    """Poll noetl-server's /api/executions/{id}/status until terminal.

    `execute_playbook_task` HTTP-POSTs to /api/execute and returns
    immediately with the started-state response (status="started",
    execution_id, commands_generated). The agent contract demands a
    synchronous outcome — the parent step needs to see whether the
    child succeeded, failed, or what the actual data is. Without
    waiting, the auto-troubleshoot hook (Gap 4.1) never fires
    because the parent's normalised_status stays "started" instead
    of "error".

    Returns the status doc from /api/executions/{id}/status (with
    keys ``completed``, ``failed``, optionally ``current_step`` /
    ``error``) once the execution reaches terminal status, OR a
    synthetic timeout doc if the deadline passes. The caller then
    builds the agent envelope based on the terminal outcome.

    Imports are lazy so this module stays importable in test
    harnesses that don't have requests available (the agent
    executor's optional-dependency contract).
    """
    import time

    try:
        import requests
    except ImportError:
        logger.warning(
            "AGENT.WAIT: requests not available; cannot poll sub-execution %s; "
            "returning synthetic timeout",
            execution_id,
        )
        return {"completed": False, "failed": True, "timeout": True,
                "error": "requests module unavailable"}

    server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8083").rstrip("/")
    if not server_url.endswith("/api"):
        server_url = server_url + "/api"
    status_url = f"{server_url}/executions/{execution_id}/status"

    deadline = time.time() + max(1.0, float(timeout_seconds))
    last_doc: Dict[str, Any] = {}
    poll_n = 0

    while time.time() < deadline:
        poll_n += 1
        try:
            resp = requests.get(status_url, timeout=10)
            resp.raise_for_status()
            last_doc = resp.json()
        except Exception as exc:
            logger.warning(
                "AGENT.WAIT: poll #%d for %s failed: %s",
                poll_n, execution_id, exc,
            )
            time.sleep(max(0.1, float(poll_interval_seconds)))
            continue

        if last_doc.get("completed") or last_doc.get("failed"):
            logger.debug(
                "AGENT.WAIT: %s reached terminal after %d polls (completed=%s, failed=%s)",
                execution_id, poll_n,
                last_doc.get("completed"), last_doc.get("failed"),
            )
            return last_doc

        time.sleep(max(0.1, float(poll_interval_seconds)))

    logger.warning(
        "AGENT.WAIT: %s did not reach terminal within %.1fs (last status: %s)",
        execution_id, timeout_seconds, last_doc,
    )
    last_doc["timeout"] = True
    last_doc["failed"] = True   # treat timeouts as failures so caller's
                                 # error-branch + auto-troubleshoot fire
    return last_doc


def _normalise_result_reference(reference: Any) -> Optional[Dict[str, Any]]:
    """Convert compact event ``result.reference`` into ResultStore ref shape."""
    if not isinstance(reference, dict):
        return None
    locator = str(reference.get("locator") or reference.get("ref") or "").strip()
    if not locator.startswith("noetl://"):
        return None
    store = str(reference.get("store") or "kv").strip().lower() or "kv"
    return {
        "kind": "temp_ref" if store == "memory" else "result_ref",
        "ref": locator,
        "store": store,
    }


def _resolve_result_reference_sync(reference: Any) -> Any:
    """Resolve a compact event result reference from sync agent code."""
    ref = _normalise_result_reference(reference)
    if not isinstance(ref, dict):
        return None
    try:
        import asyncio
        import concurrent.futures
        from noetl.core.storage.result_store import default_store

        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, default_store.resolve(ref))
                return future.result(timeout=10.0)
        except RuntimeError:
            return asyncio.run(default_store.resolve(ref))
    except Exception as exc:
        logger.warning(
            "AGENT.RESULT.FETCH: failed to resolve result reference %s: %s",
            ref.get("ref") if isinstance(ref, dict) else reference,
            exc,
        )
        return None


def _compact_mcp_result_for_agent_context(result: Any) -> Any:
    """Bound MCP-like child results so parent steps can template them.

    Agent-to-NoETL calls use the child playbook's terminal result as the
    parent agent step's ``data``. Some MCP tools legitimately return very
    large collections; carrying the whole payload through the parent step
    makes the parent result externalize again, which hides ``data`` from
    immediate downstream branch predicates. Keep the MCP contract fields
    and the first few collection items, preserving counts for observability.
    The full child result remains available from the child execution's own
    ResultRef; this is the control-plane view for parent routing/rendering.
    """
    if not isinstance(result, dict):
        return result

    data = result.get("data")
    if not isinstance(data, dict):
        return result

    collection_keys = ("items", "offers", "hotels", "activities", "locations")
    collection_key = next(
        (key for key in collection_keys if isinstance(data.get(key), list)),
        None,
    )
    if collection_key is None:
        return result

    max_items = 10
    collection = data.get(collection_key) or []
    compact_data: Dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, list):
            if key == collection_key:
                if key in {"offers", "items"}:
                    compact_data[key] = value[:max_items]
                else:
                    # Travel renderers and most MCP consumers expect the
                    # canonical collection field to be `items`; Amadeus uses
                    # domain-specific names for hotels/activities.
                    compact_data["items"] = value[:max_items]
                compact_data.setdefault(f"{key}_total", len(value))
            else:
                compact_data[f"{key}_total"] = len(value)
            continue
        compact_data[key] = value

    compact: Dict[str, Any] = {
        key: result[key]
        for key in ("status", "isError", "_meta")
        if key in result
    }
    compact["data"] = compact_data
    return compact


def _expand_flattened_terminal_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Rehydrate auto-extracted ``data_*`` / ``_meta_*`` fields.

    When a child result reference cannot be resolved, the terminal event
    still carries scalar fields produced by ResultHandler's auto-extractor
    (for example ``data_ok`` and ``data_status_code``). Expand those back
    into an MCP-shaped envelope so parent predicates can still distinguish
    a successful upstream call from a real failure.
    """
    expanded: Dict[str, Any] = {}
    data: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}

    for key, value in context.items():
        key_str = str(key)
        if key_str.startswith("data_"):
            data[key_str.removeprefix("data_")] = value
        elif key_str.startswith("_meta_"):
            meta[key_str.removeprefix("_meta_")] = value
        else:
            expanded[key_str] = value

    if data:
        expanded["data"] = data
    if meta:
        existing_meta = expanded.get("_meta")
        if isinstance(existing_meta, dict):
            merged_meta = dict(existing_meta)
            merged_meta.update(meta)
            expanded["_meta"] = merged_meta
        else:
            expanded["_meta"] = meta
    return expanded


def _fetch_sub_execution_terminal_result(
    execution_id: str,
    *,
    request_timeout_seconds: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """Fetch the sub-execution's terminal-step result.context from events.

    The /api/executions/{id}/status endpoint compacts ``state.variables``
    (see `_compact_status_variables` in `noetl/server/api/core/utils.py`):
    any value over ``_STATUS_VALUE_MAX_BYTES`` is replaced with a
    `{_truncated, _original_size_bytes, _preview}` stub. That endpoint is
    fine for "did it complete?" checks, but it's the wrong source for the
    sub-execution's actual final result — large MCP envelopes (e.g.
    Amadeus activities with N items) get silently truncated and the
    parent's Jinja access (``.data.ok``, ``.data.items``) sees a stub
    instead of the real payload.

    The events table stores the uncompacted ``result.context`` for every
    ``command.completed`` / ``step.exit`` / ``call.done`` event. This
    helper walks the events page for the sub-execution, finds the last
    terminal step's ``result.context``, and returns it. The caller
    (``_invoke_noetl_playbook``) uses this as ``envelope.data`` so the
    parent step sees the full result.

    Returns ``None`` when the events page is unavailable or no qualifying
    terminal-step event exists, in which case the caller falls back to
    the (possibly truncated) status doc. Best-effort: this is a polish
    layer over the existing terminal-status polling, not a replacement.
    """
    try:
        import requests
    except ImportError:
        logger.debug(
            "AGENT.RESULT.FETCH: requests module unavailable; cannot "
            "extract terminal-step result"
        )
        return None

    server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8083").rstrip("/")
    if not server_url.endswith("/api"):
        server_url = server_url + "/api"
    # Page size 500 is the endpoint's max; we want all terminal events
    # in one page so we can scan back-to-front for the last result.
    events_url = (
        f"{server_url}/executions/{execution_id}/events"
        "?page_size=500&page=1"
    )

    try:
        resp = requests.get(events_url, timeout=max(1.0, float(request_timeout_seconds)))
        resp.raise_for_status()
        doc = resp.json()
    except Exception as exc:
        logger.warning(
            "AGENT.RESULT.FETCH: failed to fetch %s: %s",
            events_url, exc,
        )
        return None

    events = doc.get("events") if isinstance(doc, dict) else None
    if not isinstance(events, list):
        return None

    # Events are returned in some order (typically DESC by event_id from
    # the endpoint). Find the LAST terminal-step event — i.e. the highest
    # event_id whose type is in our terminal set AND whose node is not
    # the synthetic 'end'/'start' boundary nodes. The MCP playbooks'
    # render-as-tail pattern (round 6 from the travel arc) means the
    # tail step's result.context IS the playbook's externally visible
    # result.
    _TERMINAL_EVENT_TYPES = {"command.completed", "step.exit", "call.done"}
    _BOUNDARY_NODE_NAMES = {"start", "end", None, ""}

    candidate_event: Optional[Dict[str, Any]] = None
    candidate_event_id: int = -1

    for evt in events:
        if not isinstance(evt, dict):
            continue
        if evt.get("event_type") not in _TERMINAL_EVENT_TYPES:
            continue
        node_name = evt.get("node_name") or evt.get("step")
        if node_name in _BOUNDARY_NODE_NAMES:
            continue
        # event_id is monotonically increasing; the largest one is the
        # last terminal step event (the tail).
        try:
            evt_id = int(evt.get("event_id") or 0)
        except (TypeError, ValueError):
            evt_id = 0
        if evt_id > candidate_event_id:
            candidate_event_id = evt_id
            candidate_event = evt

    if candidate_event is None:
        return None

    result = candidate_event.get("result")
    if not isinstance(result, dict):
        return None
    resolved = _resolve_result_reference_sync(result.get("reference"))
    if resolved is not None:
        compact = _compact_mcp_result_for_agent_context(resolved)
        return compact if isinstance(compact, dict) else {"data": compact}
    context = result.get("context")
    if not isinstance(context, dict):
        return None
    return _expand_flattened_terminal_context(context)


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


# Default step name the troubleshoot playbook persists its diagnosis to.
# Configurable via task_config.on_failure.diagnosis_step or env var so
# bespoke troubleshoot playbooks can name the step differently.
_DEFAULT_DIAGNOSIS_STEP_NAME = "persist_diagnosis"
_DIAGNOSIS_STEP_ENV = "NOETL_TROUBLESHOOT_DIAGNOSIS_STEP"
# Adaptive persisted-diagnosis fetch backoff, tuned for cloud-managed
# inference latency. Warm path (Vertex AI ~1-3s, Ollama ~200-500ms)
# typically completes in 1-3 polls (~0.5-2s wall time). Cold path
# (~30s+ tail latency) completes in ~10-12 polls within the 60s
# deadline. Calibrated against the GKE Vertex AI arc's v2.36.1
# cold-start outlier (`diagnosis_lookup.attempts=16`) — see
# sync/issues/2026-05-07-noetl-adaptive-retry-backoff-tail-latency.md.
_DIAGNOSIS_BACKOFF_INITIAL_SLEEP = 0.5
_DIAGNOSIS_BACKOFF_MULTIPLIER = 1.5
_DIAGNOSIS_BACKOFF_MAX_SLEEP = 4.0
_DIAGNOSIS_BACKOFF_DEADLINE = 60.0
_REQUIRED_DIAGNOSIS_KEYS = (
    "category",
    "confidence",
    "root_cause",
    "suggested_action",
    "source",
)
_TROUBLESHOOT_ON_FAILURE_KEYS = {
    "confidence_threshold",
    "escalate_to",
    "openai_credential",
    "openai_model",
    "anthropic_credential",
    "anthropic_model",
    "noetl_url",
}
_TROUBLESHOOT_ON_FAILURE_PREFIXES = (
    "triage_",
    "ollama_",
)


def _should_forward_troubleshoot_workload_key(key: str) -> bool:
    """Return true for safe workload knobs forwarded to diagnose_execution."""
    return key in _TROUBLESHOOT_ON_FAILURE_KEYS or key.startswith(
        _TROUBLESHOOT_ON_FAILURE_PREFIXES
    )


def _fetch_persisted_diagnosis_from_doc(
    execution_id: str,
    *,
    diagnosis_step_name: str = _DEFAULT_DIAGNOSIS_STEP_NAME,
    request_timeout_seconds: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """Fetch the full execution doc and pull the persisted diagnosis dict.

    The troubleshoot playbook persists its result at
    result.context.diagnosis on a terminal event, usually from the
    persist_diagnosis step. Return None when the doc is unavailable or
    no qualifying diagnosis exists so the original error remains intact.
    """
    try:
        import requests
    except ImportError:
        logger.debug(
            "AGENT.DIAGNOSIS.FETCH: requests module unavailable; cannot "
            "extract persisted diagnosis"
        )
        return None

    server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8083").rstrip("/")
    if not server_url.endswith("/api"):
        server_url = server_url + "/api"
    doc_url = f"{server_url}/executions/{execution_id}"

    try:
        resp = requests.get(doc_url, timeout=max(1.0, float(request_timeout_seconds)))
        resp.raise_for_status()
        doc = resp.json()
    except Exception as exc:
        logger.warning(
            "AGENT.DIAGNOSIS.FETCH: failed to fetch %s: %s",
            doc_url, exc,
        )
        return None

    events = doc.get("events") if isinstance(doc, dict) else None
    if not isinstance(events, list):
        return None

    # Walk newest-first so we pick the terminal event over command.issued.
    for evt in reversed(events):
        if not isinstance(evt, dict):
            continue
        if evt.get("node_name") != diagnosis_step_name:
            continue
        if evt.get("event_type") not in ("command.completed", "step.exit", "call.done"):
            continue
        result_block = evt.get("result") if isinstance(evt.get("result"), dict) else {}
        ctx = result_block.get("context") if isinstance(result_block.get("context"), dict) else {}
        candidate = ctx.get("diagnosis") if isinstance(ctx.get("diagnosis"), dict) else None
        if candidate and set(_REQUIRED_DIAGNOSIS_KEYS).issubset(candidate.keys()):
            return candidate

    return None


def _diagnosis_fetch_meta(
    *,
    started_at: float,
    poll_count: int,
    deadline_seconds: float,
    hit_deadline: bool,
) -> Dict[str, Any]:
    elapsed = max(0.0, time.monotonic() - started_at)
    return {
        "poll_count": int(poll_count),
        "elapsed_seconds": round(elapsed, 3),
        "deadline_seconds": float(deadline_seconds),
        "hit_deadline": bool(hit_deadline),
    }


def _attach_diagnosis_fetch_meta(
    diagnosis: Dict[str, Any],
    fetch_meta: Dict[str, Any],
) -> Dict[str, Any]:
    result = dict(diagnosis)
    meta = result.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
    else:
        meta = dict(meta)
    meta["diagnosis_fetch"] = dict(fetch_meta)
    result["_meta"] = meta
    return result


def _fetch_persisted_diagnosis_with_backoff(
    execution_id: str,
    *,
    diagnosis_step_name: str = _DEFAULT_DIAGNOSIS_STEP_NAME,
    deadline_seconds: float = _DIAGNOSIS_BACKOFF_DEADLINE,
    initial_sleep_seconds: float = _DIAGNOSIS_BACKOFF_INITIAL_SLEEP,
    multiplier: float = _DIAGNOSIS_BACKOFF_MULTIPLIER,
    max_sleep_seconds: float = _DIAGNOSIS_BACKOFF_MAX_SLEEP,
    fetch_func: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Fetch a persisted diagnosis using adaptive exponential backoff."""
    fetch = fetch_func or _fetch_persisted_diagnosis_from_doc
    deadline_seconds = max(0.0, float(deadline_seconds))
    sleep_seconds = max(0.1, float(initial_sleep_seconds))
    multiplier = max(1.0, float(multiplier))
    max_sleep_seconds = max(sleep_seconds, float(max_sleep_seconds))

    started_at = time.monotonic()
    deadline_at = started_at + deadline_seconds
    poll_count = 0

    while True:
        poll_count += 1
        diagnosis = fetch(
            str(execution_id),
            diagnosis_step_name=diagnosis_step_name,
        )
        now = time.monotonic()
        if diagnosis is not None:
            return diagnosis, _diagnosis_fetch_meta(
                started_at=started_at,
                poll_count=poll_count,
                deadline_seconds=deadline_seconds,
                hit_deadline=False,
            )

        if now >= deadline_at:
            return None, _diagnosis_fetch_meta(
                started_at=started_at,
                poll_count=poll_count,
                deadline_seconds=deadline_seconds,
                hit_deadline=True,
            )

        remaining = max(0.0, deadline_at - now)
        time.sleep(min(sleep_seconds, remaining))
        sleep_seconds = min(sleep_seconds * multiplier, max_sleep_seconds)


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

    Returns the diagnosis dict carrying
    ``{category, confidence, root_cause, suggested_action, source}``
    or ``None`` if the diagnosis itself fails.

    Wait-for-terminal contract (mirrors Gap 1 fix in
    ``_invoke_noetl_playbook``): ``execute_playbook_task`` HTTP-POSTs
    to /api/execute and returns the started-state response immediately.
    We poll /api/executions/<id>/status until the diagnose
    sub-execution terminates, then fetch the full doc and extract the
    persisted diagnosis from the terminal event.

    We swallow exceptions here because a failing diagnostic should
    never *replace* the
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
    # Pass-through workload overrides: operators can pin a triage
    # backend/model, tune the confidence threshold, or swap escalation
    # target. Keep the allow-pattern narrow so arbitrary on_failure
    # data is not leaked into the diagnose workload, but make the
    # backend/model prefixes generic enough that new triage_* knobs do
    # not need compatibility mirrors through deprecated ollama_* names.
    for key, value in on_failure.items():
        if _should_forward_troubleshoot_workload_key(str(key)):
            diagnose_input[key] = value

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

    if not isinstance(sub_result, dict) or sub_result.get("status") not in ("success", "ok"):
        # Dispatch itself failed (HTTP error, plugin import error, etc.)
        # — leave the envelope untouched.
        return None

    data = sub_result.get("data")
    if isinstance(data, dict) and set(_REQUIRED_DIAGNOSIS_KEYS).issubset(data.keys()):
        return data

    diag_execution_id = (
        sub_result.get("execution_id")
        or (data or {}).get("execution_id")
    )
    if not diag_execution_id:
        logger.warning(
            "AGENT.DIAGNOSIS: dispatch succeeded but no execution_id in response; "
            "cannot wait for terminal or fetch persisted diagnosis"
        )
        return None

    # Wait for the diagnose sub-execution to reach terminal status before
    # fetching the persisted diagnosis. Default 60s; diagnoses are usually
    # quick, but local model paths can stretch.
    wait_timeout = float(on_failure.get("diagnosis_wait_timeout_seconds", 60.0))
    terminal = _wait_for_sub_execution_terminal(
        str(diag_execution_id),
        timeout_seconds=wait_timeout,
    )
    can_fetch_persisted = bool(
        (terminal.get("completed") and not terminal.get("failed"))
        or (
            terminal.get("failed")
            and terminal.get("completion_inferred")
            and not terminal.get("timeout")
        )
    )
    if not can_fetch_persisted:
        logger.warning(
            "AGENT.DIAGNOSIS: sub-execution %s did not complete cleanly "
            "(terminal=%s); returning no diagnosis",
            diag_execution_id, terminal,
        )
        return None

    diagnosis_step = str(
        on_failure.get("diagnosis_step")
        or os.environ.get(_DIAGNOSIS_STEP_ENV, "")
        or _DEFAULT_DIAGNOSIS_STEP_NAME
    )
    fetch_deadline = float(
        on_failure.get(
            "diagnosis_fetch_deadline_seconds",
            on_failure.get(
                "diagnosis_fetch_timeout_seconds",
                _DIAGNOSIS_BACKOFF_DEADLINE,
            ),
        )
    )
    fetch_initial_sleep = float(
        on_failure.get(
            "diagnosis_fetch_initial_sleep_seconds",
            on_failure.get(
                "diagnosis_fetch_interval_seconds",
                _DIAGNOSIS_BACKOFF_INITIAL_SLEEP,
            ),
        )
    )
    fetch_max_sleep = float(
        on_failure.get(
            "diagnosis_fetch_max_sleep_seconds",
            _DIAGNOSIS_BACKOFF_MAX_SLEEP,
        )
    )
    fetch_multiplier = float(
        on_failure.get(
            "diagnosis_fetch_backoff_multiplier",
            _DIAGNOSIS_BACKOFF_MULTIPLIER,
        )
    )
    diagnosis, fetch_meta = _fetch_persisted_diagnosis_with_backoff(
        str(diag_execution_id),
        diagnosis_step_name=diagnosis_step,
        deadline_seconds=fetch_deadline,
        initial_sleep_seconds=fetch_initial_sleep,
        multiplier=fetch_multiplier,
        max_sleep_seconds=fetch_max_sleep,
    )
    if diagnosis is not None:
        if fetch_meta.get("poll_count", 0) > 1:
            logger.info(
                "AGENT.DIAGNOSIS: fetched persisted diagnosis for %s "
                "after %d polls in %.3fs",
                diag_execution_id,
                fetch_meta.get("poll_count"),
                fetch_meta.get("elapsed_seconds"),
            )
        return _attach_diagnosis_fetch_meta(diagnosis, fetch_meta)
    if terminal.get("failed"):
        logger.warning(
            "AGENT.DIAGNOSIS: sub-execution %s failed and no persisted "
            "diagnosis was found (terminal=%s)",
            diag_execution_id,
            terminal,
        )
    return None


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

    **Optional-dependency contract.** AI features are optional in
    NoETL — a deployment without the workflow plugin available
    must not crash the worker. We import ``execute_playbook_task``
    lazily here and surface a structured error envelope on
    ImportError rather than letting the exception leak. The worker
    keeps running; the playbook step fails with a clear "this
    feature is not available" message; non-AI playbooks are
    completely unaffected.
    """
    try:
        from noetl.core.workflow.playbook import execute_playbook_task
    except ImportError as exc:
        # Workflow plugin not available in this deployment. Return a
        # clean error envelope so the caller sees a typed, retryable
        # failure rather than a worker-level traceback.
        logger.warning(
            "AGENT.EXECUTE framework=noetl unavailable — "
            "noetl.core.workflow.playbook could not be imported (%s). "
            "Returning structured error envelope.",
            exc,
        )
        return {
            "status": "error",
            "framework": "noetl",
            "entrypoint": entrypoint,
            "error": {
                "kind": "agent.dependency",
                "code": "WORKFLOW_PLUGIN_UNAVAILABLE",
                "message": (
                    "framework=noetl requires noetl.core.workflow.playbook; "
                    f"import failed: {exc}"
                ),
                "retryable": False,
            },
        }

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

    # `execute_playbook_task` HTTP-POSTs to /api/execute and returns
    # the started-state response immediately. We need to wait for the
    # sub-execution to reach terminal status so the agent contract
    # (parent step sees the child's actual outcome) holds. Otherwise
    # the auto-troubleshoot hook (Gap 4.1) never fires because the
    # status stays "started" instead of resolving to "ok"/"error".
    sub_execution_id: Optional[str] = None
    sub_terminal: Dict[str, Any] = {}
    if isinstance(sub_result, dict):
        plugin_status = sub_result.get("status")
        # `execute_playbook_task` reports "success" when the HTTP
        # dispatch succeeded (regardless of the inner sub-execution's
        # outcome). The actual sub-execution_id lives either at
        # top-level (some plugin versions) or inside `.data`.
        sub_execution_id = (
            sub_result.get("execution_id")
            or (sub_result.get("data") or {}).get("execution_id")
        )

        # If the dispatch succeeded and we have an execution_id, poll
        # for terminal. Errors and missing execution_ids fall through
        # to the existing normalisation logic below.
        if plugin_status == "success" and sub_execution_id:
            wait_timeout = float(task_config.get("wait_timeout_seconds", 300.0))
            sub_terminal = _wait_for_sub_execution_terminal(
                str(sub_execution_id),
                timeout_seconds=wait_timeout,
            )

    # Normalise the plugin's status-wording into the agent envelope.
    # Three sources of truth, in priority order:
    #   1. sub_terminal (if we polled to terminal): completed → ok,
    #      failed → error
    #   2. execute_playbook_task's plugin_status (success/error): pre-
    #      polling fall-back when no execution_id was available
    #   3. Default to "error" when the shape is unrecognised
    if isinstance(sub_result, dict):
        if sub_terminal:
            if sub_terminal.get("completed") and not sub_terminal.get("failed"):
                normalised_status = "ok"
            else:
                normalised_status = "error"
        else:
            plugin_status = sub_result.get("status")
            normalised_status = "ok" if plugin_status == "success" else (
                plugin_status if plugin_status else "error"
            )

        # Hydrate ``data`` from the sub-execution's terminal-step
        # ``result.context`` in the events table when available. The
        # ``/status`` endpoint compacts large ``state.variables`` values
        # to ``{_truncated, _original_size_bytes, _preview}`` stubs (see
        # ``_compact_status_variables`` in the server utils). Large MCP
        # envelopes — e.g. Amadeus activities — fit through the events
        # path uncompacted, and ``result.context`` is what the parent's
        # Jinja access (``envelope.data.ok``, ``envelope.data.items``)
        # actually wants to see. Falls back to the (possibly truncated)
        # status doc when the events fetch fails or returns no
        # terminal-step event. Only meaningful when we have an
        # execution_id to fetch against.
        envelope_data: Any
        if sub_execution_id:
            envelope_data = (
                _fetch_sub_execution_terminal_result(str(sub_execution_id))
                or sub_terminal
                or sub_result.get("data")
            )
        else:
            envelope_data = sub_terminal or sub_result.get("data")

        envelope: Dict[str, Any] = {
            "status": normalised_status,
            "framework": "noetl",
            "entrypoint": entrypoint,
            "data": envelope_data,
            "execution_id": sub_execution_id or sub_result.get("execution_id"),
            "duration": sub_result.get("duration"),
        }
        if normalised_status != "ok":
            error_message = (
                (sub_terminal.get("error") if sub_terminal else None)
                or sub_result.get("error")
                or "sub-playbook returned non-success status"
            )
            envelope["error"] = {
                "kind": "agent.execution",
                "code": "PLAYBOOK_FAILED",
                "message": error_message,
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
