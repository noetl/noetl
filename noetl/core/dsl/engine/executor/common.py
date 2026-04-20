"""
NoETL Core Execution Engine - Canonical Format

Event-driven control flow engine that:
1. Consumes events from workers
2. Evaluates next[].when transitions for conditional routing
3. Emits commands to queue table
4. Maintains execution state

Canonical format only - no case/when/then blocks.
"""

import logging
import os
import time
import asyncio
import json
import sys
from collections import OrderedDict
from typing import Any, Optional, TypeVar, Generic
from datetime import datetime, timezone
from jinja2 import Template, Environment, StrictUndefined
from psycopg.types.json import Json
from psycopg.rows import dict_row

from noetl.core.dsl.engine.models import Event, Command, Playbook, Step, ToolCall, CommandSpec, NextRouter, Arc
from noetl.core.db import pool as db_pool
from noetl.core.cache import nats_kv
from noetl.core.storage import default_store

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)


def _engine_module():
    return sys.modules.get("noetl.core.dsl.engine.executor")


def _engine_setting(name: str, default: Any) -> Any:
    engine_module = _engine_module()
    if engine_module is None:
        return default
    value = getattr(engine_module, name, default)
    return default if value is None else value


def get_pool_connection():
    """Resolve the shared DB pool lazily so package-level monkeypatches still work."""
    override = _engine_setting("get_pool_connection", None)
    if override and override is not get_pool_connection:
        return override()
    return db_pool.get_pool_connection()


def get_snowflake_id():
    override = _engine_setting("get_snowflake_id", None)
    if override and override is not get_snowflake_id:
        return override()
    return db_pool.get_snowflake_id()


def get_nats_cache():
    """Resolve the shared NATS cache lazily.

    Keep this as an indirection instead of binding the cache factory directly so tests
    and runtime monkeypatches against ``noetl.core.cache.nats_kv.get_nats_cache`` keep
    working after the engine package refactor.
    """
    return nats_kv.get_nats_cache()


def _loop_result_max_bytes() -> int:
    return int(_engine_setting("_LOOP_RESULT_MAX_BYTES", _LOOP_RESULT_MAX_BYTES))


def _loop_result_max_items() -> int:
    return int(_engine_setting("_LOOP_RESULT_MAX_ITEMS", _LOOP_RESULT_MAX_ITEMS))

_LOOP_RESULT_MAX_BYTES = max(
    0,
    int(os.getenv("NOETL_LOOP_RESULT_MAX_BYTES", "65536")),
)
_LOOP_RESULT_PREVIEW_KEYS = max(
    1,
    int(os.getenv("NOETL_LOOP_RESULT_PREVIEW_KEYS", "8")),
)
_LOOP_RESULT_PREVIEW_ITEMS = max(
    1,
    int(os.getenv("NOETL_LOOP_RESULT_PREVIEW_ITEMS", "3")),
)
_LOOP_RESULT_MAX_ITEMS = max(
    1,
    int(os.getenv("NOETL_LOOP_RESULT_MAX_ITEMS", "128")),
)
_TASKSEQ_LOOP_REPAIR_THRESHOLD = max(
    0,
    int(os.getenv("NOETL_TASKSEQ_LOOP_REPAIR_THRESHOLD", "3")),
)
_TASKSEQ_LOOP_MISSING_MIN_AGE_SECONDS = max(
    0.0,
    float(os.getenv("NOETL_TASKSEQ_LOOP_MISSING_MIN_AGE_SECONDS", "5")),
)
_LOOP_STALL_WATCHDOG_SECONDS = max(
    0.0,
    float(os.getenv("NOETL_LOOP_STALL_WATCHDOG_SECONDS", "60")),
)
_LOOP_STALL_RECOVERY_COOLDOWN_SECONDS = max(
    0.0,
    float(os.getenv("NOETL_LOOP_STALL_RECOVERY_COOLDOWN_SECONDS", "15")),
)
_LOOP_COUNTER_RECONCILE_COOLDOWN_SECONDS = max(
    0.0,
    float(os.getenv("NOETL_LOOP_COUNTER_RECONCILE_COOLDOWN_SECONDS", "10")),
)
_STATE_CACHE_ALLOWED_MISSING_EVENTS = max(
    1,
    int(os.getenv("NOETL_STATE_CACHE_ALLOWED_MISSING_EVENTS", "256")),
)
_STATE_CACHE_STALE_CHECK_INTERVAL_SECONDS = max(
    0.0,
    float(os.getenv("NOETL_STATE_CACHE_STALE_CHECK_INTERVAL_SECONDS", "0.5")),
)
_MAX_LOOP_STALL_RESTARTS = max(
    1,
    int(os.getenv("NOETL_MAX_LOOP_STALL_RESTARTS", "5")),
)
_EXECUTION_TERMINAL_EVENT_TYPES = {
    "playbook.completed",
    "playbook.failed",
    "workflow.completed",
    "workflow.failed",
    "execution.cancelled",
    # NOTE: "command.failed" is intentionally NOT in this set.
    # command.failed is an infrastructure-level event (retries exhausted) that may arrive
    # after a call.error arc has already issued recovery steps. It does not by itself make
    # an execution terminal — only workflow.failed/playbook.failed do. This means that when
    # the command.failed handler skips terminal emission (recovery in-flight), the status
    # API will NOT report the execution as completed/failed based on the command.failed
    # event alone. The execution remains in-progress until a true terminal event is emitted.
}
_EXECUTION_FAILURE_EVENT_TYPES = {
    "playbook.failed",
    "workflow.failed",
}
# Command lifecycle types are NO LONGER scanned from the event table.
# issued_steps and completed_steps are populated from noetl.command
# (the mutable projection table) in _replay_execution_events.
_STATE_REPLAY_EVENT_TYPES = (
    "step.exit",
    "call.done",
    "call.error",
    "loop.done",
    "playbook.completed",
    "playbook.failed",
    "workflow.completed",
    "workflow.failed",
    "execution.cancelled",
)


def _sample_keys(value: Any, max_items: int = 10) -> list[str]:
    if isinstance(value, dict):
        return list(value.keys())[:max_items]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in list(value)[:max_items]]
    return []


def _get_next_router(step: Step) -> Optional[NextRouter]:
    """Return the canonical next router for a step."""
    if step.next is None:
        return None
    if isinstance(step.next, NextRouter):
        return step.next
    if isinstance(step.next, dict):
        return NextRouter.model_validate(step.next)
    raise TypeError(f"Step '{step.step}' has unsupported next router type: {type(step.next).__name__}")


def _get_next_mode(step: Step) -> str:
    """Return the canonical next router mode for a step."""
    router = _get_next_router(step)
    if not router or not router.spec:
        return "exclusive"
    return router.spec.mode


def _get_next_arcs(step: Step) -> list[Arc]:
    """Return the canonical next arcs for a step."""
    router = _get_next_router(step)
    if not router:
        return []
    return list(router.arcs)


def _estimate_json_size(value: Any) -> int:
    """Best-effort JSON byte size estimation for payload guards.

    Uses the fast estimator from storage to avoid full json.dumps overhead.
    """
    from noetl.core.storage.extractor import _estimate_size_fast
    return _estimate_size_fast(value)


def _is_loop_epoch_transition_emitted(
    state: "ExecutionState", step_name: str, event_name: str, loop_event_id: str
) -> bool:
    """Check if a specific transition event (e.g. loop.done) for a given epoch was already emitted.

    Checks the in-memory set first (populated during the current handle_event call).
    Since emitted_loop_epochs is NOT serialized (to keep state bounded), this set
    is empty after state reload. Falls back to checking the DB event table.
    The loop_event_id is stored in the event payload -> context column (not meta).
    """
    key = f"{step_name}:{event_name}:{loop_event_id}"
    if key in state.emitted_loop_epochs:
        return True

    # DB fallback: check if the event was already persisted in a prior handle_event call.
    # Critical after state reload when emitted_loop_epochs is empty.
    # loop_event_id is stored in event payload -> context column as 'loop_event_id'.
    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            from noetl.core.db.pool import get_pool_connection
            import asyncio
            async def _check_db():
                async with get_pool_connection(timeout=3.0) as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "SELECT 1 FROM noetl.event WHERE execution_id = %s AND event_type = %s "
                            "AND context->>'loop_event_id' = %s LIMIT 1",
                            (int(state.execution_id), event_name, str(loop_event_id)),
                        )
                        return await cur.fetchone() is not None
            found = pool.submit(asyncio.run, _check_db()).result(timeout=10.0)
            if found:
                state.emitted_loop_epochs.add(key)
                return True
    except Exception:
        pass

    return False


def _parse_iso_utc(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        normalized = value
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _preview_large_value(value: Any, depth: int = 0) -> Any:
    """Build a compact preview for large loop iteration results."""
    if depth >= 2:
        if isinstance(value, dict):
            return f"dict({len(value)} keys)"
        if isinstance(value, (list, tuple)):
            return f"list({len(value)} items)"
        return value

    if isinstance(value, dict):
        items = list(value.items())
        preview: dict[str, Any] = {
            k: _preview_large_value(v, depth + 1)
            for k, v in items[:_LOOP_RESULT_PREVIEW_KEYS]
        }
        if len(items) > _LOOP_RESULT_PREVIEW_KEYS:
            preview["_truncated_keys"] = len(items) - _LOOP_RESULT_PREVIEW_KEYS
        return preview

    if isinstance(value, (list, tuple)):
        seq = list(value)
        preview_items = [_preview_large_value(v, depth + 1) for v in seq[:_LOOP_RESULT_PREVIEW_ITEMS]]
        if len(seq) > _LOOP_RESULT_PREVIEW_ITEMS:
            preview_items.append(f"... {len(seq) - _LOOP_RESULT_PREVIEW_ITEMS} more")
        return preview_items

    return value


def _compact_loop_result(result: Any) -> Any:
    """
    Store only bounded loop iteration data in engine state.

    This protects server memory/render context from large per-item payloads while
    preserving basic diagnostics for loop aggregation.
    """
    max_bytes = _loop_result_max_bytes()
    if max_bytes <= 0:
        return result

    if not isinstance(result, (dict, list, tuple)):
        return result

    size_bytes = _estimate_json_size(result)
    if size_bytes <= max_bytes:
        return result

    return {
        "_truncated": True,
        "_original_size_bytes": size_bytes,
        "_type": type(result).__name__,
        "_preview": _preview_large_value(result),
    }


def _retain_recent_loop_results(
    results: list[Any],
    omitted_count: int = 0,
    max_items: Optional[int] = None,
) -> tuple[list[Any], int]:
    """Keep only a bounded tail of loop results to cap in-memory state growth."""
    if max_items is None:
        max_items = _loop_result_max_items()
    if max_items <= 0 or len(results) <= max_items:
        return results, omitted_count
    overflow = len(results) - max_items
    return results[overflow:], omitted_count + overflow


def _loop_results_total(loop_state: dict[str, Any]) -> int:
    """Return authoritative local loop completion count."""
    return loop_state.get("completed_count", 0) + loop_state.get("omitted_results_count", 0)


def _unwrap_event_payload(payload: Any) -> Any:
    """Normalize persisted event payload wrappers back to runtime payload semantics."""
    if isinstance(payload, dict) and "kind" in payload and "data" in payload:
        return payload.get("data")
    return payload


def _extract_command_id_from_event_payload(payload: Any, meta: Optional[dict[str, Any]] = None) -> Optional[int]:
    """Best-effort extraction of command_id (BIGINT snowflake) from worker event payloads.

    Accepts int (current shape), or numeric str (legacy). Returns int or None.
    """
    def _coerce(v: Any) -> Optional[int]:
        if v is None: return None
        if isinstance(v, int): return v
        if isinstance(v, str) and v.strip().isdigit(): return int(v.strip())
        return None

    if isinstance(meta, dict) and "command_id" in meta:
        coerced = _coerce(meta.get("command_id"))
        if coerced is not None:
            return coerced

    if not isinstance(payload, dict):
        return None

    candidates: list[Any] = [payload.get("command_id")]

    payload_context = payload.get("context")
    if isinstance(payload_context, dict):
        candidates.append(payload_context.get("command_id"))

    payload_result = payload.get("result")
    if isinstance(payload_result, dict):
        candidates.append(payload_result.get("command_id"))
        result_context = payload_result.get("context")
        if isinstance(result_context, dict):
            candidates.append(result_context.get("command_id"))

    payload_response = payload.get("response")
    if isinstance(payload_response, dict):
        candidates.append(payload_response.get("command_id"))
        response_context = payload_response.get("context")
        if isinstance(response_context, dict):
            candidates.append(response_context.get("command_id"))
        response_result = payload_response.get("result")
        if isinstance(response_result, dict):
            candidates.append(response_result.get("command_id"))
            response_result_context = response_result.get("context")
            if isinstance(response_result_context, dict):
                candidates.append(response_result_context.get("command_id"))

    for value in candidates:
        coerced = _coerce(value)
        if coerced is not None:
            return coerced
    return None


def _extract_loop_iteration_index_from_event_payload(
    payload: Any,
    meta: Optional[dict[str, Any]] = None,
) -> Optional[int]:
    """Best-effort extraction of loop_iteration_index from event payloads."""
    candidates: list[Any] = []
    if isinstance(meta, dict):
        candidates.append(meta.get("loop_iteration_index"))

    if isinstance(payload, dict):
        candidates.append(payload.get("loop_iteration_index"))
        payload_context = payload.get("context")
        if isinstance(payload_context, dict):
            candidates.append(payload_context.get("loop_iteration_index"))
        payload_response = payload.get("response")
        if isinstance(payload_response, dict):
            candidates.append(payload_response.get("loop_iteration_index"))
            response_context = payload_response.get("context")
            if isinstance(response_context, dict):
                candidates.append(response_context.get("loop_iteration_index"))
        payload_result = payload.get("result")
        if isinstance(payload_result, dict):
            candidates.append(payload_result.get("loop_iteration_index"))
            result_context = payload_result.get("context")
            if isinstance(result_context, dict):
                candidates.append(result_context.get("loop_iteration_index"))

    for value in candidates:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


async def _resolve_collection_if_reference(value: Any) -> Any:
    """If value is a dict with a reference key, resolve it to get the actual data.

    Used by loop collection paths: when a template like
    {{ claim_patients.rows }} renders to a step result that carries a
    reference instead of inline rows, resolve the reference to fetch
    the actual row list from TempStore.
    """
    if not isinstance(value, dict):
        return value
    ref = value.get("reference")
    if not isinstance(ref, dict):
        # Also check if the value itself IS a reference dict (e.g. from context promotion)
        if value.get("kind") in ("temp_ref", "result_ref") and value.get("ref"):
            ref = value
        else:
            return value
    try:
        from noetl.core.storage.result_store import default_store
        resolved = await default_store.resolve(ref)
        if resolved is not None and isinstance(resolved, list):
            return resolved
        return value
    except Exception as exc:
        logger.warning("[RESOLVE-REF] Failed to resolve collection reference: %s", exc)
        return value


def _apply_set_mutations(variables: dict, mutations: dict) -> None:
    """Apply DSL Core `set` mutations to the execution variable store.

    Handles scoped keys (ctx.x, iter.x, step.x) by stripping the scope prefix
    and writing the bare key. Bare keys (no dot prefix) are written as-is.
    """
    for key, value in mutations.items():
        if "." in key:
            scope, bare_key = key.split(".", 1)
            if scope in ("ctx", "iter", "step"):
                variables[bare_key] = value
                continue
        variables[key] = value


def _reference_to_result_ref(reference: Any) -> Optional[dict[str, Any]]:
    """Convert a compact PRD reference envelope into a ResultStore-compatible ref."""
    if not isinstance(reference, dict):
        return None

    locator = str(reference.get("locator") or reference.get("ref") or "").strip()
    if not locator.startswith("noetl://"):
        return None

    store = str(reference.get("store") or "kv").strip().lower() or "kv"
    ref_kind = "temp_ref" if store == "memory" else "result_ref"
    return {
        "kind": ref_kind,
        "ref": locator,
        "store": store,
    }


def _merge_hydrated_step_result(
    resolved: Any,
    compact_result: dict[str, Any],
    ref_wrapper: dict[str, Any],
) -> Any:
    """Merge resolved output data with compact PRD metadata for runtime templating."""
    reference = compact_result.get("reference")
    compact_context = compact_result.get("context")
    compact_status = compact_result.get("status")

    if isinstance(resolved, dict):
        hydrated = dict(resolved)
        hydrated.setdefault("data", resolved)
        hydrated.setdefault("_ref", ref_wrapper)
        if isinstance(reference, dict):
            hydrated.setdefault("ref", reference)
            hydrated.setdefault("reference", reference)
        if compact_status is not None:
            hydrated.setdefault("status", compact_status)
        if isinstance(compact_context, dict):
            hydrated.setdefault("context", compact_context)
        return hydrated

    # When resolved is a list (e.g., Postgres rows from TempStore), build a proper
    # data view dict so that templates like {{ output.data.row_count }} and
    # {{ output.data.rows[0].field }} work without attribute errors.
    if isinstance(resolved, list):
        rc = (
            compact_context.get("row_count", len(resolved))
            if isinstance(compact_context, dict)
            else len(resolved)
        )
        cols = compact_context.get("columns") if isinstance(compact_context, dict) else None
        data_view: dict[str, Any] = {"rows": resolved, "row_count": rc}
        if cols is not None:
            data_view["columns"] = cols
        wrapped: dict[str, Any] = {
            "data": data_view,
            "rows": resolved,
            "row_count": rc,
            "_ref": ref_wrapper,
            "status": compact_status,
        }
        if isinstance(reference, dict):
            wrapped["ref"] = reference
            wrapped["reference"] = reference
        if isinstance(compact_context, dict):
            wrapped["context"] = compact_context
        return wrapped

    wrapped = {
        "data": resolved,
        "_ref": ref_wrapper,
        "status": compact_status,
    }
    if isinstance(reference, dict):
        wrapped["ref"] = reference
        wrapped["reference"] = reference
    if isinstance(compact_context, dict):
        wrapped["context"] = compact_context
    return wrapped


async def _hydrate_reference_only_step_result(result: Any) -> Any:
    """Resolve compact `result.reference` envelopes back into runtime step output."""
    if not isinstance(result, dict):
        return result

    reference = result.get("reference")
    ref_wrapper = _reference_to_result_ref(reference)
    if not isinstance(ref_wrapper, dict):
        return result

    try:
        resolved = await default_store.resolve(ref_wrapper)
    except Exception as exc:
        logger.warning(
            "[RESULT-REF] Failed to resolve %s: %s",
            ref_wrapper.get("ref"),
            exc,
        )
        return result

    return _merge_hydrated_step_result(resolved, result, ref_wrapper)


def _normalize_output_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"ok", "success", "completed", "done", "noop"}:
        return "ok"
    if raw in {"error", "failed", "failure"}:
        return "error"
    return "ok"


def _build_output_view(
    *,
    event_payload: dict[str, Any],
    step_result: Any,
) -> dict[str, Any]:
    """Build canonical author-facing output envelope from control-plane payload and step state."""
    payload_result = event_payload.get("result")
    output: dict[str, Any] = {
        "status": "error" if event_payload.get("error") else "ok",
        "data": None,
        "ref": None,
        "error": event_payload.get("error"),
    }

    if isinstance(payload_result, dict):
        output["status"] = _normalize_output_status(payload_result.get("status", output["status"]))
        if isinstance(payload_result.get("reference"), dict):
            output["ref"] = payload_result.get("reference")
        if isinstance(payload_result.get("error"), dict):
            output["error"] = payload_result.get("error")
        if isinstance(payload_result.get("context"), dict):
            output["context"] = payload_result.get("context")
            output["data"] = payload_result.get("context")
        # When the event.result column carries small inline rows (preserved by
        # server/_build_reference_only_result for <=16-row postgres selects),
        # surface them as output.data.rows so replay-time re-rendering of
        # step-level set: expressions like {{ output.data.rows[0].<col> }}
        # can still resolve the value.
        inline_rows = payload_result.get("rows")
        if isinstance(inline_rows, list):
            data_view = output.get("data") if isinstance(output.get("data"), dict) else {}
            data_view = {**data_view, "rows": inline_rows}
            if "row_count" not in data_view:
                data_view["row_count"] = len(inline_rows)
            output["data"] = data_view

    if isinstance(step_result, dict):
        if "status" in step_result:
            output["status"] = _normalize_output_status(step_result.get("status"))
        if "error" in step_result and step_result.get("error") is not None:
            output["error"] = step_result.get("error")
        if isinstance(step_result.get("ref"), dict):
            output["ref"] = step_result.get("ref")
        elif isinstance(step_result.get("reference"), dict):
            output["ref"] = step_result.get("reference")
        output["data"] = step_result.get("data", step_result)
        for key in ("http", "pg", "py", "meta", "context"):
            if key in step_result:
                output[key] = step_result.get(key)
    elif step_result is not None:
        output["data"] = step_result

    if output.get("data") is None and output.get("context") is not None:
        output["data"] = output["context"]

    return output


def _pending_step_key(step_name: Optional[str]) -> str:
    """
    Normalize orchestration pending-step keys.

    Task-sequence commands are emitted as `<parent_step>:task_sequence` but step completion
    is tracked on the parent step name. Pending tracking must use the parent key to avoid
    stale synthetic pending entries that block terminal lifecycle emission.
    """
    if not step_name:
        return ""
    if isinstance(step_name, str) and step_name.endswith(":task_sequence"):
        return step_name.rsplit(":", 1)[0]
    return str(step_name)


def _node_name_candidates(node_name: str) -> tuple[str, ...]:
    """Return canonical event node-name aliases for step and task-sequence rows."""
    normalized = str(node_name)
    candidates: list[str] = [normalized]
    if normalized.endswith(":task_sequence"):
        parent = normalized.rsplit(":", 1)[0]
        if parent:
            candidates.append(parent)
    else:
        candidates.append(f"{normalized}:task_sequence")
    # Preserve order while removing duplicates.
    return tuple(dict.fromkeys(candidates))


# Type variable for generic BoundedCache
T = TypeVar('T')


class BoundedCache(Generic[T]):
    """
    LRU cache with TTL and maximum size to prevent unbounded memory growth.

    Features:
    - Max size limit with LRU eviction
    - TTL (time-to-live) for entries
    - Thread-safe with asyncio.Lock
    - Automatic cleanup of expired entries
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        """
        Initialize bounded cache.

        Args:
            max_size: Maximum number of entries (default 1000)
            ttl_seconds: Time-to-live in seconds (default 1 hour)
        """
        self._cache: OrderedDict[str, tuple[T, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()
        self._cleanup_counter = 0
        self._cleanup_interval = 100  # Cleanup every N operations

    async def get(self, key: str) -> Optional[T]:
        """Get value from cache (async)."""
        async with self._lock:
            if key not in self._cache:
                return None
            value, timestamp = self._cache[key]
            if time.time() - timestamp > self._ttl_seconds:
                del self._cache[key]
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            return value

    async def set(self, key: str, value: T):
        """Set value in cache (async)."""
        async with self._lock:
            # Increment cleanup counter and maybe cleanup
            self._cleanup_counter += 1
            if self._cleanup_counter >= self._cleanup_interval:
                self._cleanup_expired_sync()
                self._cleanup_counter = 0

            # Evict oldest if at capacity
            while len(self._cache) >= self._max_size:
                evicted_key, _ = self._cache.popitem(last=False)
                logger.debug(f"BoundedCache: evicted {evicted_key} due to capacity")

            self._cache[key] = (value, time.time())

    async def delete(self, key: str) -> bool:
        """Delete entry from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def get_sync(self, key: str) -> Optional[T]:
        """Get value from cache (sync for backward compatibility)."""
        if key not in self._cache:
            return None
        value, timestamp = self._cache[key]
        if time.time() - timestamp > self._ttl_seconds:
            # Note: no lock in sync version, best-effort
            try:
                del self._cache[key]
            except KeyError:
                pass
            return None
        # Move to end (most recently used)
        try:
            self._cache.move_to_end(key)
        except KeyError:
            pass
        return value

    def set_sync(self, key: str, value: T):
        """Set value in cache (sync for backward compatibility)."""
        # Evict oldest if at capacity
        while len(self._cache) >= self._max_size:
            try:
                evicted_key, _ = self._cache.popitem(last=False)
                logger.debug(f"BoundedCache: evicted {evicted_key} due to capacity")
            except KeyError:
                break

        self._cache[key] = (value, time.time())

    def _cleanup_expired_sync(self):
        """Remove expired entries (internal, called with lock held)."""
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items()
                   if now - ts > self._ttl_seconds]
        for k in expired:
            del self._cache[k]
        if expired:
            logger.debug(f"BoundedCache: cleaned up {len(expired)} expired entries")

    async def cleanup_expired(self):
        """Remove all expired entries (async)."""
        async with self._lock:
            self._cleanup_expired_sync()

    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)

    def clear(self):
        """Clear all entries."""
        self._cache.clear()




class TemplateCache:
    """
    LRU cache for compiled Jinja2 templates.

    Caches compiled Template objects to avoid expensive from_string() calls.
    Thread-safe for read operations (compiled templates are immutable).

    Memory bounded: max_size limits total cached templates.
    """

    def __init__(self, max_size: int = 500):
        self._cache: OrderedDict[str, Any] = OrderedDict()  # template_str -> compiled Template
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get_or_compile(self, env: Environment, template_str: str) -> Any:
        """Get compiled template from cache or compile and cache it."""
        if template_str in self._cache:
            # Cache hit - move to end (most recently used)
            self._cache.move_to_end(template_str)
            self._hits += 1
            return self._cache[template_str]

        # Cache miss - compile template
        self._misses += 1
        compiled = env.from_string(template_str)

        # Add to cache with LRU eviction
        if len(self._cache) >= self._max_size:
            # Remove oldest entry
            self._cache.popitem(last=False)
            self._evictions += 1

        self._cache[template_str] = compiled

        # Log cache stats periodically (every 100 misses)
        if self._misses % 100 == 0:
            logger.debug(
                f"[TEMPLATE-CACHE] Engine stats: size={len(self._cache)}/{self._max_size}, "
                f"hits={self._hits}, misses={self._misses}, evictions={self._evictions}, "
                f"hit_rate={self._hits / (self._hits + self._misses) * 100:.1f}%"
            )

        return compiled

    def size(self) -> int:
        """Return current cache size."""
        return len(self._cache)

    def stats(self) -> dict:
        """Return cache statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate": (self._hits / total * 100) if total > 0 else 0.0
        }

    def clear(self) -> None:
        """Clear the cache and reset stats."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        self._evictions = 0


__all__ = [name for name in globals() if not name.startswith("__")]
