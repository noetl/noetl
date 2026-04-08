"""
NoETL V2 Execution Engine - Canonical Format

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
from collections import OrderedDict
from typing import Any, Optional, TypeVar, Generic
from datetime import datetime, timezone
from jinja2 import Template, Environment, StrictUndefined
from psycopg.types.json import Json
from psycopg.rows import dict_row

from noetl.core.dsl.v2.models import Event, Command, Playbook, Step, ToolCall, CommandSpec
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.cache import get_nats_cache
from noetl.core.storage import default_store

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)

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
_STATE_REPLAY_EVENT_TYPES = (
    "command.issued",
    "command.completed",
    "command.failed",
    "command.cancelled",
    "step.exit",
    "call.done",
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


def _estimate_json_size(value: Any) -> int:
    """Best-effort JSON byte size estimation for payload guards.

    Uses the fast estimator from storage to avoid full json.dumps overhead.
    """
    from noetl.core.storage.extractor import _estimate_size_fast
    return _estimate_size_fast(value)


def _is_loop_epoch_transition_emitted(
    state: "ExecutionState", step_name: str, event_name: str, loop_event_id: str
) -> bool:
    """Check if a specific transition event (e.g. loop.done) for a given epoch was already emitted."""
    key = f"{step_name}:{event_name}:{loop_event_id}"
    return key in state.emitted_loop_epochs


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
    if _LOOP_RESULT_MAX_BYTES <= 0:
        return result

    if not isinstance(result, (dict, list, tuple)):
        return result

    size_bytes = _estimate_json_size(result)
    if size_bytes <= _LOOP_RESULT_MAX_BYTES:
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
        max_items = _LOOP_RESULT_MAX_ITEMS
    if max_items <= 0 or len(results) <= max_items:
        return results, omitted_count
    overflow = len(results) - max_items
    return results[overflow:], omitted_count + overflow


def _loop_results_total(loop_state: dict[str, Any]) -> int:
    """Return authoritative local loop completion count."""
    buffered_results = loop_state.get("results", [])
    if not isinstance(buffered_results, list):
        buffered_results = []
    omitted = int(loop_state.get("omitted_results_count", 0) or 0)
    return len(buffered_results) + max(0, omitted)


def _unwrap_event_payload(payload: Any) -> Any:
    """Normalize persisted event payload wrappers back to runtime payload semantics."""
    if isinstance(payload, dict) and "kind" in payload and "data" in payload:
        return payload.get("data")
    return payload


def _extract_command_id_from_event_payload(payload: Any) -> Optional[str]:
    """Best-effort extraction of command_id from worker event payloads."""
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
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _apply_set_mutations(variables: dict, mutations: dict) -> None:
    """Apply DSL v2 `set` mutations to the execution variable store.

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

    wrapped: dict[str, Any] = {
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


class ExecutionState:
    """Tracks state of a playbook execution."""
    
    def __init__(self, execution_id: str, playbook: Playbook, payload: dict[str, Any], catalog_id: Optional[int] = None, parent_execution_id: Optional[int] = None):
        self.execution_id = execution_id
        self.playbook = playbook
        self.payload = payload
        self.catalog_id = catalog_id  # Store catalog_id for event persistence
        self.parent_execution_id = parent_execution_id  # Track parent execution for sub-playbooks
        self.current_step: Optional[str] = None
        self.variables: dict[str, Any] = {}
        self.last_event_id: Optional[int] = None  # Track last persisted event ID
        self.step_event_ids: dict[str, int] = {}  # Track last event per step
        self.step_results: dict[str, Any] = {}
        self.completed_steps: set[str] = set()
        self.issued_steps: set[str] = set()  # Track steps that have commands issued (pending execution)
        self.failed = False
        self.completed = False
        
        # Root event tracking for traceability
        self.root_event_id: Optional[int] = None  # First event (playbook.initialized) for full trace
        
        # Loop state tracking
        self.loop_state: dict[str, dict[str, Any]] = {}  # step_name -> {collection, index, item, mode}
        self.step_stall_counts: dict[str, int] = {}  # step_name -> consecutive times loop ended with zero successful slots
        self.emitted_loop_epochs: set[str] = set()  # "step_name:event_name:loop_event_id"


        # Pagination state tracking for collect+retry pattern
        self.pagination_state: dict[str, dict[str, Any]] = {}  # step_name -> {collected_data: [], iteration_count: int}

        # Deferred next actions tracking for inline tasks
        # When inline tasks are in a then block with next actions, the next is deferred until inline tasks complete
        self.pending_next_actions: dict[str, dict[str, Any]] = {}  # inline_task_step -> {next_actions, inline_tasks, context_event_step}
        
        # Initialize workload variables (becomes ctx at runtime)
        # NOTE: Playbooks use 'workload:' section for default variables, NOT 'ctx:'
        # The 'ctx' is an internal runtime concept, not a playbook structure
        if playbook.workload:
            self.variables.update(playbook.workload)

        # Merge payload into variables (execution request overrides playbook defaults)
        # NOTE: 'vars' key is REMOVED in strict v10 - use 'ctx' instead
        for k, v in payload.items():
            if k == "ctx" and isinstance(v, dict):
                # Merge execution request ctx into variables (canonical v10)
                self.variables.update(v)
                logger.debug(f"[STATE-INIT] Merged execution ctx into variables: {list(v.keys())}")
            else:
                # Other keys go directly into variables
                self.variables[k] = v

        # Log final state for debugging reconstruction issues
        logger.debug(
            "[STATE-INIT] execution_id=%s variables_count=%s variable_keys=%s",
            execution_id,
            len(self.variables),
            _sample_keys(self.variables),
        )

    def get_step(self, step_name: str) -> Optional[Step]:
        """Get step by name."""
        for step in self.playbook.workflow:
            if step.step == step_name:
                return step
        return None
    
    def set_current_step(self, step_name: str):
        """Set current executing step."""
        self.current_step = step_name
    
    def mark_step_completed(self, step_name: str, result: Any = None):
        """Mark step as completed and store result in memory and transient.

        If result contains _ref (externalized via ResultRef pattern), the extracted
        output_select fields are stored directly for template access:
        - {{ step_name.status }} accesses extracted field
        - {{ step_name._ref }} accesses the ResultRef for lazy loading
        """
        self.completed_steps.add(step_name)
        if result is not None:
            self.step_results[step_name] = result
            self.variables[step_name] = result

            # Log if result was externalized
            if isinstance(result, dict) and "_ref" in result:
                logger.info(
                    f"[STATE] Step {step_name}: externalized result stored | "
                    f"extracted_fields={[k for k in result.keys() if not k.startswith('_')]}"
                )
            # Also persist to transient for rendering in subsequent steps
            # This is done async in the engine after calling mark_step_completed

    def get_step_result_ref(self, step_name: str) -> Optional[dict]:
        """Get ResultRef for a step's externalized result, if any.

        Returns the _ref dict if step result was externalized, None otherwise.
        Used for lazy loading of large results via artifact.get.
        """
        result = self.step_results.get(step_name)
        if isinstance(result, dict) and "_ref" in result:
            return result.get("_ref")
        return None

    def is_result_externalized(self, step_name: str) -> bool:
        """Check if a step's result was externalized to remote storage."""
        result = self.step_results.get(step_name)
        return isinstance(result, dict) and "_ref" in result
    
    def is_step_completed(self, step_name: str) -> bool:
        """Check if step is completed."""
        return step_name in self.completed_steps
    
    def init_loop(self, step_name: str, collection: list[Any], iterator: str, mode: str = "sequential", event_id: Optional[int] = None):
        """Initialize loop state for a step.
        
        Args:
            step_name: Name of the step
            collection: Collection to iterate over
            iterator: Iterator variable name
            mode: Iteration mode (sequential or parallel)
            event_id: Event ID that initiated this loop instance (for uniqueness)
        """
        # Evaluate previous invocation for dead-loop detection BEFORE resetting
        if step_name in self.loop_state:
            prev_state = self.loop_state[step_name]
            # Check if previous loop had items but 0 successful completions
            prev_size = len(prev_state.get("collection", []))
            prev_completed = _loop_results_total(prev_state)
            prev_failed = prev_state.get("failed_count", 0)
            prev_break = prev_state.get("break_count", 0)
            successful_slots = prev_completed - prev_failed - prev_break
            
            # If the loop executed fully (or partially), but yielded 0 successful slots
            if prev_size > 0 and prev_completed > 0 and successful_slots <= 0:
                self.step_stall_counts[step_name] = self.step_stall_counts.get(step_name, 0) + 1
                logger.warning(
                    "[DEAD-LOOP-TRACK] Loop %s yielded 0 successful slots on previous run. Stall count: %s",
                    step_name,
                    self.step_stall_counts[step_name]
                )
            else:
                self.step_stall_counts[step_name] = 0

        self.loop_state[step_name] = {
            # Keep a local snapshot so downstream in-place list mutations outside loop_state
            # do not alter continuation/retry scheduling.
            "collection": list(collection),
            "iterator": iterator,
            "index": 0,
            "mode": mode,
            "completed": False,
            "results": [],  # Track iteration results for aggregation
            "failed_count": 0,  # Track failed iterations
            "break_count": 0,  # Track skipped/break iterations
            "scheduled_count": 0,  # Track issued iterations for max_in_flight gating
            "event_id": event_id,  # Track which event initiated this loop instance
            "omitted_results_count": 0,  # Number of older results evicted from memory buffer
        }
        logger.debug(f"Initialized loop for step {step_name}: {len(collection)} items, mode={mode}, event_id={event_id}")
    
    def get_next_loop_item(self, step_name: str) -> tuple[Any, int] | None:
        """Get next item from loop. Returns (item, index) or None if done."""
        if step_name not in self.loop_state:
            return None
        
        state = self.loop_state[step_name]
        if state["completed"]:
            return None
        
        collection = state["collection"]
        index = state["index"]
        
        if index >= len(collection):
            state["completed"] = True
            return None
        
        item = collection[index]
        state["index"] = index + 1
        return (item, index)
    
    def is_loop_done(self, step_name: str) -> bool:
        """Check if loop is completed."""
        if step_name not in self.loop_state:
            return True
        return self.loop_state[step_name]["completed"]
    
    def add_loop_result(self, step_name: str, result: Any, failed: bool = False):
        """Add iteration result to loop aggregation (local cache only)."""
        if step_name not in self.loop_state:
            return

        stored_result = _compact_loop_result(result)
        loop_state = self.loop_state[step_name]
        results_buffer = loop_state.get("results", [])
        if not isinstance(results_buffer, list):
            results_buffer = []
        results_buffer.append(stored_result)
        retained_results, omitted_count = _retain_recent_loop_results(
            results_buffer,
            int(loop_state.get("omitted_results_count", 0) or 0),
        )
        loop_state["results"] = retained_results
        loop_state["omitted_results_count"] = omitted_count
        if failed:
            loop_state["failed_count"] += 1
        elif isinstance(result, dict):
            status = str(result.get("status", "")).lower()
            is_policy_break = result.get("policy_break") is True
            if status == "break" or is_policy_break:
                loop_state["break_count"] = loop_state.get("break_count", 0) + 1

        if stored_result is not result:
            logger.info(
                "[LOOP] Compacted large iteration result for %s (max=%s bytes)",
                step_name,
                _LOOP_RESULT_MAX_BYTES,
            )
        logger.debug(
            "Added iteration result to loop %s: total=%s buffered=%s omitted=%s",
            step_name,
            _loop_results_total(loop_state),
            len(loop_state.get("results", [])),
            loop_state.get("omitted_results_count", 0),
        )
        
        # Note: Distributed sync to NATS K/V happens in engine.handle_event()
    
    def get_loop_aggregation(self, step_name: str) -> dict[str, Any]:
        """Get aggregated loop results in standard format."""
        if step_name not in self.loop_state:
            return {"results": [], "stats": {"total": 0, "success": 0, "failed": 0}}
        
        loop_state = self.loop_state[step_name]
        omitted_results = int(loop_state.get("omitted_results_count", 0) or 0)
        buffered_results = loop_state.get("results", [])
        if not isinstance(buffered_results, list):
            buffered_results = []
        total = _loop_results_total(loop_state)
        failed = loop_state["failed_count"]
        success = total - failed
        
        return {
            "results": buffered_results,
            "stats": {
                "total": total,
                "success": success,
                "failed": failed
            },
            "omitted_results_count": omitted_results,
        }

    def get_loop_completed_count(self, step_name: str) -> int:
        """Get local loop completion count including omitted buffered entries."""
        if step_name not in self.loop_state:
            return 0
        return _loop_results_total(self.loop_state[step_name])
    
    def add_emitted_loop_epoch(self, step_name: str, event_name: str, loop_event_id: str):
        """Mark a specific transition event as already emitted for deduplication."""
        logger.info(f"[ENGINE-STATE] Marking transition emitted: {step_name}:{event_name}:{loop_event_id}")
        self.emitted_loop_epochs.add(f"{step_name}:{event_name}:{loop_event_id}")

    def get_render_context(self, event: Event) -> dict[str, Any]:
        """Get context for Jinja2 rendering.

        Loop variables are added to state.variables in _create_command_for_step,
        so they will be available via **self.variables spread below.
        """
        logger.debug(
            "ENGINE.get_render_context execution_id=%s catalog_id=%s variables_count=%s variable_keys=%s",
            self.execution_id,
            self.catalog_id,
            len(self.variables),
            _sample_keys(self.variables),
        )

        event_payload = _unwrap_event_payload(event.payload)
        
        # Protected system fields that should not be overridden by workload variables
        protected_fields = {"execution_id", "catalog_id", "job"}
        
        # Separate iteration-scoped variables (loop iterator, loop index)
        iter_vars = {}
        if event.step and event.step in self.loop_state:
            loop_state = self.loop_state[event.step]
            iterator_name = loop_state.get("iterator", "item")
            if iterator_name in self.variables:
                iter_vars[iterator_name] = self.variables[iterator_name]
            iter_vars["_index"] = loop_state["index"] - 1 if loop_state["index"] > 0 else 0
            iter_vars["_first"] = loop_state["index"] == 1
            iter_vars["_last"] = loop_state["index"] >= len(loop_state["collection"])

        context = {
            "event": {
                "name": event.name,
                "payload": event_payload,
                "step": event.step,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            },
            # Canonical v10: ctx = execution-scoped, iter = iteration-scoped
            "ctx": self.variables,  # Execution-scoped variables (canonical v10)
            "iter": iter_vars,      # Iteration-scoped variables (canonical v10)
            # Backward compatibility: workload namespace for {{ workload.xxx }}
            "workload": self.variables,  # Legacy alias for v2 playbooks
            **self.step_results,  # Make step results accessible (e.g., {{ process }})
        }
        
        # Add variables to context only if they don't collide with reserved keys
        # This provides a flatter namespace while protecting system fields
        for k, v in self.variables.items():
            if k not in context and k not in protected_fields:
                context[k] = v
        
        # Set protected fields AFTER spreading variables to ensure they are not overridden
        # CRITICAL: Convert IDs to strings to prevent JavaScript precision loss with Snowflake IDs
        context["execution_id"] = str(self.execution_id) if self.execution_id else None
        context["catalog_id"] = str(self.catalog_id) if self.catalog_id else None
        context["job"] = {
            "uuid": str(self.execution_id) if self.execution_id else None,
            "execution_id": str(self.execution_id) if self.execution_id else None,
            "id": str(self.execution_id) if self.execution_id else None
        }
        
        # Add loop metadata context if step has active loop
        if event.step and event.step in self.loop_state:
            loop_state = self.loop_state[event.step]
            context["loop"] = {
                "index": loop_state["index"] - 1 if loop_state["index"] > 0 else 0,  # Current item index
                "first": loop_state["index"] == 1,
                "length": len(loop_state["collection"]),
                "done": loop_state["completed"]
            }
            # Note: Iterator variable itself (e.g., {{ num }}) comes from state.variables
        
        # Add event-specific data (strict reference-only contract).
        if isinstance(event_payload, dict):
            step_result = self.step_results.get(event.step) if event.step else None
            if step_result is None and isinstance(event.step, str) and event.step.endswith(":task_sequence"):
                step_result = self.step_results.get(event.step.rsplit(":", 1)[0])

            output_view = _build_output_view(
                event_payload=event_payload,
                step_result=step_result,
            )
            context["output"] = output_view
            if output_view.get("error") is not None:
                context["error"] = output_view.get("error")

        return context


class PlaybookRepo:
    """Repository for loading playbooks from catalog with bounded cache."""

    def __init__(self):
        # Bounded cache: max 500 playbooks, 30 min TTL
        self._cache: BoundedCache[Playbook] = BoundedCache(
            max_size=500,
            ttl_seconds=1800
        )

    async def load_playbook(self, path: str) -> Optional[Playbook]:
        """Load playbook from catalog by path."""
        # Check cache first
        cached = await self._cache.get(path)
        if cached:
            return cached

        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT content, layout
                    FROM noetl.catalog
                    WHERE path = %s
                    ORDER BY version DESC
                    LIMIT 1
                """, (path,))
                row = await cur.fetchone()

                if not row:
                    logger.error(f"Playbook not found: {path}")
                    return None

                # Parse YAML content
                import yaml
                content_dict = yaml.safe_load(row["content"])

                # Validate it's v2 or v10 format
                api_version = content_dict.get("apiVersion")
                if api_version not in ("noetl.io/v2", "noetl.io/v10"):
                    logger.error(f"Playbook {path} has unsupported apiVersion: {api_version}")
                    return None

                # Parse into Pydantic model
                playbook = Playbook(**content_dict)
                await self._cache.set(path, playbook)
                return playbook

    async def load_playbook_by_id(self, catalog_id: int) -> Optional[Playbook]:
        """Load playbook from catalog by ID."""
        # Check if we have it in cache
        cache_key = f"id:{catalog_id}"
        cached = await self._cache.get(cache_key)
        if cached:
            return cached

        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT content, layout, path
                    FROM noetl.catalog
                    WHERE catalog_id = %s
                """, (catalog_id,))
                row = await cur.fetchone()

                if not row:
                    logger.error(f"Playbook not found: catalog_id={catalog_id}")
                    return None

                # Parse YAML content
                import yaml
                content_dict = yaml.safe_load(row["content"])

                # Validate it's v2 or v10 format
                api_version = content_dict.get("apiVersion")
                if api_version not in ("noetl.io/v2", "noetl.io/v10"):
                    logger.error(f"Playbook catalog_id={catalog_id} has unsupported apiVersion: {api_version}")
                    return None

                # Parse into Pydantic model
                playbook = Playbook(**content_dict)
                await self._cache.set(cache_key, playbook)
                # Also cache by path for consistency
                if row.get("path"):
                    await self._cache.set(row["path"], playbook)
                return playbook


class StateStore:
    """Stores and retrieves execution state with bounded cache."""

    def __init__(self, playbook_repo: 'PlaybookRepo'):
        # Bounded cache: tune via env to avoid runaway server memory usage.
        cache_max_size = max(
            50,
            int(os.getenv("NOETL_STATE_CACHE_MAX_EXECUTIONS", "500")),
        )
        cache_ttl_seconds = max(
            60,
            int(os.getenv("NOETL_STATE_CACHE_TTL_SECONDS", "1200")),
        )
        self._memory_cache: BoundedCache[ExecutionState] = BoundedCache(
            max_size=cache_max_size,
            ttl_seconds=cache_ttl_seconds,
        )
        logger.info(
            "[STATE-CACHE] max_executions=%s ttl_seconds=%s allowed_missing_events=%s stale_check_interval_s=%s",
            cache_max_size,
            cache_ttl_seconds,
            _STATE_CACHE_ALLOWED_MISSING_EVENTS,
            _STATE_CACHE_STALE_CHECK_INTERVAL_SECONDS,
        )
        self.playbook_repo = playbook_repo
        self._stale_probe_last_checked_at: dict[str, float] = {}

    async def save_state(self, state: ExecutionState):
        """Save execution state."""
        await self._memory_cache.set(state.execution_id, state)

        # Pure event-driven: State is fully reconstructable from events
        # No need to persist to workload table - it's redundant with event log
        # Just keep in memory cache for performance
        logger.debug(f"State cached in memory for execution {state.execution_id}")

    async def should_refresh_cached_state(
        self,
        execution_id: str,
        last_event_id: Optional[int],
        *,
        allowed_missing_events: int = 1,
    ) -> bool:
        """Return True when cached state is older than the persisted event stream.

        When API/event ingestion persists the current event before calling the engine,
        a healthy local cache should lag by at most that single event. If more than one
        newer event exists in Postgres, another server advanced the execution and the
        local in-memory snapshot is stale.
        """
        if last_event_id is None:
            return True

        # Probe staleness at most once per interval for each execution.
        # This prevents invalidate/replay thrash under high parallel event rates.
        probe_interval = _STATE_CACHE_STALE_CHECK_INTERVAL_SECONDS
        execution_key = str(execution_id)
        if probe_interval > 0:
            now_monotonic = time.monotonic()
            last_probe_at = self._stale_probe_last_checked_at.get(execution_key)
            if (
                last_probe_at is not None
                and (now_monotonic - last_probe_at) < probe_interval
            ):
                return False
            self._stale_probe_last_checked_at[execution_key] = now_monotonic

        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT COUNT(*)::int AS newer_count, MAX(event_id) AS latest_event_id
                    FROM noetl.event
                    WHERE execution_id = %s AND event_id > %s
                    """,
                    (int(execution_id), int(last_event_id)),
                )
                row = await cur.fetchone()

        newer_count = int((row or {}).get("newer_count", 0) or 0)
        latest_event_id = (row or {}).get("latest_event_id")
        refresh = newer_count > max(0, allowed_missing_events)
        if refresh:
            logger.warning(
                "[STATE-CACHE-STALE] execution_id=%s last_event_id=%s latest_event_id=%s newer_count=%s threshold=%s",
                execution_id,
                last_event_id,
                latest_event_id,
                newer_count,
                max(0, allowed_missing_events),
            )
        return refresh
    
    async def load_state(self, execution_id: str) -> Optional[ExecutionState]:
        """Load execution state from memory or reconstruct from events."""
        # Check memory first
        cached = await self._memory_cache.get(execution_id)
        if cached:
            logger.debug(
                "[STATE-CACHE-HIT] execution_id=%s issued_steps=%s completed_steps=%s",
                execution_id,
                len(cached.issued_steps),
                len(cached.completed_steps),
            )
            return cached
        logger.debug(f"[STATE-CACHE-MISS] Execution {execution_id}: reconstructing from events")
        
        # Reconstruct state from events in database using event sourcing
        async with get_pool_connection() as conn:
            # Explicitly use dict_row for predictable results
            async with conn.cursor(row_factory=dict_row) as cur:
                # Get playbook info and workload from playbook.initialized event
                await cur.execute("""
                    SELECT catalog_id, context, result
                    FROM noetl.event
                    WHERE execution_id = %s AND event_type = 'playbook.initialized'
                    ORDER BY event_id
                    LIMIT 1
                """, (int(execution_id),))

                result = await cur.fetchone()
                logger.debug(
                    "[STATE-LOAD] playbook.initialized query result_type=%s is_none=%s",
                    type(result).__name__,
                    result is None,
                )
                if not result:
                    logger.warning(f"[STATE-LOAD] No playbook.initialized event found for execution {execution_id}")
                    return None

                if isinstance(result, dict):
                    catalog_id = result.get("catalog_id")
                    event_context = result.get("context")
                    event_result = result.get("result")
                else:
                    catalog_id = result[0]
                    event_context = result[1] if len(result) > 1 else None
                    event_result = result[2] if len(result) > 2 else None
                if catalog_id is None:
                    return None
                
                # Extract workload from playbook.initialized event payload.
                # This contains the merged workload (playbook defaults + parent input)
                workload = {}
                logger.debug(
                    "[STATE-LOAD] event_result type=%s truthy=%s is_dict=%s",
                    type(event_result).__name__,
                    bool(event_result),
                    isinstance(event_result, dict) if event_result is not None else False,
                )
                if isinstance(event_context, dict):
                    workload = event_context.get("workload", {}) or {}
                if not workload and event_result and isinstance(event_result, dict):
                    result_context = event_result.get("context")
                    if isinstance(result_context, dict):
                        workload = result_context.get("workload", {}) or {}
                if not workload and event_result and isinstance(event_result, dict):
                    workload = event_result.get("workload", {}) or {}
                if isinstance(workload, dict):
                    logger.debug(
                        "[STATE-LOAD] restored workload keys=%s",
                        list(workload.keys()),
                    )
                    if not workload:
                        logger.warning(
                            "[STATE-LOAD] workload is empty (event_context keys=%s event_result keys=%s)",
                            list(event_context.keys()) if isinstance(event_context, dict) else [],
                            list(event_result.keys()) if isinstance(event_result, dict) else [],
                        )
                else:
                    logger.warning(
                        "[STATE-LOAD] Could not extract workload from playbook.initialized payload "
                        "(context_type=%s result_type=%s)",
                        type(event_context).__name__,
                        type(event_result).__name__,
                    )
                    workload = {}
                
                # Load playbook
                playbook = await self.playbook_repo.load_playbook_by_id(catalog_id)
                if not playbook:
                    return None
                
                # Create new state with restored workload
                # Note: We pass workload as the payload param so it merges properly
                # The ExecutionState.__init__ first loads playbook.workload, then merges payload
                # To avoid double-loading playbook defaults, we pass the full workload directly
                # and let the playbook.workload be overwritten
                state = ExecutionState(execution_id, playbook, workload, catalog_id)
                
                # Identify loop steps from playbook for initialization
                loop_steps = set()
                loop_step_defs: dict[str, Step] = {}
                if hasattr(playbook, 'workflow') and playbook.workflow:
                    for step in playbook.workflow:
                        if hasattr(step, 'loop') and step.loop:
                            loop_steps.add(step.step)
                            loop_step_defs[step.step] = step
                
                # Replay events to rebuild state (event sourcing)
                await cur.execute("""
                    SELECT
                        event_id,
                        parent_event_id,
                        node_name,
                        event_type,
                        CASE WHEN event_type IN ('step.exit', 'call.done', 'loop.done') THEN result ELSE NULL END AS result,
                        CASE WHEN event_type = 'command.issued' THEN meta ELSE NULL END AS meta
                    FROM noetl.event
                    WHERE execution_id = %s
                      AND event_type = ANY(%s)
                    ORDER BY event_id
                """, (int(execution_id), list(_STATE_REPLAY_EVENT_TYPES)))
                
                rows = await cur.fetchall()
                
                # Track loop iteration results during event replay (bounded in-memory tail only)
                # while preserving authoritative counts for completion math.
                loop_iteration_state: dict[str, dict[str, Any]] = {}
                loop_iteration_counts: dict[str, int] = {}
                loop_event_ids = {}  # {step_name: loop_event_id}
                replay_loop_command_ids: dict[str, set[str]] = {}
                replay_render_env = Environment(undefined=StrictUndefined)
                from noetl.core.dsl.render import render_template as recursive_render
                
                for row in rows:
                    if isinstance(row, dict):
                        event_id = row.get("event_id")
                        parent_event_id = row.get("parent_event_id")
                        node_name = row.get("node_name")
                        event_type = row.get("event_type")
                        result_data = row.get("result")
                        meta_data = row.get("meta")
                    else:
                        event_id = row[0]
                        parent_event_id = row[1]
                        node_name = row[2]
                        event_type = row[3]
                        result_data = row[4]
                        meta_data = row[5] if len(row) > 5 else None

                    if event_id is not None:
                        state.last_event_id = int(event_id)
                        if isinstance(node_name, str) and node_name:
                            state.step_event_ids[node_name] = int(event_id)

                    if event_type in _EXECUTION_TERMINAL_EVENT_TYPES:
                        state.completed = True
                        if event_type in _EXECUTION_FAILURE_EVENT_TYPES:
                            state.failed = True

                    # Track issued commands for pending detection (race condition fix)
                    if event_type == 'command.issued':
                        pending_key = _pending_step_key(node_name)
                        if pending_key:
                            state.issued_steps.add(pending_key)
                            logger.debug(f"[STATE-LOAD] Reconstructed issued_step: {pending_key}")
                        if isinstance(meta_data, dict):
                            loop_event_id = meta_data.get("loop_event_id")
                            if loop_event_id:
                                loop_step = (
                                    node_name.replace(":task_sequence", "")
                                    if isinstance(node_name, str)
                                    else node_name
                                )
                                loop_event_ids[loop_step] = str(loop_event_id)
                    elif event_type in {'command.completed', 'command.failed', 'command.cancelled'}:
                        pending_key = _pending_step_key(node_name)
                        if pending_key:
                            state.issued_steps.discard(pending_key)
                            logger.debug(
                                "[STATE-LOAD] Removed terminal command from issued_steps: %s (%s)",
                                pending_key,
                                event_type,
                            )

                    event_payload = result_data

                    # Task-sequence policy rules can mutate ctx on the worker. Replay must
                    # restore those execution-scoped variables from persisted call.done events
                    # so a cache miss on another server does not lose them.
                    if event_type == 'call.done' and isinstance(event_payload, dict) and isinstance(node_name, str) and node_name.endswith(":task_sequence"):
                        response_data = event_payload.get("result", event_payload)
                        if isinstance(response_data, dict):
                            task_ctx = response_data.get("ctx", {})
                            if isinstance(task_ctx, dict):
                                for key, value in task_ctx.items():
                                    state.variables[key] = value
                                    logger.debug("[STATE-LOAD] Replayed task-sequence ctx: %s", key)

                        # Reconstruct loop iteration progress for task-sequence loop steps.
                        # step.exit rows use :task_sequence node names and are intentionally
                        # skipped below, so call.done is the authoritative iteration signal.
                        loop_step_name = node_name.replace(":task_sequence", "")
                        if loop_step_name in loop_steps:
                            command_id = _extract_command_id_from_event_payload(event_payload)
                            seen_command_ids = replay_loop_command_ids.setdefault(loop_step_name, set())
                            if command_id and command_id in seen_command_ids:
                                logger.debug(
                                    "[STATE-LOAD] Skipping duplicate task-sequence call.done replay "
                                    "for %s command_id=%s",
                                    loop_step_name,
                                    command_id,
                                )
                            else:
                                if command_id:
                                    seen_command_ids.add(command_id)

                                if loop_step_name not in loop_iteration_state:
                                    loop_iteration_state[loop_step_name] = {
                                        "results": [],
                                        "omitted_results_count": 0,
                                        "failed_count": 0,
                                    }
                                loop_iteration_counts[loop_step_name] = int(
                                    loop_iteration_counts.get(loop_step_name, 0) or 0
                                ) + 1

                                step_loop_state = loop_iteration_state[loop_step_name]
                                iteration_result = (
                                    response_data.get("results", response_data)
                                    if isinstance(response_data, dict)
                                    else response_data
                                )
                                step_results = step_loop_state.get("results", [])
                                if not isinstance(step_results, list):
                                    step_results = []
                                step_results.append(_compact_loop_result(iteration_result))
                                retained_results, omitted_count = _retain_recent_loop_results(
                                    step_results,
                                    int(step_loop_state.get("omitted_results_count", 0) or 0),
                                )
                                step_loop_state["results"] = retained_results
                                step_loop_state["omitted_results_count"] = omitted_count
                                if isinstance(response_data, dict):
                                    status = str(response_data.get("status", "")).upper()
                                    if status in {"FAILED", "ERROR"}:
                                        step_loop_state["failed_count"] = int(
                                            step_loop_state.get("failed_count", 0) or 0
                                        ) + 1

                            loop_event_id = event_payload.get("loop_event_id")
                            if not loop_event_id and isinstance(response_data, dict):
                                loop_event_id = response_data.get("loop_event_id")
                            if loop_event_id:
                                loop_event_ids[loop_step_name] = str(loop_event_id)

                    # For loop steps, collect iteration results from step.exit events
                    if event_type == 'step.exit' and event_payload and node_name in loop_steps:
                        if node_name not in loop_iteration_state:
                            loop_iteration_state[node_name] = {
                                "results": [],
                                "omitted_results_count": 0,
                                "failed_count": 0,
                            }
                        loop_iteration_counts[node_name] = int(
                            loop_iteration_counts.get(node_name, 0) or 0
                        ) + 1

                        step_loop_state = loop_iteration_state[node_name]
                        iteration_result = (
                            event_payload.get("result", event_payload)
                            if isinstance(event_payload, dict)
                            else event_payload
                        )
                        step_results = step_loop_state.get("results", [])
                        if not isinstance(step_results, list):
                            step_results = []
                        step_results.append(_compact_loop_result(iteration_result))
                        retained_results, omitted_count = _retain_recent_loop_results(
                            step_results,
                            int(step_loop_state.get("omitted_results_count", 0) or 0),
                        )
                        step_loop_state["results"] = retained_results
                        step_loop_state["omitted_results_count"] = omitted_count
                        if isinstance(event_payload, dict):
                            status = str(event_payload.get("status", "")).upper()
                            if status in {"FAILED", "ERROR"}:
                                step_loop_state["failed_count"] = int(
                                    step_loop_state.get("failed_count", 0) or 0
                                ) + 1

                    # Mark loop steps completed based on loop.done events
                    if event_type == 'loop.done' and event_payload and node_name in loop_steps:
                        step_result = event_payload.get("result", event_payload) if isinstance(event_payload, dict) else event_payload
                        state.mark_step_completed(node_name, step_result)
                        if node_name in loop_iteration_state:
                            loop_iteration_state[node_name]["completed"] = True
                            loop_iteration_state[node_name]["aggregation_finalized"] = True

                    # Restore step results from step.exit events (final result only)
                    if event_type == 'step.exit' and event_payload:
                        # Task-sequence substeps are iteration-level internals; parent completion
                        # is driven by call.done/loop.done, not per-iteration step.exit.
                        if node_name.endswith(":task_sequence"):
                            continue

                        # For looped parent steps, step.exit is emitted per iteration and should
                        # not mark the whole step as completed during replay.
                        if node_name in loop_steps:
                            continue

                        step_result = (
                            event_payload.get("result", event_payload)
                            if isinstance(event_payload, dict)
                            else event_payload
                        )
                        step_result = await _hydrate_reference_only_step_result(step_result)
                        state.mark_step_completed(node_name, step_result)

                        step_def = state.get_step(node_name)
                        step_set = getattr(step_def, "set", None) if step_def else None
                        if step_def and step_set:
                            replay_event = Event(
                                execution_id=execution_id,
                                step=node_name,
                                name="step.exit",
                                payload=event_payload if isinstance(event_payload, dict) else {"result": event_payload},
                            )
                            context = state.get_render_context(replay_event)
                            rendered_set: dict = {}
                            for key, value_template in step_set.items():
                                try:
                                    if isinstance(value_template, str) and "{{" in value_template:
                                        rendered_set[key] = recursive_render(
                                            replay_render_env,
                                            value_template,
                                            context,
                                            strict_keys=True,
                                        )
                                    else:
                                        rendered_set[key] = value_template
                                    logger.debug("[STATE-LOAD] Replayed set %s from %s", key, node_name)
                                except Exception as exc:
                                    logger.warning(
                                        "[STATE-LOAD] Failed to replay set %s for %s: %s",
                                        key,
                                        node_name,
                                        exc,
                                    )
                            _apply_set_mutations(state.variables, rendered_set)

                    # Track emitted loop transitions to prevent duplicate restarts during replay/races
                    if event_type in {"loop.done", "loop.failed"} and event_payload:
                        loop_event_id = event_payload.get("loop_event_id") if isinstance(event_payload, dict) else None
                        if loop_event_id:
                            state.add_emitted_loop_epoch(node_name, event_type, str(loop_event_id))

                    # Track emitted loop epochs during replay to prevent duplicate recovery
                    if event_type in {"loop.done", "step.done", "step.exit"} and event_payload:
                        loop_event_id = event_payload.get("loop_event_id")
                        if loop_event_id:
                            # Unique key for this specific transition batch
                            key = f"{node_name}:{event_type}:{loop_event_id}:{parent_event_id}"
                            state.emitted_loop_epochs.add(key)
                
                # Initialize loop_state for loop steps with collected iteration results
                for step_name in loop_steps:
                    # Count iterations by counting step.exit events for this step
                    # This gives us the current loop index when reconstructing state
                    iteration_count = int(loop_iteration_counts.get(step_name, 0) or 0)
                    replay_loop_state = loop_iteration_state.get(
                        step_name,
                        {
                            "results": [],
                            "omitted_results_count": 0,
                            "failed_count": 0,
                        },
                    )
                    loop_step_def = loop_step_defs.get(step_name)
                    loop_iterator = (
                        loop_step_def.loop.iterator
                        if loop_step_def and loop_step_def.loop
                        else "item"
                    )
                    loop_mode = (
                        loop_step_def.loop.mode
                        if loop_step_def and loop_step_def.loop
                        else "sequential"
                    )
                    
                    if step_name not in state.loop_state:
                        state.loop_state[step_name] = {
                            "collection": [],
                            "iterator": loop_iterator,
                            "index": iteration_count,  # Start from number of completed iterations
                            "mode": loop_mode,
                            "completed": replay_loop_state.get("completed", False),
                            "results": replay_loop_state.get("results", []),
                            "failed_count": int(replay_loop_state.get("failed_count", 0) or 0),
                            "scheduled_count": iteration_count,
                            "aggregation_finalized": replay_loop_state.get("aggregation_finalized", False),
                            "event_id": loop_event_ids.get(step_name),
                            "omitted_results_count": int(
                                replay_loop_state.get("omitted_results_count", 0) or 0
                            ),
                        }
                        logger.debug(f"[STATE-LOAD] Initialized loop_state for {step_name}: index={iteration_count}")
                    else:
                        # Restore collected results and update index
                        state.loop_state[step_name]["results"] = replay_loop_state.get("results", [])
                        if replay_loop_state.get("completed"):
                            state.loop_state[step_name]["completed"] = True
                            state.loop_state[step_name]["aggregation_finalized"] = True
                        state.loop_state[step_name]["failed_count"] = int(
                            replay_loop_state.get("failed_count", 0) or 0
                        )
                        state.loop_state[step_name]["omitted_results_count"] = int(
                            replay_loop_state.get("omitted_results_count", 0) or 0
                        )
                        state.loop_state[step_name]["index"] = iteration_count
                        state.loop_state[step_name]["scheduled_count"] = max(
                            int(state.loop_state[step_name].get("scheduled_count", 0) or 0),
                            iteration_count,
                        )
                        state.loop_state[step_name]["iterator"] = (
                            state.loop_state[step_name].get("iterator") or loop_iterator
                        )
                        state.loop_state[step_name]["mode"] = (
                            state.loop_state[step_name].get("mode") or loop_mode
                        )
                        loop_event_id = loop_event_ids.get(step_name)
                        if loop_event_id:
                            state.loop_state[step_name]["event_id"] = loop_event_id
                        logger.debug(f"[STATE-LOAD] Updated loop_state for {step_name}: index={iteration_count}")
                
                # Restore loop completion status from NATS for loop steps that
                # completed their loop before this state rebuild. Without this,
                # `completed_steps` is empty for loop steps after rebuild, causing the
                # dedup guard in `_evaluate_next_transitions` to block loopback
                # re-dispatch (e.g. fetch_medications re-invoked after re-check step).
                try:
                    nats_cache = await get_nats_cache()
                    for step_name in loop_steps:
                        event_id = loop_event_ids.get(step_name)
                        if event_id:
                            nats_loop = await nats_cache.get_loop_state(
                                execution_id, step_name, event_id
                            )
                            if nats_loop and nats_loop.get("loop_done_claimed", False):
                                state.loop_state[step_name]["completed"] = True
                                state.loop_state[step_name]["aggregation_finalized"] = True
                                state.completed_steps.add(step_name)
                                logger.debug(
                                    "[STATE-LOAD] Restored loop completion from NATS for %s "
                                    "(loop_done_claimed=True, event_id=%s)",
                                    step_name,
                                    event_id,
                                )
                except Exception as _nats_exc:
                    logger.debug(
                        "[STATE-LOAD] NATS loop-completion restore skipped: %s", _nats_exc
                    )

                # Log reconstructed state for debugging
                if state.issued_steps:
                    logger.debug(
                        "[STATE-LOAD] Reconstructed pending commands count=%s",
                        len(state.issued_steps),
                    )
                logger.debug(
                    "[STATE-LOAD] Execution %s: completed_steps=%s issued_steps=%s",
                    execution_id,
                    len(state.completed_steps),
                    len(state.issued_steps),
                )

                # Cache and return
                await self._memory_cache.set(execution_id, state)
                return state

    def get_state(self, execution_id: str) -> Optional[ExecutionState]:
        """Get state from memory cache (sync)."""
        return self._memory_cache.get_sync(execution_id)

    async def evict_completed(self, execution_id: str):
        """Remove completed execution from cache to free memory."""
        execution_key = str(execution_id)
        deleted = await self._memory_cache.delete(execution_key)
        self._stale_probe_last_checked_at.pop(execution_key, None)
        if deleted:
            logger.info(f"Evicted completed execution {execution_id} from cache")

    async def invalidate_state(self, execution_id: str, reason: str = "manual") -> bool:
        """Invalidate cached execution state so next load reconstructs from events."""
        execution_key = str(execution_id)
        deleted = await self._memory_cache.delete(execution_key)
        self._stale_probe_last_checked_at.pop(execution_key, None)
        if deleted:
            logger.warning(
                "[STATE-CACHE-INVALIDATE] execution_id=%s reason=%s",
                execution_key,
                reason,
            )
        else:
            logger.debug(
                "[STATE-CACHE-INVALIDATE] execution_id=%s reason=%s cache_miss=true",
                execution_key,
                reason,
            )
        return deleted


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


class ControlFlowEngine:
    """
    V2 Control Flow Engine - Canonical Format.

    Processes events and evaluates next[].when transitions for conditional routing.
    Pure event-driven architecture with canonical DSL format only.
    """

    # Shared template cache across all ControlFlowEngine instances
    # This allows template reuse across executions
    _template_cache: TemplateCache = None

    def __init__(self, playbook_repo: PlaybookRepo, state_store: StateStore):
        self.playbook_repo = playbook_repo
        self.state_store = state_store
        self.jinja_env = Environment(undefined=StrictUndefined)

        # Initialize shared template cache (singleton pattern)
        if ControlFlowEngine._template_cache is None:
            ControlFlowEngine._template_cache = TemplateCache(max_size=500)

    async def finalize_abandoned_execution(
        self,
        execution_id: str,
        reason: str = "Abandoned or timed out",
    ) -> None:
        """Forcibly finalize a stuck execution with terminal failure lifecycle events."""
        state = await self.state_store.load_state(execution_id)
        if not state:
            logger.error("[FINALIZE] No state found for execution %s", execution_id)
            return
        if state.completed:
            logger.info("[FINALIZE] Execution %s already completed; skipping", execution_id)
            return

        last_step = state.current_step or (list(state.step_results.keys())[-1] if state.step_results else None)
        logger.warning(
            "[FINALIZE] Forcibly finalizing execution %s at step %s due to: %s",
            execution_id,
            last_step,
            reason,
        )

        from noetl.core.dsl.v2.models import LifecycleEventPayload

        current_event_id = state.last_event_id
        workflow_failed_event = Event(
            execution_id=execution_id,
            step="workflow",
            name="workflow.failed",
            payload=LifecycleEventPayload(
                status="failed",
                final_step=last_step,
                result=None,
                error={"message": reason},
            ).model_dump(),
            timestamp=datetime.now(timezone.utc),
            parent_event_id=current_event_id,
        )
        await self._persist_event(workflow_failed_event, state)

        playbook_path = state.playbook.metadata.get("path", "playbook")
        playbook_failed_event = Event(
            execution_id=execution_id,
            step=playbook_path,
            name="playbook.failed",
            payload=LifecycleEventPayload(
                status="failed",
                final_step=last_step,
                result=None,
                error={"message": reason},
            ).model_dump(),
            timestamp=datetime.now(timezone.utc),
            parent_event_id=state.last_event_id,
        )
        await self._persist_event(playbook_failed_event, state)

        state.failed = True
        state.completed = True
        await self.state_store.save_state(state)
        logger.info("[FINALIZE] Emitted terminal failure lifecycle events for execution %s", execution_id)
    
    def _render_value_recursive(self, value: Any, context: dict[str, Any]) -> Any:
        """Recursively render templates in nested data structures."""
        if isinstance(value, str) and "{{" in value:
            return self._render_template(value, context)
        elif isinstance(value, dict):
            return {k: self._render_value_recursive(v, context) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._render_value_recursive(item, context) for item in value]
        else:
            return value
    
    def _render_template(self, template_str: str, context: dict[str, Any]) -> Any:
        """Render Jinja2 template."""
        if not isinstance(template_str, str) or "{{" not in template_str:
            return template_str
            
        try:
            # Check if this is a simple variable reference like {{ varname }} or {{ obj.attr }}
            # If so, evaluate and return the actual object instead of string representation
            import re
            # Improved regex to handle optional spaces and nested attributes
            simple_var_match = re.match(r'^\{\{\s*([\w.]+)\s*\}\}$', template_str.strip())
            if simple_var_match:
                var_path = simple_var_match.group(1)
                # Navigate dot notation: ctx.api_url → context['ctx']['api_url']
                value = context
                parts = var_path.split('.')
                
                # OPTIMIZATION: Check top-level directly first
                if len(parts) == 1:
                    part = parts[0]
                    if part in context:
                        return context[part]
                
                for part in parts:
                    if isinstance(value, dict) and part in value:
                        value = value[part]
                    elif hasattr(value, part):
                        value = getattr(value, part)
                    else:
                        # Path doesn't resolve, fall back to Jinja rendering
                        break
                else:
                    # Successfully navigated full path
                    return value
            
            # Standard Jinja2 rendering - use cached template
            template = self._template_cache.get_or_compile(self.jinja_env, template_str)
            result = template.render(**context)
            
            # Try to parse as boolean for conditions
            if result.lower() in ("true", "false"):
                return result.lower() == "true"
            
            return result
        except Exception as e:
            logger.error(
                "Template rendering error: %s | template_preview=%s | context_keys=%s",
                e,
                (template_str[:160] + "...") if isinstance(template_str, str) and len(template_str) > 160 else template_str,
                list(context.keys()) if isinstance(context, dict) else [],
            )
            raise

    def _normalize_loop_collection(self, value: Any, step_name: str) -> list[Any]:
        """Normalize loop input to a list without accidentally exploding strings into characters."""
        if isinstance(value, list):
            return value
        if value is None:
            return []
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, set):
            return list(value)
        if isinstance(value, dict):
            logger.warning(f"[LOOP] Step {step_name}: collection rendered as dict; wrapping as single item")
            return [value]
        if isinstance(value, (str, bytes, bytearray)):
            text = value.decode("utf-8", errors="replace") if not isinstance(value, str) else value
            if "{{" in text or "{%" in text:
                logger.warning(f"[LOOP] Step {step_name}: collection template unresolved, defaulting to empty list")
                return []
            logger.warning(f"[LOOP] Step {step_name}: collection rendered as scalar string; wrapping as single item")
            return [text]
        if hasattr(value, "__iter__"):
            try:
                return list(value)
            except Exception:
                logger.warning(f"[LOOP] Step {step_name}: failed to materialize iterable collection; wrapping value")
                return [value]
        return [value]

    def _build_loop_event_id_candidates(
        self,
        state: "ExecutionState",
        step_name: str,
        loop_state: Optional[dict[str, Any]] = None,
    ) -> list[str]:
        """Build ordered candidate loop identifiers for distributed-safe NATS loop state lookup."""
        candidates: list[str] = []

        loop_event_id = loop_state.get("event_id") if loop_state else None
        if loop_event_id is not None:
            candidates.append(str(loop_event_id))

        execution_fallback = f"exec_{state.execution_id}"
        if execution_fallback not in candidates:
            candidates.append(execution_fallback)

        step_event_id = state.step_event_ids.get(step_name)
        if step_event_id is not None:
            step_event_id_str = str(step_event_id)
            if step_event_id_str not in candidates:
                candidates.append(step_event_id_str)

        return candidates

    @staticmethod
    def _loop_event_ids_compatible(
        cached_event_id: Optional[str],
        restored_event_id: Optional[str],
    ) -> bool:
        """Allow safe loop snapshot reuse across replay key normalization."""
        if cached_event_id is None or restored_event_id is None:
            return True
        cached = str(cached_event_id)
        restored = str(restored_event_id)
        if cached == restored:
            return True

        # Compatibility fallback: allow exec-key matches only for the same execution key.
        # Do not treat exec_<id> as a wildcard against loop_<...> or numeric step event ids.
        if cached.startswith("exec_") and restored.startswith("exec_"):
            return cached == restored

        return False

    def _snapshot_loop_collections(
        self,
        state: "ExecutionState",
    ) -> dict[str, dict[str, Any]]:
        """Capture active loop collection snapshots before cache invalidation."""
        snapshots: dict[str, dict[str, Any]] = {}
        for step_name, loop_state in state.loop_state.items():
            collection = loop_state.get("collection")
            if not isinstance(collection, list) or len(collection) == 0:
                continue
            epoch_size = len(collection)
            # Cap counts to epoch_size so accumulated multi-batch counts don't inflate the snapshot.
            # After a state rebuild, state.get_loop_completed_count() returns the total across all
            # epochs; capping to epoch_size keeps the snapshot epoch-relative.
            completed_count = min(state.get_loop_completed_count(step_name), epoch_size)
            scheduled_count = min(
                int(loop_state.get("scheduled_count", completed_count) or completed_count),
                epoch_size,
            )
            if scheduled_count < completed_count:
                scheduled_count = completed_count
            snapshots[step_name] = {
                "collection": list(collection),
                "epoch_size": epoch_size,
                "event_id": (
                    str(loop_state.get("event_id"))
                    if loop_state.get("event_id") is not None
                    else None
                ),
                "iterator": loop_state.get("iterator"),
                "mode": loop_state.get("mode"),
                "completed_count": completed_count,
                "scheduled_count": scheduled_count,
            }
        return snapshots

    def _restore_loop_collection_snapshots(
        self,
        state: "ExecutionState",
        snapshots: dict[str, dict[str, Any]],
    ) -> int:
        """Restore loop collections that replay could not reconstruct safely."""
        restored_count = 0
        for step_name, snapshot in snapshots.items():
            loop_state = state.loop_state.get(step_name)
            if not loop_state:
                continue

            cached_collection = snapshot.get("collection")
            if not isinstance(cached_collection, list) or len(cached_collection) == 0:
                continue

            restored_event_id = (
                str(loop_state.get("event_id"))
                if loop_state.get("event_id") is not None
                else None
            )
            cached_event_id = snapshot.get("event_id")
            if not self._loop_event_ids_compatible(cached_event_id, restored_event_id):
                continue

            current_collection = loop_state.get("collection")
            current_size = (
                len(current_collection)
                if isinstance(current_collection, list)
                else 0
            )
            cached_size = len(cached_collection)
            snapshot_completed_count = int(
                snapshot.get("completed_count", 0) or 0
            )
            snapshot_scheduled_count = int(
                snapshot.get("scheduled_count", snapshot_completed_count)
                or snapshot_completed_count
            )
            if snapshot_scheduled_count < snapshot_completed_count:
                snapshot_scheduled_count = snapshot_completed_count

            # Use epoch_size from snapshot (= len(collection) at snapshot time) to cap
            # min_required_size.  Accumulated completion counts span multiple batches and
            # would falsely inflate the threshold beyond the per-epoch batch size, causing
            # valid same-epoch snapshots to be rejected after the first batch.
            snapshot_epoch_size = int(snapshot.get("epoch_size", cached_size) or cached_size)
            completed_count = max(
                state.get_loop_completed_count(step_name),
                snapshot_completed_count,
            )
            scheduled_count = max(
                int(loop_state.get("scheduled_count", completed_count) or completed_count),
                completed_count,
                snapshot_scheduled_count,
            )
            min_required_size = max(
                1,
                min(completed_count, snapshot_epoch_size),
                min(scheduled_count, snapshot_epoch_size),
            )

            loop_mode = str(loop_state.get("mode") or snapshot.get("mode") or "").lower()
            if (
                loop_mode == "parallel"
                and cached_size <= 1
                and (scheduled_count > cached_size or completed_count > cached_size)
            ):
                logger.warning(
                    "[LOOP-CACHE-RESTORE] Skipping tiny parallel snapshot for %s "
                    "(cached_size=%s scheduled=%s completed=%s snapshot_scheduled=%s snapshot_completed=%s)",
                    step_name,
                    cached_size,
                    scheduled_count,
                    completed_count,
                    snapshot_scheduled_count,
                    snapshot_completed_count,
                )
                continue

            if cached_size < min_required_size:
                logger.warning(
                    "[LOOP-CACHE-RESTORE] Skipping snapshot restore for %s "
                    "(cached_size=%s required_min=%s scheduled=%s completed=%s "
                    "snapshot_scheduled=%s snapshot_completed=%s cached_event_id=%s restored_event_id=%s)",
                    step_name,
                    cached_size,
                    min_required_size,
                    scheduled_count,
                    completed_count,
                    snapshot_scheduled_count,
                    snapshot_completed_count,
                    cached_event_id,
                    restored_event_id,
                )
                continue

            should_restore = (
                current_size == 0
                or (current_size <= min_required_size and cached_size > current_size)
            )
            if not should_restore:
                continue

            loop_state["collection"] = list(cached_collection)
            if not loop_state.get("iterator") and snapshot.get("iterator") is not None:
                loop_state["iterator"] = snapshot.get("iterator")
            if not loop_state.get("mode") and snapshot.get("mode") is not None:
                loop_state["mode"] = snapshot.get("mode")
            loop_state["scheduled_count"] = max(
                int(loop_state.get("scheduled_count", 0) or 0),
                scheduled_count,
            )
            restored_count += 1
            logger.warning(
                "[LOOP-CACHE-RESTORE] Restored collection snapshot for %s "
                "(cached_size=%s replay_size=%s scheduled=%s completed=%s "
                "snapshot_scheduled=%s snapshot_completed=%s cached_event_id=%s restored_event_id=%s)",
                step_name,
                cached_size,
                current_size,
                scheduled_count,
                completed_count,
                snapshot_scheduled_count,
                snapshot_completed_count,
                cached_event_id,
                restored_event_id,
            )

            # After a STATE-CACHE-STALE rebuild mid-epoch, load_state accumulates results
            # from ALL prior epochs in loop_state["results"] + omitted_results_count.
            # This inflates get_loop_completed_count() to a cross-epoch total (e.g. 806 for
            # a 10×100 loop), causing previous_exhausted=True in _create_command_for_step
            # even though only ~5/100 iterations of the current epoch have completed.
            # Fix: when the cross-epoch total exceeds one epoch's size, reset results/counts
            # and index to the snapshot's epoch-relative values so downstream exhaustion
            # checks operate on the current epoch only.
            if completed_count > snapshot_epoch_size:
                epoch_relative_count = max(0, snapshot_completed_count)
                epoch_relative_scheduled = max(epoch_relative_count, snapshot_scheduled_count)
                loop_state["results"] = []
                loop_state["omitted_results_count"] = epoch_relative_count
                loop_state["index"] = epoch_relative_count
                loop_state["scheduled_count"] = epoch_relative_scheduled
                logger.warning(
                    "[LOOP-CACHE-RESTORE] Reset loop counts to epoch-relative for %s "
                    "(cross_epoch_total=%s epoch_size=%s epoch_relative=%s epoch_scheduled=%s)",
                    step_name,
                    completed_count,
                    snapshot_epoch_size,
                    epoch_relative_count,
                    epoch_relative_scheduled,
                )

        return restored_count

    async def _count_step_events(
        self,
        execution_id: str,
        node_name: str,
        event_type: str,
    ) -> int:
        """Count persisted events for a node/event pair (best-effort fallback path)."""
        try:
            node_names = list(_node_name_candidates(node_name))
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT COUNT(*) AS cnt
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND node_name = ANY(%s)
                          AND event_type = %s
                        """,
                        (int(execution_id), node_names, event_type),
                    )
                    row = await cur.fetchone()
                    return int((row or {}).get("cnt", 0) or 0)
        except Exception as exc:
            logger.warning(
                "[TASK_SEQ-LOOP] Failed to count %s events for %s/%s: %s",
                event_type,
                execution_id,
                node_name,
                exc,
            )
            return -1

    async def _count_persisted_command_events(
        self,
        execution_id: str,
        event_type: str,
        command_id: str,
    ) -> int:
        """Count persisted events by command_id for actionable idempotency guards."""
        try:
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT COUNT(*) AS cnt
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND event_type = %s
                          AND meta ? 'command_id'
                          AND meta->>'command_id' = %s
                        """,
                        (int(execution_id), event_type, str(command_id)),
                    )
                    row = await cur.fetchone()
                    return int((row or {}).get("cnt", 0) or 0)
        except Exception as exc:
            logger.warning(
                "[EVENT-DEDUPE] Failed to count persisted %s events for %s command_id=%s: %s",
                event_type,
                execution_id,
                command_id,
                exc,
            )
            return -1

    async def _find_missing_loop_iteration_indices(
        self,
        execution_id: str,
        node_name: str,
        loop_event_id: Optional[str] = None,
        limit: int = 10,
        min_age_seconds: float = _TASKSEQ_LOOP_MISSING_MIN_AGE_SECONDS,
    ) -> list[int]:
        """
        Find loop iteration indexes that were issued but never started and have no terminal event.

        Guards against false positives from healthy in-flight commands by only
        considering unstarted commands older than the minimum age threshold.
        """
        if limit <= 0:
            return []

        try:
            loop_filter = ""
            node_names = list(_node_name_candidates(node_name))
            issued_params: list[Any] = [int(execution_id), node_names]
            if loop_event_id:
                loop_filter = "AND meta->>'loop_event_id' = %s"
                issued_params.append(str(loop_event_id))

            min_age = max(0.0, float(min_age_seconds or 0.0))
            params: list[Any] = [
                *issued_params,
                int(execution_id),
                node_names,
                int(execution_id),
                node_names,
                min_age,
                int(limit),
            ]

            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        f"""
                        WITH issued AS (
                            SELECT
                                meta->>'command_id' AS command_id,
                                NULLIF(meta->>'loop_iteration_index', '')::int AS loop_iteration_index,
                                created_at AS issued_at
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type = 'command.issued'
                              {loop_filter}
                        ),
                        started AS (
                            SELECT
                                COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                ) AS command_id,
                                MAX(created_at) AS started_at
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type = 'command.started'
                              AND COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                  ) IS NOT NULL
                              AND COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                  ) IN (
                                    SELECT command_id FROM issued WHERE command_id IS NOT NULL
                                  )
                            GROUP BY COALESCE(
                                meta->>'command_id',
                                result->'context'->>'command_id',
                                context->>'command_id'
                            )
                        ),
                        terminal AS (
                            SELECT DISTINCT
                                COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                ) AS command_id
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type IN ('command.completed', 'command.failed', 'command.cancelled', 'call.done')
                              AND COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                  ) IS NOT NULL
                              AND COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                  ) IN (
                                    SELECT command_id FROM issued WHERE command_id IS NOT NULL
                                  )
                        )
                        SELECT i.loop_iteration_index
                        FROM issued i
                        LEFT JOIN started s ON s.command_id = i.command_id
                        LEFT JOIN terminal t ON t.command_id = i.command_id
                        WHERE i.loop_iteration_index IS NOT NULL
                          AND t.command_id IS NULL
                          AND i.issued_at <= (NOW() - (%s * INTERVAL '1 second'))
                          AND s.command_id IS NULL
                        ORDER BY i.loop_iteration_index
                        LIMIT %s
                        """,
                        tuple(params),
                    )
                    rows = await cur.fetchall()

            return [
                int(row.get("loop_iteration_index"))
                for row in rows or []
                if row.get("loop_iteration_index") is not None
            ]
        except Exception as exc:
            logger.warning(
                "[TASK_SEQ-LOOP] Failed to detect missing loop iterations for %s/%s: %s",
                execution_id,
                node_name,
                exc,
            )
            return []

    async def _find_orphaned_loop_iteration_indices(
        self,
        execution_id: str,
        node_name: str,
        loop_event_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[int]:
        """Find issued loop indexes that never started and have no terminal event."""
        if limit <= 0:
            return []

        try:
            loop_filter = ""
            node_names = list(_node_name_candidates(node_name))
            issued_params: list[Any] = [int(execution_id), node_names]
            if loop_event_id:
                loop_filter = "AND meta->>'loop_event_id' = %s"
                issued_params.append(str(loop_event_id))

            params: list[Any] = [
                *issued_params,
                int(execution_id),
                node_names,
                int(execution_id),
                node_names,
                int(limit),
            ]

            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        f"""
                        WITH issued AS (
                            SELECT
                                meta->>'command_id' AS command_id,
                                NULLIF(meta->>'loop_iteration_index', '')::int AS loop_iteration_index
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type = 'command.issued'
                              {loop_filter}
                        ),
                        started AS (
                            SELECT DISTINCT
                                COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                ) AS command_id
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type = 'command.started'
                              AND COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                  ) IS NOT NULL
                              AND COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                  ) IN (
                                    SELECT command_id FROM issued WHERE command_id IS NOT NULL
                                  )
                        ),
                        terminal AS (
                            SELECT DISTINCT
                                COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                ) AS command_id
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type IN ('command.completed', 'command.failed', 'command.cancelled', 'call.done')
                              AND COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                  ) IS NOT NULL
                              AND COALESCE(
                                    meta->>'command_id',
                                    result->'context'->>'command_id',
                                    context->>'command_id'
                                  ) IN (
                                    SELECT command_id FROM issued WHERE command_id IS NOT NULL
                                  )
                        )
                        SELECT i.loop_iteration_index
                        FROM issued i
                        LEFT JOIN started s ON s.command_id = i.command_id
                        LEFT JOIN terminal t ON t.command_id = i.command_id
                        WHERE i.loop_iteration_index IS NOT NULL
                          AND s.command_id IS NULL
                          AND t.command_id IS NULL
                        ORDER BY i.loop_iteration_index
                        LIMIT %s
                        """,
                        tuple(params),
                    )
                    rows = await cur.fetchall()

            return [
                int(row.get("loop_iteration_index"))
                for row in rows or []
                if row.get("loop_iteration_index") is not None
            ]
        except Exception as exc:
            logger.warning(
                "[TASK_SEQ-LOOP] Failed to detect orphaned loop iterations for %s/%s: %s",
                execution_id,
                node_name,
                exc,
            )
            return []

    def _get_loop_max_in_flight(self, step: Step) -> int:
        """Resolve max in-flight limit for loop scheduling."""
        if not step.loop:
            return 1
        if step.loop.mode != "parallel":
            return 1
        if step.loop.spec and step.loop.spec.max_in_flight:
            return max(1, int(step.loop.spec.max_in_flight))
        return 1

    async def _issue_loop_commands(
        self,
        state: "ExecutionState",
        step_def: Step,
        step_input: dict[str, Any],
    ) -> list[Command]:
        """Issue one or more loop commands based on loop mode and max_in_flight."""
        if not step_def.loop:
            command = await self._create_command_for_step(state, step_def, step_input)
            return [command] if command else []

        issue_budget = self._get_loop_max_in_flight(step_def)
        commands: list[Command] = []

        for _ in range(issue_budget):
            command = await self._create_command_for_step(state, step_def, step_input)
            if not command:
                break
            commands.append(command)

        return commands
    
    def _evaluate_condition(self, when_expr: str, context: dict[str, Any]) -> bool:
        """Evaluate when condition."""
        try:
            # Render the condition
            result = self._render_template(when_expr, context)
            
            # Convert to boolean
            if isinstance(result, bool):
                logger.debug("[COND] Evaluated condition -> %s", result)
                return result
            if isinstance(result, str):
                # Check for explicit false values, otherwise treat non-empty strings as truthy
                is_false = result.lower() in ("false", "0", "no", "none", "")
                is_true = not is_false
                logger.debug("[COND] Evaluated string condition -> %s", is_true)
                return is_true
            bool_result = bool(result)
            logger.debug("[COND] Evaluated condition value_type=%s -> %s", type(result).__name__, bool_result)
            return bool_result
        except Exception as e:
            logger.error(
                "Condition evaluation error: %s | condition_preview=%s",
                e,
                (when_expr[:160] + "...") if isinstance(when_expr, str) and len(when_expr) > 160 else when_expr,
            )
            return False
    
    async def _evaluate_next_transitions(
        self,
        state: ExecutionState,
        step_def: Step,
        event: Event
    ) -> list[Command]:
        commands, _actionable_match = await self._evaluate_next_transitions_with_match(
            state,
            step_def,
            event,
        )
        return commands

    async def _evaluate_next_transitions_with_match(
        self,
        state: ExecutionState,
        step_def: Step,
        event: Event,
    ) -> tuple[list[Command], bool]:
        """
        Evaluate next[].when conditions and return commands plus matched-arc status.

        The boolean return is True when any arc condition matched AND the target step
        exists in the playbook.  A matched-but-deduplicated arc (target already in
        issued_steps) still returns True — the command is already in flight, so this
        is not a dead-end.

        Canonical format routing using next[].when:
        - Each next entry has optional 'when' condition
        - Entries without 'when' always match
        - next_mode controls evaluation: exclusive (first match) or inclusive (all matches)

        Example:
            next:
              - step: success_handler
                when: "{{ output.status == 'success' }}"
              - step: error_handler
                when: "{{ output.status == 'error' }}"
              - step: default_handler  # No when = always matches
        """
        commands = []
        context = state.get_render_context(event)

        # Get next_mode from next.spec.mode (canonical v10 - not step.spec.next_mode)
        next_mode = "exclusive"
        if step_def.next:
            # next is normalized to router format: {spec: {mode: ...}, arcs: [...]}
            if isinstance(step_def.next, dict):
                next_spec = step_def.next.get("spec", {})
                if isinstance(next_spec, dict) and "mode" in next_spec:
                    next_mode = next_spec.get("mode", "exclusive")

        if not step_def.next:
            return commands, False

        # Normalize next to list of dicts (arcs)
        next_items = step_def.next
        if isinstance(next_items, str):
            # String shorthand: next: "step_name"
            next_items = [{"step": next_items}]
        elif isinstance(next_items, dict):
            # V10 router format: {spec: {...}, arcs: [...]}
            if "arcs" in next_items:
                next_items = next_items.get("arcs", [])
            elif "step" in next_items:
                # Legacy single target: {step: "name", when: "..."}
                next_items = [next_items]
            else:
                next_items = []
        elif isinstance(next_items, list):
            # Legacy list format: [{ step: ... }, ...]
            next_items = [
                item if isinstance(item, dict) else {"step": item}
                for item in next_items
            ]

        logger.info(f"[NEXT-EVAL] Step {event.step} has {len(next_items)} next targets, mode={next_mode}, evaluating for event {event.name}")

        any_matched = False

        for idx, next_target in enumerate(next_items):
            target_step = next_target.get("step")
            when_condition = next_target.get("when")
            # Canonical DSL v2: arc.set contains transition-scoped mutations.
            arc_set = next_target.get("set") or {}

            if not target_step:
                logger.warning(f"[NEXT-EVAL] Skipping next entry {idx} with no step")
                continue

            # Evaluate when condition (if present)
            if when_condition:
                logger.debug(f"[NEXT-EVAL] Evaluating next[{idx}].when: {when_condition}")
                if not self._evaluate_condition(when_condition, context):
                    logger.debug(f"[NEXT-EVAL] Next[{idx}] condition not matched: {when_condition}")
                    continue
                logger.info(f"[NEXT-MATCH] Step {event.step}: matched next[{idx}] -> {target_step} (when: {when_condition})")
            else:
                # No when condition = always matches
                logger.info(f"[NEXT-MATCH] Step {event.step}: matched next[{idx}] -> {target_step} (unconditional)")

            # Get target step definition — must exist before we count this as a match
            target_step_def = state.get_step(target_step)
            if not target_step_def:
                logger.error(f"[NEXT-EVAL] Target step not found: {target_step}")
                continue

            # Arc condition matched AND target step exists.
            any_matched = True

            # DEDUPLICATION: Skip if command for this step is already pending.
            # A matched-but-deduplicated arc is NOT a dead-end — the command is
            # already in flight from a concurrent event processor.
            # Exception: loop steps whose previous epoch is done (loop_done_claimed)
            # must be allowed to re-dispatch for loopback patterns. After a state
            # rebuild completed_steps is empty for loop steps, but is_loop_done()
            # returns True when NATS loop_done_claimed was restored during rebuild.
            if target_step in state.issued_steps and target_step not in state.completed_steps:
                if state.is_loop_done(target_step):
                    logger.debug(
                        "[NEXT-EVAL] Allowing re-dispatch of loop step '%s' — "
                        "previous epoch is done (loopback pattern)",
                        target_step,
                    )
                else:
                    logger.warning(f"[NEXT-EVAL] Skipping duplicate command for step '{target_step}' - already in issued_steps")
                    continue

            # Apply arc-level set mutations to state before issuing the command.
            # Canonical DSL v2: arc.set writes to ctx/iter/step scopes.
            if arc_set:
                from noetl.core.dsl.render import render_template as recursive_render
                rendered_arc_set = recursive_render(self.jinja_env, arc_set, context)
                _apply_set_mutations(state.variables, rendered_arc_set)

            # Create command(s) for target step. Loop steps may issue multiple commands
            # immediately up to max_in_flight when parallel mode is configured.
            issued_cmds = await self._issue_loop_commands(state, target_step_def, {})
            if issued_cmds:
                commands.extend(issued_cmds)
                # Steps can be revisited in loopback workflows; clear old completion marker
                # so pending tracking reflects the new in-flight invocation.
                state.completed_steps.discard(target_step)
                # CRITICAL: Mark step as issued immediately to prevent duplicate commands
                # from parallel event processing
                state.issued_steps.add(target_step)
                logger.info(
                    f"[NEXT-MATCH] Created {len(issued_cmds)} command(s) for step {target_step}, "
                    "added to issued_steps"
                )

            # In exclusive mode: first match wins
            if next_mode == "exclusive":
                break

        if not any_matched:
            logger.debug(f"[NEXT-EVAL] No next targets matched for step {event.step}")

        return commands, any_matched

    def _has_matching_next_transition(
        self,
        state: ExecutionState,
        step_def: Step,
        context: dict[str, Any],
    ) -> bool:
        """Return True when a next arc condition matches and target step exists."""
        if not step_def.next:
            return False

        next_items = step_def.next
        if isinstance(next_items, str):
            next_items = [{"step": next_items}]
        elif isinstance(next_items, dict):
            if "arcs" in next_items:
                next_items = next_items.get("arcs", [])
            elif "step" in next_items:
                next_items = [next_items]
            else:
                next_items = []
        elif isinstance(next_items, list):
            next_items = [
                item if isinstance(item, dict) else {"step": item}
                for item in next_items
            ]

        for next_target in next_items:
            target_step = next_target.get("step")
            if not target_step:
                continue
            when_condition = next_target.get("when")
            if state.get_step(target_step) is None:
                logger.warning("[NEXT-EVAL] Skipping missing next target step: %s", target_step)
                continue
            if not when_condition:
                return True
            if self._evaluate_condition(when_condition, context):
                return True
        return False

    async def _process_then_actions_with_break(
        self,
        then_block: dict | list,
        state: ExecutionState,
        event: Event
    ) -> tuple[list[Command], bool]:
        """
        Process then actions and return (commands, has_next).

        Returns True for has_next if a next: action was encountered,
        which signals that evaluation should break in inclusive mode.
        """
        commands = await self._process_then_actions(then_block, state, event)

        # Check if any action was a next: transition
        actions = then_block if isinstance(then_block, list) else [then_block]
        has_next = any(
            isinstance(action, dict) and "next" in action
            for action in actions
        )

        return commands, has_next
    
    async def _process_then_actions(
        self,
        then_block: dict | list,
        state: ExecutionState,
        event: Event
    ) -> list[Command]:
        """
        Process actions in a then block.

        Supports:
        - Task sequences: labeled tasks with tool.eval: for flow control
        - Reserved action types: next, set, fail, collect, retry, call
        - Inline tasks with tool: { task_name: { tool: { kind: ... } } }

        IMPORTANT: Actions are processed sequentially. If inline tasks are present,
        the 'next' action is deferred until all inline tasks complete. This prevents
        race conditions where the next step runs before inline tasks finish.
        """
        commands: list[Command] = []
        inline_task_commands: list[Command] = []
        deferred_next_actions: list[dict] = []

        # Reserved action keys that are not named tasks
        # Any key not in this set that contains a tool: is treated as an inline task
        # NOTE: 'vars' REMOVED in strict v10
        reserved_actions = {"next", "set", "fail", "collect", "retry", "call"}

        # Normalize to list
        actions = then_block if isinstance(then_block, list) else [then_block]

        context = state.get_render_context(event)

        # Check for task sequence (labeled tasks with tool: containing eval:)
        # Task sequences are executed as atomic units by a single worker
        from noetl.worker.task_sequence_executor import is_task_sequence, extract_task_sequence

        if is_task_sequence(actions):
            # Extract labeled tool tasks and remaining actions
            task_list, remaining_actions = extract_task_sequence(actions)

            if task_list:
                # Create a single command for the task sequence
                logger.info(f"[TASK_SEQ] Processing task sequence for step {event.step} with {len(task_list)} tasks")
                command = await self._create_task_sequence_command(
                    state, event.step, task_list, remaining_actions, context
                )
                if command:
                    commands.append(command)

                # Process any immediate actions (set, etc. - not next)
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    # Skip labeled tasks (they're in the task sequence)
                    is_task = any(
                        key not in {"next", "set", "fail", "collect", "retry", "call"}
                        and isinstance(val, dict) and "tool" in val
                        for key, val in action.items()
                    )
                    if is_task:
                        continue
                    await self._process_immediate_actions(action, state, context, event, commands)

                return commands
        max_pages_env = os.getenv("NOETL_PAGINATION_MAX_PAGES", "100")
        try:
            max_pages = max(1, int(max_pages_env))
        except ValueError:
            max_pages = 100

        # First pass: collect inline tasks and identify next actions
        for action in actions:
            if not isinstance(action, dict):
                continue

            handled_pagination_retry = False

            # Check for named tasks with tool: inside
            # Format: { task_name: { tool: { kind: ... } } }
            for task_name, task_config in action.items():
                if task_name in reserved_actions:
                    continue  # Will be handled by specific handlers below
                if isinstance(task_config, dict) and "tool" in task_config:
                    # This is a named task - create a command for it
                    tool_spec = task_config["tool"]
                    if isinstance(tool_spec, dict) and "kind" in tool_spec:
                        logger.info(f"[THEN-TASK] Processing named task '{task_name}' with tool kind '{tool_spec.get('kind')}'")
                        command = await self._create_inline_command(
                            state, event.step, task_name, tool_spec, context
                        )
                        if command:
                            inline_task_commands.append(command)

            # Collect next actions for potential deferral
            if "next" in action:
                deferred_next_actions.append(action)

        # If there are inline tasks, defer next actions until they complete
        if inline_task_commands:
            # Store the deferred next actions in state, keyed by the inline task step names
            inline_task_step_names = [cmd.step for cmd in inline_task_commands]
            if deferred_next_actions:
                # Store pending next actions for each inline task
                # The last inline task to complete will trigger the next actions
                for inline_step in inline_task_step_names:
                    if not hasattr(state, 'pending_next_actions'):
                        state.pending_next_actions = {}
                    state.pending_next_actions[inline_step] = {
                        'next_actions': deferred_next_actions,
                        'inline_tasks': set(inline_task_step_names),
                        'context_event_step': event.step
                    }
                logger.info(f"[THEN-TASK] Deferred {len(deferred_next_actions)} next action(s) until inline tasks complete: {inline_task_step_names}")

            # Return only inline task commands (next actions are deferred)
            commands.extend(inline_task_commands)

            # Still process non-next reserved actions (set, fail, collect, retry, call)
            for action in actions:
                if not isinstance(action, dict):
                    continue
                # Process immediate actions that don't depend on inline task completion.
                await self._process_immediate_actions(action, state, context, event, commands)

            return commands

        # No inline tasks - process all actions normally including next
        commands.extend(inline_task_commands)

        for action in actions:
            if not isinstance(action, dict):
                continue

            handled_pagination_retry = False

            # Handle different reserved action types
            if "next" in action:
                # Transition to next step(s)
                # Support both old format: { next: "step" } or { next: ["step1", "step2"] }
                # And new format: { next: { next: [{ step: "step" }] } }
                next_value = action["next"]

                # Check for new nested format: { next: { next: [...] } }
                if isinstance(next_value, dict) and "next" in next_value:
                    next_items = next_value["next"]
                    if not isinstance(next_items, list):
                        next_items = [next_items]
                else:
                    # Old format
                    next_items = next_value if isinstance(next_value, list) else [next_value]

                for next_item in next_items:
                    if isinstance(next_item, str):
                        # Simple step name
                        target_step = next_item
                        arc_set_legacy = {}
                    elif isinstance(next_item, dict):
                        # {step: name, set: {...}} (canonical)
                        target_step = next_item.get("step")
                        arc_set_legacy = next_item.get("set") or {}

                        # Render and apply arc-level set mutations
                        if arc_set_legacy:
                            rendered_arc = {}
                            for key, value in arc_set_legacy.items():
                                if isinstance(value, str) and "{{" in value:
                                    rendered_arc[key] = self._render_template(value, context)
                                else:
                                    rendered_arc[key] = value
                            _apply_set_mutations(state.variables, rendered_arc)
                    else:
                        continue

                    # Get target step definition
                    step_def = state.get_step(target_step)
                    if not step_def:
                        logger.error(f"Target step not found: {target_step}")
                        continue

                    # Create command for target step
                    issued_cmds = await self._issue_loop_commands(
                        state, step_def, {}
                    )
                    if issued_cmds:
                        commands.extend(issued_cmds)
            
            elif "set" in action:
                # Set variables
                set_data = action["set"]
                for key, value in set_data.items():
                    if isinstance(value, str) and "{{" in value:
                        state.variables[key] = self._render_template(value, context)
                    else:
                        state.variables[key] = value
            
            elif "fail" in action:
                # Mark execution as failed
                state.failed = True
                logger.info(f"Execution {state.execution_id} marked as failed")
            
            if "collect" in action:
                # Collect data for pagination accumulation
                collect_spec = action["collect"]
                strategy = collect_spec.get("strategy", "append")  # append, extend, replace
                path = collect_spec.get("path")  # Path to extract from response
                into_var = collect_spec.get("into", "_collected_pages")  # Target variable name (reserved for future vars usage)

                # Initialize pagination state for this step if needed
                step_name = event.step
                if step_name not in state.pagination_state:
                    state.pagination_state[step_name] = {
                        "collected_data": [],
                        "iteration_count": 0,
                        "pending_retry": False
                    }

                # Extract data from strict result envelope.
                result_data = event.payload.get("result")

                if result_data is None:
                    logger.warning(f"[COLLECT] No result payload to collect for step {step_name}")
                else:
                    data_to_collect = result_data
                    if path and isinstance(result_data, dict):
                        for part in path.split("."):
                            if isinstance(data_to_collect, dict) and part in data_to_collect:
                                data_to_collect = data_to_collect[part]
                            else:
                                logger.warning(f"Path {path} not found in result for collect")
                                data_to_collect = None
                                break

                    if data_to_collect is not None:
                        # Collect data based on strategy
                        collected = state.pagination_state[step_name]["collected_data"]
                        if strategy == "append":
                            collected.append(data_to_collect)
                        elif strategy == "extend" and isinstance(data_to_collect, list):
                            collected.extend(data_to_collect)
                        elif strategy == "replace":
                            state.pagination_state[step_name]["collected_data"] = [data_to_collect]

                        state.pagination_state[step_name]["iteration_count"] += 1
                        # If this collect matched a terminal page (no retry), clear pending flag
                        state.pagination_state[step_name]["pending_retry"] = False
                        logger.info(
                            f"[COLLECT] Accumulated {len(collected)} items for step {step_name} "
                            f"(iteration {state.pagination_state[step_name]['iteration_count']})"
                        )
                        if state.pagination_state[step_name]["iteration_count"] >= max_pages:
                            state.pagination_state[step_name]["pending_retry"] = False
                            logger.warning(
                                f"[PAGINATION] Reached max_pages={max_pages} for step {step_name}; stopping pagination retries"
                            )

            # Pagination retry (params/url/etc) can coexist with collect
            pagination_retry_spec = action.get("retry") if isinstance(action, dict) else None
            if pagination_retry_spec and isinstance(pagination_retry_spec, dict) and any(
                key in pagination_retry_spec for key in ["params", "url", "method", "headers", "body", "data"]
            ):
                retry_spec = pagination_retry_spec
                handled_pagination_retry = True

                # Hard cap pagination retries to avoid infinite loops
                iteration_count = state.pagination_state.get(event.step, {}).get("iteration_count", 0)
                if iteration_count >= max_pages:
                    state.pagination_state.setdefault(event.step, {}).setdefault("pending_retry", False)
                    state.pagination_state[event.step]["pending_retry"] = False
                    logger.warning(
                        f"[PAGINATION] Skip retry for {event.step}: iteration_count={iteration_count} reached max_pages={max_pages}"
                    )
                    continue

                # Get current step definition
                step_def = state.get_step(event.step)
                if not step_def:
                    logger.error(f"Cannot retry: step {event.step} not found")
                    continue

                # Extract updated parameters from retry spec
                updated_args = {}

                # Process params field (most common for HTTP pagination)
                if "params" in retry_spec:
                    params = retry_spec["params"]
                    rendered_params = {}
                    for key, value in params.items():
                        if isinstance(value, str) and "{{" in value:
                            rendered_params[key] = self._render_template(value, context)
                        else:
                            rendered_params[key] = value

                    # HTTP tool expects runtime pagination overrides under input['params']
                    updated_args["params"] = rendered_params

                # Process other updatable fields
                for field in ["url", "method", "headers", "body", "data"]:
                    if field in retry_spec:
                        value = retry_spec[field]
                        if isinstance(value, str) and "{{" in value:
                            updated_args[field] = self._render_template(value, context)
                        else:
                            updated_args[field] = value

                # For looped steps, keep the same item by rewinding the index before command creation
                loop_state = state.loop_state.get(event.step)
                rewind_applied = False
                if loop_state and loop_state["index"] > 0:
                    loop_state["index"] -= 1
                    rewind_applied = True
                    logger.info(
                        f"[RETRY] Rewound loop index for step {event.step} to reuse current item "
                        f"(index now {loop_state['index']})"
                    )

                # Create retry command with updated input (same step)
                retry_args_with_control = dict(updated_args)
                if loop_state is not None:
                    retry_args_with_control["__loop_retry"] = True
                    retry_args_with_control["__loop_retry_index"] = max(
                        int(loop_state.get("index", 0) or 0),
                        0,
                    )
                command = await self._create_command_for_step(state, step_def, retry_args_with_control)

                # If creation failed, restore index
                if not command and rewind_applied and loop_state:
                    loop_state["index"] += 1
                if command:
                    state.pagination_state.setdefault(event.step, {}).setdefault("pending_retry", False)
                    state.pagination_state[event.step]["pending_retry"] = True
                    commands.append(command)
                    logger.info(
                        f"[RETRY] Created pagination retry command for {event.step} with updated params: {list(updated_args.keys())}"
                    )

            if "call" in action:
                # Call/invoke a step with new arguments
                call_spec = action["call"]
                target_step = call_spec.get("step")
                call_input = call_spec.get("input") or {}
                
                if not target_step:
                    logger.warning("Call action missing 'step' attribute")
                    continue
                
                # Render input payload.
                rendered_args = {}
                for key, value in call_input.items():
                    if isinstance(value, str) and "{{" in value:
                        rendered_args[key] = self._render_template(value, context)
                    else:
                        rendered_args[key] = value
                
                # Get target step definition
                step_def = state.get_step(target_step)
                if not step_def:
                    logger.error(f"Call target step not found: {target_step}")
                    continue
                
                # Create command for target step
                command = await self._create_command_for_step(state, step_def, rendered_args)
                if command:
                    commands.append(command)
                    logger.info(f"Call action: invoking step {target_step}")
            
            if "retry" in action and not handled_pagination_retry:
                # Retry current step with optional backoff
                retry_spec = action["retry"]
                delay = retry_spec.get("delay", 0)
                max_attempts = retry_spec.get("max_attempts", 3)
                backoff = retry_spec.get("backoff", "linear")  # linear, exponential
                retry_args = retry_spec.get("input", {})  # Rendered retry input from worker
                
                # Get current attempt from event.attempt (Event model field)
                current_attempt = event.attempt if event.attempt else 1
                
                # Check if max attempts exceeded
                if current_attempt >= max_attempts:
                    logger.warning(
                        f"[RETRY-EXHAUSTED] Step {event.step} has reached max retry attempts "
                        f"({current_attempt}/{max_attempts}). Skipping retry action."
                    )
                    continue
                
                # Get current step
                step_def = state.get_step(event.step)
                if not step_def:
                    logger.error(f"Retry: current step not found: {event.step}")
                    continue
                
                logger.info(
                    "[RETRY-ACTION] Creating retry command for %s with arg_keys=%s",
                    event.step,
                    _sample_keys(retry_args),
                )
                
                # Create retry command with rendered input from worker
                command = await self._create_command_for_step(state, step_def, retry_args)
                if command:
                    # Increment attempt counter
                    command.attempt = current_attempt + 1
                    command.max_attempts = max_attempts
                    command.retry_delay = delay
                    command.retry_backoff = backoff
                    commands.append(command)
                    logger.info(
                        f"[RETRY-ACTION] Re-attempting step {event.step} "
                        f"(attempt {command.attempt}/{max_attempts})"
                    )

            # NOTE: Inline tasks (with tool: inside) are processed by the code above

        return commands

    async def _process_immediate_actions(
        self,
        action: dict,
        state: "ExecutionState",
        context: dict[str, Any],
        event: Event,
        commands: list[Command]
    ) -> None:
        """
        Process immediate (non-deferred) actions like set and fail.
        These actions don't depend on inline task completion and can run immediately.
        """
        if "set" in action:
            # Set variables
            set_data = action["set"]
            for key, value in set_data.items():
                if isinstance(value, str) and "{{" in value:
                    state.variables[key] = self._render_template(value, context)
                else:
                    state.variables[key] = value

        # NOTE: 'vars' action is REMOVED in strict v10 - use scoped 'set' assignments.

        if "fail" in action:
            # Mark execution as failed
            state.failed = True
            logger.info(f"Execution {state.execution_id} marked as failed")

    async def _process_deferred_next_actions(
        self,
        state: "ExecutionState",
        completed_inline_task: str,
        event: Event
    ) -> list[Command]:
        """
        Process deferred next actions when an inline task completes.

        This is called when an inline task's step.exit event is received.
        It checks if all inline tasks in the group have completed, and if so,
        processes the deferred next actions.

        Args:
            state: Current execution state
            completed_inline_task: The step name of the completed inline task
            event: The step.exit event for the completed inline task

        Returns:
            List of commands for the next steps, or empty if not all inline tasks are done
        """
        commands: list[Command] = []

        if not hasattr(state, 'pending_next_actions'):
            return commands

        pending = state.pending_next_actions.get(completed_inline_task)
        if not pending:
            return commands

        inline_tasks = pending['inline_tasks']
        next_actions = pending['next_actions']
        context_event_step = pending['context_event_step']

        # Check if all inline tasks in this group have completed
        all_completed = all(task in state.completed_steps for task in inline_tasks)

        if not all_completed:
            logger.debug(f"[DEFERRED-NEXT] Not all inline tasks completed yet. Waiting for: {inline_tasks - state.completed_steps}")
            return commands

        logger.info(f"[DEFERRED-NEXT] All inline tasks completed, processing {len(next_actions)} deferred next action(s)")

        # Get context from the original step that triggered the inline tasks
        # Create a synthetic event for context
        context_event = Event(
            execution_id=event.execution_id,
            step=context_event_step,
            name="call.done",
            payload=event.payload,
            timestamp=event.timestamp
        )
        context = state.get_render_context(context_event)

        # Process each deferred next action
        for action in next_actions:
            if "next" not in action:
                continue

            next_value = action["next"]

            # Check for new nested format: { next: { next: [...] } }
            if isinstance(next_value, dict) and "next" in next_value:
                next_items = next_value["next"]
                if not isinstance(next_items, list):
                    next_items = [next_items]
            else:
                # Old format
                next_items = next_value if isinstance(next_value, list) else [next_value]

            for next_item in next_items:
                if isinstance(next_item, str):
                    target_step = next_item
                    deferred_arc_set: dict = {}
                elif isinstance(next_item, dict):
                    target_step = next_item.get("step")
                    deferred_arc_set = next_item.get("set") or {}

                    # Render and apply arc-level set mutations
                    if deferred_arc_set:
                        rendered_deferred: dict = {}
                        for key, value in deferred_arc_set.items():
                            if isinstance(value, str) and "{{" in value:
                                rendered_deferred[key] = self._render_template(value, context)
                            else:
                                rendered_deferred[key] = value
                        _apply_set_mutations(state.variables, rendered_deferred)
                else:
                    continue

                # Get target step definition
                step_def = state.get_step(target_step)
                if not step_def:
                    logger.error(f"[DEFERRED-NEXT] Target step not found: {target_step}")
                    continue

                # Create command for target step
                issued_cmds = await self._issue_loop_commands(state, step_def, {})
                if issued_cmds:
                    commands.extend(issued_cmds)
                    logger.info(
                        f"[DEFERRED-NEXT] Created {len(issued_cmds)} command(s) for step: {target_step}"
                    )

        # Clean up pending actions for all inline tasks in this group
        for task in inline_tasks:
            if task in state.pending_next_actions:
                del state.pending_next_actions[task]

        return commands

    async def _create_inline_command(
        self,
        state: ExecutionState,
        step_name: str,
        task_name: str,
        tool_spec: dict[str, Any],
        context: dict[str, Any]
    ) -> Optional[Command]:
        """
        Create a command for an inline tool execution from a then: block.

        This handles named tasks in then: blocks like:
        then:
          - send_callback:
              tool:
                kind: gateway
                action: callback
                data:
                  status: "{{ output.status }}"

        Args:
            state: Current execution state
            step_name: The step this task belongs to
            task_name: Name of the task (e.g., "send_callback")
            tool_spec: Tool specification dict with kind and other config
            context: Render context for Jinja2 templates

        Returns:
            Command object or None if tool kind is missing
        """
        tool_kind = tool_spec.get("kind")
        if not tool_kind:
            logger.warning(f"[INLINE-TASK] Task '{task_name}' missing tool kind")
            return None

        # Extract tool config (everything except 'kind')
        tool_config = {k: v for k, v in tool_spec.items() if k != "kind"}

        # Render Jinja2 templates in tool config
        from noetl.core.dsl.render import render_template as recursive_render
        rendered_tool_config = recursive_render(self.jinja_env, tool_config, context)

        # Create command for inline task
        # Use step_name as the step, task_name in metadata for tracking
        command = Command(
            execution_id=state.execution_id,
            step=f"{step_name}:{task_name}",  # Composite step name to track task
            tool=ToolCall(
                kind=tool_kind,
                config=rendered_tool_config
            ),
            input={},
            render_context=context,
            attempt=1,
            priority=0,
            metadata={"inline_task": True, "task_name": task_name, "parent_step": step_name}
        )

        logger.info(f"[INLINE-TASK] Created command for task '{task_name}' (kind={tool_kind})")
        return command

    async def _create_task_sequence_command(
        self,
        state: ExecutionState,
        step_name: str,
        task_list: list[dict[str, Any]],
        remaining_actions: list[dict[str, Any]],
        context: dict[str, Any]
    ) -> Optional[Command]:
        """
        Create a command for a task sequence execution.

        Task sequences are executed as atomic units by a single worker.
        The worker handles task sequencing, eval: flow control, and control flow locally.

        Args:
            state: Current execution state
            step_name: The step this task sequence belongs to
            task_list: List of labeled tasks:
                [
                    {"fetch": {"tool": {"kind": "http", "eval": [...]}}},
                    {"transform": {"tool": {"kind": "python", ...}}},
                    ...
                ]
            remaining_actions: Non-task actions to process after sequence (next, etc.)
            context: Render context for Jinja2 templates

        Returns:
            Command object for the task sequence
        """
        if not task_list:
            logger.warning(f"[TASK_SEQ] Empty task sequence for step {step_name}")
            return None

        # Get task names for logging
        task_names = []
        for task in task_list:
            if isinstance(task, dict):
                task_names.extend(task.keys())

        logger.info(f"[TASK_SEQ] Creating command for step {step_name} with tasks: {task_names}")

        # Create command with "task_sequence" tool kind
        # The worker will recognize this and use TaskSequenceExecutor
        command = Command(
            execution_id=state.execution_id,
            step=f"{step_name}:task_sequence",  # Mark as task_sequence
            tool=ToolCall(
                kind="task_sequence",  # Special kind for task sequence execution
                config={
                    "tasks": task_list,
                    "remaining_actions": remaining_actions,
                }
            ),
            input={},
            render_context=context,
            attempt=1,
            priority=0,
            metadata={
                "task_sequence": True,
                "parent_step": step_name,
                "task_names": task_names,
            }
        )

        return command

    async def _create_command_for_step(
        self,
        state: ExecutionState,
        step: Step,
        transition_input: dict[str, Any]
    ) -> Optional[Command]:
        """Create a command to execute a step."""
        control_args = transition_input if isinstance(transition_input, dict) else {}
        loop_retry_requested = bool(control_args.get("__loop_retry"))
        loop_retry_index_raw = control_args.get("__loop_retry_index")
        loop_continue_requested = bool(control_args.get("__loop_continue"))
        loop_retry_index: Optional[int] = None
        loop_event_id_for_metadata: Optional[str] = None
        claimed_index: Optional[int] = None
        _nats_slot_incremented = False  # tracks whether a NATS scheduled_count was incremented
        if loop_retry_requested and loop_retry_index_raw is not None:
            try:
                loop_retry_index = int(loop_retry_index_raw)
            except (TypeError, ValueError):
                loop_retry_index = None

        # Check if step has loop configuration
        if step.loop:
            logger.debug(
                "[CREATE-CMD] Step %s has loop iterator=%s mode=%s",
                step.step,
                step.loop.iterator,
                step.loop.mode,
            )
            existing_loop_state = state.loop_state.get(step.step)
            reuse_cached_collection = (
                existing_loop_state is not None
                and (loop_continue_requested or loop_retry_requested)
                and isinstance(existing_loop_state.get("collection"), list)
                and len(existing_loop_state.get("collection") or []) > 0
            )

            if reuse_cached_collection:
                context = state.get_render_context(Event(
                    execution_id=state.execution_id,
                    step=step.step,
                    name="loop_continue",
                    payload={}
                ))
                collection = list(existing_loop_state.get("collection", []))
                logger.debug(
                    "[LOOP] Reusing cached collection for %s continuation/retry (size=%s)",
                    step.step,
                    len(collection),
                )
            else:
                if (
                    existing_loop_state is not None
                    and (loop_continue_requested or loop_retry_requested)
                ):
                    cached_collection = existing_loop_state.get("collection")
                    if isinstance(cached_collection, list) and len(cached_collection) == 0:
                        logger.info(
                            "[LOOP] Replayed cached collection is empty for %s continuation/retry; "
                            "re-rendering loop expression",
                            step.step,
                        )
                    else:
                        logger.warning(
                            "[LOOP] Missing/invalid cached collection for %s continuation/retry; "
                            "re-rendering loop expression",
                            step.step,
                        )

                # Get collection to iterate
                context = state.get_render_context(Event(
                    execution_id=state.execution_id,
                    step=step.step,
                    name="loop_init",
                    payload={}
                ))

                # Render collection expression
                collection_expr = step.loop.in_
                collection = self._render_template(collection_expr, context)
                collection = self._normalize_loop_collection(collection, step.step)

                # Guard: if the collection is empty after re-rendering on a loop continuation
                # or retry, the state reconstruction is incomplete (e.g., a reference-only
                # step result could not be hydrated from NATS after a cache miss).  Skip
                # dispatch entirely so we never call claim_next_loop_index and leak a slot.
                if len(collection) == 0 and (loop_continue_requested or loop_retry_requested):
                    logger.warning(
                        "[LOOP] Empty collection after re-render for %s on continuation/retry; "
                        "skipping dispatch (step result may be unavailable after state rebuild)",
                        step.step,
                    )
                    return None

            # Initialize local loop state if needed and refresh collection snapshot.
            # IMPORTANT: A loop step can be re-entered multiple times in the same execution
            # (e.g., load -> normalize -> process(loop) -> load). When the prior loop
            # invocation is already finalized, reset counters/results and use a fresh
            # distributed loop key so claim slots are not stuck at old scheduled/completed
            # counts (e.g., 100/100 from the previous batch).
            #
            # a new epoch with a time-based suffix to guarantee uniqueness. This prevents
            # epoch ID collisions when state.last_event_id is the same across epoch resets
            # (e.g. during STATE-CACHE-INVALIDATE / rebuild races where try_claim_loop_done
            # has not yet written loop_done_claimed=True to NATS).
            force_new_loop_instance = False
            _is_fresh_dispatch = not loop_continue_requested and not loop_retry_requested
            if existing_loop_state is None:
                loop_event_id = f"loop_{state.last_event_id or time.time_ns()}_{time.time_ns()}"
                state.init_loop(
                    step.step,
                    collection,
                    step.loop.iterator,
                    step.loop.mode,
                    event_id=loop_event_id,
                )

                if state.step_stall_counts.get(step.step, 0) >= _MAX_LOOP_STALL_RESTARTS:
                    state.failed = True
                    logger.error("[DEAD-LOOP] Loop step %s stalled for %s consecutive restarts. Halting execution.", step.step, _MAX_LOOP_STALL_RESTARTS)
                    stalled_event = Event(
                        execution_id=state.execution_id,
                        step=step.step,
                        name="loop.stalled",
                        payload={
                            "message": f"Dead-loop detected: zero successful slots across {_MAX_LOOP_STALL_RESTARTS} consecutive loop runs."
                        }
                    )
                    await self._persist_event(stalled_event, state)
                    return None

                existing_loop_state = state.loop_state[step.step]
            else:
                previous_collection = existing_loop_state.get("collection")
                previous_size = len(previous_collection) if isinstance(previous_collection, list) else 0
                previous_completed = state.get_loop_completed_count(step.step)
                previous_scheduled = int(
                    existing_loop_state.get("scheduled_count", previous_completed) or previous_completed
                )
                previous_finalized = bool(
                    existing_loop_state.get("aggregation_finalized") or existing_loop_state.get("completed")
                )
                previous_exhausted = (
                    previous_size > 0
                    and previous_completed >= previous_size
                    and previous_scheduled >= previous_size
                )

                # EPOCH UNIQUENESS: On fresh dispatch for a newly routed loop, reset the 
                # loop state (which generates a new loop_event_id) only if the previous 
                # run was cleanly finalized or exhausted. This ensures race conditions
                # during STATE-CACHE-INVALIDATE do not accidentally use a stale epoch,
                # but ALSO prevents resetting the loop 5 times concurrently when issuing
                # multiple commands for mode=parallel max_in_flight=5.
                should_reset_existing_loop = _is_fresh_dispatch and (previous_finalized or previous_exhausted)

                if should_reset_existing_loop:
                    loop_event_id = f"loop_{state.last_event_id or time.time_ns()}_{time.time_ns()}"
                    state.init_loop(
                        step.step,
                        collection,
                        step.loop.iterator,
                        step.loop.mode,
                        event_id=loop_event_id,
                    )
                    
                    if state.step_stall_counts.get(step.step, 0) >= _MAX_LOOP_STALL_RESTARTS:
                        state.failed = True
                        logger.error("[DEAD-LOOP] Loop step %s stalled for %s consecutive restarts. Halting execution.", step.step, _MAX_LOOP_STALL_RESTARTS)
                        stalled_event = Event(
                            execution_id=state.execution_id,
                            step=step.step,
                            name="loop.stalled",
                            payload={
                                "message": f"Dead-loop detected: zero successful slots across {_MAX_LOOP_STALL_RESTARTS} consecutive loop runs."
                            }
                        )
                        await self._persist_event(stalled_event, state)
                        return None

                    existing_loop_state = state.loop_state[step.step]
                    force_new_loop_instance = True

                    # This step is active again; clear prior completion snapshot.
                    state.completed_steps.discard(step.step)
                    state.step_results.pop(step.step, None)
                    state.variables.pop(step.step, None)

                    logger.info(
                        "[LOOP] Reset loop invocation for %s (prev_completed=%s prev_scheduled=%s prev_size=%s new_size=%s event_id=%s)",
                        step.step,
                        previous_completed,
                        previous_scheduled,
                        previous_size,
                        len(collection),
                        loop_event_id,
                    )
                else:
                    rendered_collection_size = len(collection)
                    if (
                        (loop_continue_requested or loop_retry_requested)
                        and isinstance(previous_collection, list)
                        and previous_size > 0
                        and rendered_collection_size < previous_size
                    ):
                        logger.warning(
                            "[LOOP] Preserving prior collection snapshot for %s continuation/retry "
                            "(rendered_size=%s previous_size=%s)",
                            step.step,
                            rendered_collection_size,
                            previous_size,
                        )
                        collection = list(previous_collection)
                    existing_loop_state["collection"] = list(collection)
            loop_state = existing_loop_state
            loop_event_id_for_metadata = (
                str(loop_state.get("event_id"))
                if loop_state.get("event_id") is not None
                else None
            )

            # Resolve distributed loop key candidates.
            if force_new_loop_instance:
                loop_event_id_candidates = [str(loop_state.get("event_id"))]
            else:
                loop_event_id_candidates = self._build_loop_event_id_candidates(state, step.step, loop_state)
            resolved_loop_event_id = (
                loop_event_id_candidates[0]
                if loop_event_id_candidates
                else f"exec_{state.execution_id}"
            )
            loop_state["event_id"] = resolved_loop_event_id

            nats_cache = await get_nats_cache()
            nats_loop_state = None
            for candidate_event_id in loop_event_id_candidates:
                candidate_state = await nats_cache.get_loop_state(
                    str(state.execution_id),
                    step.step,
                    event_id=candidate_event_id,
                )
                if candidate_state:
                    nats_loop_state = candidate_state
                    resolved_loop_event_id = candidate_event_id
                    loop_state["event_id"] = candidate_event_id
                    break

            # If we're entering this loop from upstream routing (not loop continuation/retry)
            # and the distributed counters are already fully saturated, treat that state as
            # a completed previous invocation and start a fresh loop epoch.
            if (
                not loop_retry_requested
                and not loop_continue_requested
                and nats_loop_state
            ):
                nats_completed = int(nats_loop_state.get("completed_count", 0) or 0)
                nats_scheduled = int(
                    nats_loop_state.get("scheduled_count", nats_completed) or nats_completed
                )
                nats_size = int(nats_loop_state.get("collection_size", len(collection)) or len(collection))
                nats_loop_done_claimed = bool(nats_loop_state.get("loop_done_claimed", False))
                if (nats_size > 0 and nats_completed >= nats_size and nats_scheduled >= nats_size) or nats_loop_done_claimed:
                    loop_event_id = f"loop_{state.last_event_id or time.time_ns()}"
                    state.init_loop(
                        step.step,
                        collection,
                        step.loop.iterator,
                        step.loop.mode,
                        event_id=loop_event_id,
                    )

                    if state.step_stall_counts.get(step.step, 0) >= _MAX_LOOP_STALL_RESTARTS:
                        state.failed = True
                        logger.error("[DEAD-LOOP] Loop step %s stalled for %s consecutive restarts. Halting execution.", step.step, _MAX_LOOP_STALL_RESTARTS)
                        stalled_event = Event(
                            execution_id=state.execution_id,
                            step=step.step,
                            name="loop.stalled",
                            payload={
                                "message": f"Dead-loop detected: zero successful slots across {_MAX_LOOP_STALL_RESTARTS} consecutive loop runs."
                            }
                        )
                        await self._persist_event(stalled_event, state)
                        return None

                    loop_state = state.loop_state[step.step]
                    force_new_loop_instance = True
                    loop_event_id_candidates = [loop_event_id]
                    resolved_loop_event_id = loop_event_id
                    nats_loop_state = None

                    state.completed_steps.discard(step.step)
                    state.step_results.pop(step.step, None)
                    state.variables.pop(step.step, None)

                    logger.info(
                        "[LOOP] Reset stale distributed state for new invocation of %s "
                        "(completed=%s scheduled=%s size=%s new_event_id=%s)",
                        step.step,
                        nats_completed,
                        nats_scheduled,
                        nats_size,
                        loop_event_id,
                    )

            completed_count_local = state.get_loop_completed_count(step.step)
            completed_count = completed_count_local
            if nats_loop_state:
                completed_count = int(nats_loop_state.get("completed_count", completed_count_local) or completed_count_local)

            max_in_flight = self._get_loop_max_in_flight(step)

            # Repair invalid distributed metadata from older writes/restarts where
            # collection_size regressed to 0 while local loop collection is valid.
            if nats_loop_state and len(collection) > 0:
                nats_collection_size = int(nats_loop_state.get("collection_size", 0) or 0)
                if nats_collection_size <= 0:
                    repaired_scheduled = int(
                        nats_loop_state.get("scheduled_count", completed_count) or completed_count
                    )
                    if repaired_scheduled < completed_count:
                        repaired_scheduled = completed_count
                    nats_loop_state["collection_size"] = len(collection)
                    nats_loop_state["completed_count"] = completed_count
                    nats_loop_state["scheduled_count"] = repaired_scheduled
                    nats_loop_state["failed_count"] = existing_loop_state.get("failed_count", 0) if existing_loop_state else 0
                    nats_loop_state["break_count"] = existing_loop_state.get("break_count", 0) if existing_loop_state else 0
                    await nats_cache.set_loop_state(
                        str(state.execution_id),
                        step.step,
                        nats_loop_state,
                        event_id=resolved_loop_event_id,
                    )
                    nats_loop_state = await nats_cache.get_loop_state(
                        str(state.execution_id),
                        step.step,
                        event_id=resolved_loop_event_id,
                    )
                    logger.warning(
                        "[LOOP-REPAIR] Restored collection_size for %s via %s (completed=%s scheduled=%s size=%s)",
                        step.step,
                        resolved_loop_event_id,
                        completed_count,
                        repaired_scheduled,
                        len(collection),
                    )

            # Ensure distributed loop metadata exists before claiming next slot.
            if not nats_loop_state:
                # New epoch: discard cross-epoch accumulated counts so the fresh
                # NATS entry starts from 0 instead of being poisoned by prior
                # facility runs (fixes stale-count / no-slot bug for reused loops).
                if force_new_loop_instance:
                    completed_count = 0
                    # Also reset scheduled_count: the in-memory loop_state still carries
                    # the previous epoch's scheduled_count (e.g. 100) which would poison
                    # the new NATS entry, causing claim_next_loop_index to return None
                    # immediately (scheduled >= collection_size).
                    scheduled_seed = 0
                else:
                    scheduled_seed = max(
                        int(loop_state.get("scheduled_count", completed_count) or completed_count),
                        completed_count,
                    )
                await nats_cache.set_loop_state(
                    str(state.execution_id),
                    step.step,
                    {
                        "collection_size": len(collection),
                        "completed_count": completed_count,
                        "scheduled_count": scheduled_seed,
                        "iterator": step.loop.iterator,
                        "mode": step.loop.mode,
                        "event_id": resolved_loop_event_id,
                    },
                    event_id=resolved_loop_event_id,
                )
                nats_loop_state = await nats_cache.get_loop_state(
                    str(state.execution_id),
                    step.step,
                    event_id=resolved_loop_event_id,
                )

            if loop_retry_requested and loop_retry_index is not None:
                claimed_index = loop_retry_index
                logger.info(
                    "[LOOP] Reusing loop iteration %s for retry on step %s",
                    claimed_index,
                    step.step,
                )
            else:
                if nats_loop_state:
                    claimed_index = await nats_cache.claim_next_loop_index(
                        str(state.execution_id),
                        step.step,
                        collection_size=len(collection),
                        max_in_flight=max_in_flight,
                        event_id=resolved_loop_event_id,
                    )
                    if claimed_index is not None:
                        _nats_slot_incremented = True
                else:
                    # Local fallback when distributed cache is unavailable.
                    completed_count = completed_count_local
                    scheduled_count = max(
                        int(loop_state.get("scheduled_count", completed_count) or completed_count),
                        completed_count,
                    )
                    if scheduled_count < len(collection) and (scheduled_count - completed_count) < max_in_flight:
                        claimed_index = scheduled_count
                        loop_state["scheduled_count"] = scheduled_count + 1

            if claimed_index is None:
                scheduled_hint = int(
                    (nats_loop_state or {}).get(
                        "scheduled_count",
                        loop_state.get("scheduled_count", completed_count),
                    )
                    or completed_count
                )
                collection_size_hint = int(
                    (nats_loop_state or {}).get("collection_size", len(collection)) or len(collection)
                )
                in_flight = max(0, scheduled_hint - completed_count)

                # Fast counter reconciliation:
                # If distributed counters report no claimable slot but persisted state shows
                # no in-flight command rows, advance completed_count from durable events and
                # retry claim immediately. This avoids silent loop stalls waiting for another
                # unrelated event to trigger watchdog recovery.
                if (
                    claimed_index is None
                    and nats_loop_state
                    and collection_size_hint > completed_count
                    and (
                        scheduled_hint >= collection_size_hint
                        or in_flight >= max_in_flight
                    )
                ):
                    now_utc = datetime.now(timezone.utc)
                    last_counter_reconcile = _parse_iso_utc(
                        nats_loop_state.get("last_counter_reconcile_at")
                    ) or _parse_iso_utc(loop_state.get("last_counter_reconcile_at"))
                    reconcile_cooldown_elapsed = (
                        last_counter_reconcile is None
                        or (now_utc - last_counter_reconcile).total_seconds()
                        >= _LOOP_COUNTER_RECONCILE_COOLDOWN_SECONDS
                    )
                    if reconcile_cooldown_elapsed:
                        missing_indexes = await self._find_missing_loop_iteration_indices(
                            str(state.execution_id),
                            step.step,
                            loop_event_id=resolved_loop_event_id,
                            limit=1,
                        )
                        if not missing_indexes:
                            # Only use the all-batch persisted count to repair NATS when all
                            # iteration slots appear to have been scheduled (scheduled_hint >=
                            # collection_size_hint).  When the trigger is in_flight saturation
                            # alone (scheduled_hint < collection_size_hint), there are still
                            # unscheduled slots; _count_step_events would return the sum across
                            # ALL prior batches, inflating completed_count and falsely marking
                            # the current epoch as finished.  In that case, skip the repair and
                            # let natural backpressure release (workers completing will lower
                            # in_flight and unblock future claim attempts).
                            if scheduled_hint < collection_size_hint:
                                logger.debug(
                                    "[LOOP-COUNTER-RECONCILE] Skipping persisted-count repair for %s "
                                    "(scheduled=%s < size=%s — in_flight saturation, not a stall)",
                                    step.step,
                                    scheduled_hint,
                                    collection_size_hint,
                                )
                            else:
                                persisted_completed = await self._count_step_events(
                                    state.execution_id,
                                    step.step,
                                    "call.done",
                                )
                                if persisted_completed >= 0:
                                    persisted_completed = min(
                                        persisted_completed,
                                        collection_size_hint,
                                    )
                                    if persisted_completed > completed_count:
                                        repaired_completed = persisted_completed
                                        repaired_scheduled = max(
                                            int(
                                                (nats_loop_state or {}).get(
                                                    "scheduled_count",
                                                    scheduled_hint,
                                                )
                                                or scheduled_hint
                                            ),
                                            repaired_completed,
                                        )
                                        repaired_at = now_utc.isoformat()
                                        nats_loop_state["completed_count"] = repaired_completed
                                        nats_loop_state["scheduled_count"] = repaired_scheduled
                                        nats_loop_state["last_counter_reconcile_at"] = repaired_at
                                        nats_loop_state["last_progress_at"] = repaired_at
                                        nats_loop_state["updated_at"] = repaired_at
                                        loop_state["scheduled_count"] = repaired_scheduled
                                        loop_state["last_counter_reconcile_at"] = repaired_at
                                        await nats_cache.set_loop_state(
                                            str(state.execution_id),
                                            step.step,
                                            nats_loop_state,
                                            event_id=resolved_loop_event_id,
                                        )
                                        completed_count = repaired_completed
                                        scheduled_hint = repaired_scheduled
                                        in_flight = max(0, scheduled_hint - completed_count)
                                        claimed_index = await nats_cache.claim_next_loop_index(
                                            str(state.execution_id),
                                            step.step,
                                            collection_size=len(collection),
                                            max_in_flight=max_in_flight,
                                            event_id=resolved_loop_event_id,
                                        )
                                        if claimed_index is not None:
                                            _nats_slot_incremented = True
                                            logger.warning(
                                                "[LOOP-COUNTER-RECONCILE] Recovered claim slot for %s "
                                                "(event_id=%s completed=%s scheduled=%s size=%s claimed=%s)",
                                                step.step,
                                                resolved_loop_event_id,
                                                completed_count,
                                                scheduled_hint,
                                                collection_size_hint,
                                                claimed_index,
                                            )

                # Runtime loop-stall watchdog:
                # If there is pending work but no claimable slot is available, stale
                # distributed loop metadata can leave the loop parked indefinitely.
                # That shows up in two shapes:
                # 1. all slots appear scheduled (`scheduled_count >= collection_size`)
                # 2. ghost in-flight work saturates `max_in_flight` before all items are scheduled
                # In both cases, look for orphaned iteration indexes and replay one when
                # progress has been stale long enough.
                if (
                    claimed_index is None
                    and nats_loop_state
                    and collection_size_hint > completed_count
                    and (
                        scheduled_hint >= collection_size_hint
                        or in_flight >= max_in_flight
                    )
                ):
                    now_utc = datetime.now(timezone.utc)
                    last_progress = (
                        _parse_iso_utc(nats_loop_state.get("last_progress_at"))
                        or _parse_iso_utc(nats_loop_state.get("last_completed_at"))
                        or _parse_iso_utc(nats_loop_state.get("last_claimed_at"))
                        or _parse_iso_utc(nats_loop_state.get("updated_at"))
                    )
                    last_repair = _parse_iso_utc(nats_loop_state.get("last_watchdog_repair_at"))
                    if last_repair is None:
                        last_repair = _parse_iso_utc(loop_state.get("last_watchdog_repair_at"))

                    stalled_seconds = (
                        (now_utc - last_progress).total_seconds()
                        if last_progress is not None
                        else (_LOOP_STALL_WATCHDOG_SECONDS + 1.0)
                    )
                    repair_cooldown_elapsed = (
                        last_repair is None
                        or (now_utc - last_repair).total_seconds()
                        >= _LOOP_STALL_RECOVERY_COOLDOWN_SECONDS
                    )
                    if (
                        stalled_seconds >= _LOOP_STALL_WATCHDOG_SECONDS
                        and repair_cooldown_elapsed
                    ):
                        orphaned_indexes = await self._find_orphaned_loop_iteration_indices(
                            str(state.execution_id),
                            step.step,
                            loop_event_id=resolved_loop_event_id,
                            limit=max(1, _TASKSEQ_LOOP_REPAIR_THRESHOLD),
                        )
                        issued_repairs_raw = loop_state.get("repair_issued_indexes", [])
                        issued_repairs = {
                            int(idx)
                            for idx in issued_repairs_raw
                            if isinstance(idx, int) or (isinstance(idx, str) and str(idx).isdigit())
                        }
                        recovered_index: Optional[int] = None
                        for orphaned_idx in orphaned_indexes:
                            if (
                                orphaned_idx in issued_repairs
                                or orphaned_idx < completed_count
                                or orphaned_idx >= collection_size_hint
                            ):
                                continue
                            recovered_index = orphaned_idx
                            break
                        if recovered_index is not None:
                            claimed_index = recovered_index
                            issued_repairs.add(recovered_index)
                            loop_state["repair_issued_indexes"] = sorted(issued_repairs)
                            loop_state["last_watchdog_repair_at"] = now_utc.isoformat()
                            loop_state["watchdog_repair_count"] = int(
                                loop_state.get("watchdog_repair_count", 0) or 0
                            ) + 1
                            logger.warning(
                                "[LOOP-WATCHDOG] Recovered stalled loop for %s via orphaned index replay "
                                "(event_id=%s completed=%s scheduled=%s size=%s claimed=%s stalled_for=%.1fs)",
                                step.step,
                                resolved_loop_event_id,
                                completed_count,
                                scheduled_hint,
                                collection_size_hint,
                                claimed_index,
                                stalled_seconds,
                            )

                if claimed_index is None:
                    logger.debug(
                        "[LOOP] No available iteration slot for %s (completed=%s scheduled=%s size=%s in_flight=%s max_in_flight=%s)",
                        step.step,
                        completed_count,
                        scheduled_hint,
                        len(collection),
                        in_flight,
                        max_in_flight,
                    )
                    return None

            if claimed_index >= len(collection):
                logger.warning(
                    "[LOOP] Claimed index %s is out of range for %s (col_size=%s); %s",
                    claimed_index,
                    step.step,
                    len(collection),
                    "releasing NATS slot to prevent in-flight saturation"
                    if _nats_slot_incremented
                    else "slot was not NATS-claimed (retry/watchdog path)",
                )
                if _nats_slot_incremented:
                    released = await nats_cache.release_loop_slot(
                        str(state.execution_id),
                        step.step,
                        event_id=resolved_loop_event_id,
                    )
                    if not released:
                        logger.warning(
                            "[LOOP] Failed to release NATS slot for %s index=%s event_id=%s",
                            step.step,
                            claimed_index,
                            resolved_loop_event_id,
                        )
                return None

            item = collection[claimed_index]
            loop_state["index"] = max(int(loop_state.get("index", 0) or 0), claimed_index + 1)
            loop_event_id_for_metadata = (
                str(loop_state.get("event_id"))
                if loop_state.get("event_id") is not None
                else loop_event_id_for_metadata
            )
            logger.info(
                "[LOOP] Claimed loop iteration %s for step %s (mode=%s max_in_flight=%s)",
                claimed_index,
                step.step,
                step.loop.mode,
                max_in_flight,
            )
            
            # Add loop variables to state for Jinja2 template rendering
            state.variables[step.loop.iterator] = item
            state.variables["loop_index"] = claimed_index
            logger.debug(
                "[LOOP] Updated loop state variables: iterator=%s loop_index=%s",
                step.loop.iterator,
                claimed_index,
            )
        
        # Get render context for Jinja2 templates.
        # Reuse the context from loop collection rendering if available, patching in
        # the newly-set loop variables to avoid a full context rebuild.
        if step.loop and 'context' in dir() and context is not None:
            # Patch loop variables into existing context instead of full rebuild
            iterator_value = state.variables.get(step.loop.iterator)
            context[step.loop.iterator] = iterator_value
            context["loop_index"] = claimed_index
            context["ctx"] = state.variables
            context["workload"] = state.variables
            # Update iter namespace so {{ iter.<iterator>.<field> }} works
            if "iter" not in context or not isinstance(context.get("iter"), dict):
                context["iter"] = {}
            context["iter"][step.loop.iterator] = iterator_value
            context["iter"]["_index"] = claimed_index
            coll_len = len(collection) if 'collection' in dir() and collection else 0
            context["iter"]["_first"] = claimed_index == 0
            context["iter"]["_last"] = claimed_index >= coll_len - 1 if coll_len > 0 else True
            # Update loop metadata
            loop_s = state.loop_state.get(step.step)
            if loop_s:
                context["loop"] = {
                    "index": loop_s["index"] - 1 if loop_s["index"] > 0 else 0,
                    "first": loop_s["index"] == 1,
                    "length": len(loop_s.get("collection", [])),
                    "done": loop_s.get("completed", False),
                }
        else:
            context = state.get_render_context(Event(
                execution_id=state.execution_id,
                step=step.step,
                name="command_creation",
                payload={}
            ))

        # Import render utility
        from noetl.core.dsl.render import render_template as recursive_render

        # Debug: Log state for verify_result step
        if step.step == "verify_result":
            gcs_result = state.step_results.get('run_python_from_gcs', 'NOT_FOUND')
            logger.debug(
                "verify_result debug: step_results_keys=%s variable_keys=%s run_python_from_gcs_type=%s",
                list(state.step_results.keys()),
                list(state.variables.keys()),
                type(gcs_result).__name__,
            )

        # Debug: Log loop variables in context
        if step.loop:
            logger.debug(
                "[LOOP-DEBUG] Step %s context_keys=%s has_iterator=%s loop_index=%s",
                step.step,
                list(context.keys()),
                step.loop.iterator in context,
                context.get("loop_index", "NOT_FOUND"),
            )

        # Build input bindings separately for step execution.
        step_args = {}
        if step.input:
            step_args.update(step.input)

        # Merge transition-scoped input published by prior routing/actions.
        filtered_args = {
            k: v for k, v in control_args.items()
            if k not in {"__loop_retry", "__loop_retry_index", "__loop_continue"}
        }
        step_args.update(filtered_args)

        # Render Jinja2 templates in merged input.
        rendered_input = recursive_render(self.jinja_env, step_args, context)

        if step.tool is None:
            logger.info(
                "[CREATE-CMD] Step '%s' has no tool; treating as a terminal/non-actionable transition target",
                step.step,
            )
            return None

        # Check if step.tool is a pipeline (list of labeled tasks) or single tool
        pipeline = None
        if isinstance(step.tool, list):
            # Pipeline: list of labeled tasks
            # Each item is {name: ..., kind: ..., input/spec/output...}
            # IMPORTANT: Do NOT pre-render pipeline templates here!
            # Task sequences may have templates that depend on variables set by earlier tasks
            # (e.g., via `set` in policy rules). The worker's task_sequence_executor
            # will render templates at execution time with the proper context.
            pipeline = step.tool  # Pass raw list, worker renders at execution time
            logger.info(f"[PIPELINE] Step '{step.step}' has pipeline with {len(pipeline)} tasks (deferred rendering)")

            # For pipeline steps, use task_sequence as tool kind
            tool_kind = "task_sequence"
            tool_config = {"tasks": pipeline}  # Worker expects "tasks" key
        else:
            # Single tool (shorthand)
            tool_dict = step.tool.model_dump()
            tool_config = {k: v for k, v in tool_dict.items() if k != "kind"}
            tool_kind = step.tool.kind

            # Check if single tool has spec.policy.rules - if so, convert to task sequence
            # This enables retry/control flow for single-tool steps
            spec = tool_config.get("spec", {})
            policy = spec.get("policy", {}) if isinstance(spec, dict) else {}
            policy_rules = policy.get("rules", []) if isinstance(policy, dict) else []

            if policy_rules:
                # Convert single tool to task sequence format so policy rules work
                # Use canonical format: { name: "task_label", kind: "...", ... }
                task_label = f"{step.step}_task"
                pipeline = [{"name": task_label, **tool_dict}]
                tool_kind = "task_sequence"
                tool_config = {"tasks": pipeline}
                logger.info(f"[PIPELINE] Converted single tool with policy rules to task sequence for step '{step.step}'")
            else:
                # NOTE: step.result removed in v10 - output config is now in tool.output or tool.spec.policy

                # Render Jinja2 templates in tool config
                tool_config = recursive_render(self.jinja_env, tool_config, context)

        # Extract next targets for conditional routing (canonical v10 format)
        next_targets = None
        if step.next:
            # Normalize next to list of dicts (arcs)
            next_items = step.next
            if isinstance(next_items, str):
                # String shorthand: next: "step_name"
                next_items = [{"step": next_items}]
            elif isinstance(next_items, dict):
                # V10 router format: { spec: { mode: ... }, arcs: [...] }
                if "arcs" in next_items:
                    next_items = next_items.get("arcs", [])
                elif "step" in next_items:
                    # Legacy single target: { step: "name", when: "..." }
                    next_items = [next_items]
                else:
                    next_items = []
            elif isinstance(next_items, list):
                # Legacy list format: [{ step: ... }, ...]
                next_items = [
                    item if isinstance(item, dict) else {"step": item}
                    for item in next_items
                ]
            next_targets = next_items
            logger.debug(f"[NEXT] Step '{step.step}' has {len(next_targets)} next targets")

        # Extract next_mode from next.spec.mode (canonical v10)
        command_spec = None
        next_mode = "exclusive"
        if step.next and isinstance(step.next, dict):
            next_spec = step.next.get("spec", {})
            if isinstance(next_spec, dict) and "mode" in next_spec:
                next_mode = next_spec.get("mode", "exclusive")
        command_spec = CommandSpec(next_mode=next_mode)
        logger.debug(f"[SPEC] Step '{step.step}': next_mode={next_mode} (from next.spec.mode)")

        # For pipeline (task sequence) steps, use :task_sequence suffix in step name
        # This enables the engine to detect task sequence completion and sync ctx variables
        command_step = f"{step.step}:task_sequence" if pipeline else step.step

        command_metadata: dict[str, Any] = {}
        if pipeline:
            command_metadata.update(
                {
                    "task_sequence": True,
                    "parent_step": step.step,
                }
            )
        if step.loop:
            command_metadata.update(
                {
                    "loop_step": step.step,
                    "loop_event_id": loop_event_id_for_metadata,
                    "__loop_epoch_id": loop_event_id_for_metadata,
                    "loop_iteration_index": claimed_index,
                }
            )
            command_metadata = {
                key: value for key, value in command_metadata.items() if value is not None
            }

        command = Command(
            execution_id=state.execution_id,
            step=command_step,
            tool=ToolCall(
                kind=tool_kind,
                config=tool_config
            ),
            input=rendered_input,
            render_context=context,
            pipeline=pipeline,
            next_targets=next_targets,
            spec=command_spec,
            attempt=1,
            priority=0,
            metadata=command_metadata,
        )

        return command

    # NOTE: _process_vars_block REMOVED in strict v10 - use scoped `set` mutations.

    async def handle_event(self, event: Event, already_persisted: bool = False) -> list[Command]:
        """
        Handle an event and return commands to enqueue.
        
        This is the core engine method called by the API.
        
        Args:
            event: The event to process
            already_persisted: If True, skip persisting the event (it was already persisted by caller)
        """
        logger.debug(
            "[ENGINE] handle_event called: event.name=%s, step=%s, execution=%s, already_persisted=%s",
            event.name,
            event.step,
            event.execution_id,
            already_persisted,
        )
        commands: list[Command] = []
        normalized_payload = _unwrap_event_payload(event.payload)
        preserved_loop_snapshots: dict[str, dict[str, Any]] = {}
        cache_refreshed = False
        
        # Load execution state. For already-persisted events we must guard against
        # stale per-pod memory snapshots when another server advanced this execution.
        if already_persisted:
            cached_state = self.state_store.get_state(event.execution_id)
            if (
                cached_state
                and cached_state.last_event_id is not None
                and await self.state_store.should_refresh_cached_state(
                    event.execution_id,
                    cached_state.last_event_id,
                    allowed_missing_events=_STATE_CACHE_ALLOWED_MISSING_EVENTS,
                )
            ):
                preserved_loop_snapshots = self._snapshot_loop_collections(cached_state)
                await self.state_store.invalidate_state(
                    event.execution_id,
                    reason="stale_cache_newer_persisted_events",
                )
                cache_refreshed = True

        state = await self.state_store.load_state(event.execution_id)
        if not state:
            logger.error(f"Execution state not found: {event.execution_id}")
            return commands

        if cache_refreshed and preserved_loop_snapshots:
            self._restore_loop_collection_snapshots(state, preserved_loop_snapshots)

        if state.completed:
            logger.info(
                "[ENGINE] Execution %s already completed; skipping orchestration for event %s/%s",
                event.execution_id,
                event.name,
                event.step,
            )
            if not already_persisted:
                await self._persist_event(event, state)
                await self.state_store.save_state(state)
            return commands
        
        # Get current step
        if not event.step:
            logger.error("Event missing step name")
            return commands

        # Actionable worker completions may be retried by transport/reaper paths.
        # Since these events are already persisted before handle_event() runs,
        # duplicates can trigger the same routing side-effects multiple times.
        # Guard by command_id and only orchestrate the first persisted instance.
        if already_persisted and event.name in {"call.done", "call.error"}:
            command_id = _extract_command_id_from_event_payload(normalized_payload)
            if command_id:
                persisted_count = await self._count_persisted_command_events(
                    event.execution_id,
                    event.name,
                    command_id,
                )
                if persisted_count > 1:
                    logger.warning(
                        "[EVENT-DEDUPE] Ignoring duplicate persisted %s for execution=%s "
                        "step=%s command_id=%s count=%s",
                        event.name,
                        event.execution_id,
                        event.step,
                        command_id,
                        persisted_count,
                    )
                    return commands
        
        # Handle inline tasks (dynamically created from pipeline task execution)
        # These have format "parent_step:task_name" (e.g., "success:send_callback")
        # and don't exist as workflow steps. They execute and emit events, but don't need orchestration
        # EXCEPTION: Task sequence steps (e.g., "step:task_sequence") are NOT inline tasks - they need special handling
        is_task_sequence_step = event.step.endswith(":task_sequence")
        is_inline_task = ':' in event.step and state.get_step(event.step) is None and not is_task_sequence_step
        if is_inline_task:
            logger.debug(f"Inline task: {event.step} - persisting event without orchestration")
            # Persist the event but don't generate commands (no orchestration needed)
            # Skip if already persisted by API caller
            if not already_persisted:
                await self._persist_event(event, state)
            # CRITICAL: Mark synthetic step as completed when step.exit received
            # This ensures issued_steps - completed_steps doesn't block workflow completion
            if event.name == "step.exit":
                state.completed_steps.add(event.step)
                logger.debug(f"Marked inline task {event.step} as completed")

                # Process any deferred next actions that were waiting for this inline task
                deferred_commands = await self._process_deferred_next_actions(state, event.step, event)
                if deferred_commands:
                    commands.extend(deferred_commands)
                    # CRITICAL: Add deferred command steps to issued_steps for pending tracking
                    # This is needed because we return early and bypass the normal issued_steps update
                    for cmd in deferred_commands:
                        pending_key = _pending_step_key(cmd.step)
                        if not pending_key:
                            continue
                        state.issued_steps.add(pending_key)
                        logger.info(
                            f"[ISSUED] Added deferred {pending_key} to issued_steps for execution {state.execution_id}"
                        )
                    logger.info(f"[INLINE-TASK] Processed deferred next actions, generated {len(deferred_commands)} command(s)")
                    # Save state after processing deferred actions
                    await self.state_store.save_state(state)
                    return commands

                # Check if all issued steps are now completed (workflow might be done)
                pending_steps = state.issued_steps - state.completed_steps
                if not pending_steps and not state.completed:
                    # All steps completed - emit workflow/playbook completion events
                    state.completed = True
                    from noetl.core.dsl.v2.models import LifecycleEventPayload

                    workflow_completion_event = Event(
                        execution_id=event.execution_id,
                        step="workflow",
                        name="workflow.completed",
                        payload=LifecycleEventPayload(
                            status="completed",
                            final_step=event.step,
                            result=event.payload.get("result"),
                            error=None
                        ).model_dump(),
                        timestamp=datetime.now(timezone.utc),
                        parent_event_id=state.last_event_id
                    )
                    await self._persist_event(workflow_completion_event, state)
                    logger.info(f"Workflow completed (after inline task): execution_id={event.execution_id}")

                    playbook_completion_event = Event(
                        execution_id=event.execution_id,
                        step=state.playbook.metadata.get("path", "playbook"),
                        name="playbook.completed",
                        payload=LifecycleEventPayload(
                            status="completed",
                            final_step=event.step,
                            result=event.payload.get("result"),
                            error=None
                        ).model_dump(),
                        timestamp=datetime.now(timezone.utc),
                        parent_event_id=state.last_event_id
                    )
                    await self._persist_event(playbook_completion_event, state)
                    logger.info(f"Playbook completed (after inline task): execution_id={event.execution_id}")

                    await self.state_store.save_state(state)
            return commands

        # Handle task sequence completion events
        # Task sequence steps have suffix :task_sequence (e.g., fetch_page:task_sequence)
        if event.step.endswith(":task_sequence") and event.name == "call.done":
            parent_step = event.step.rsplit(":", 1)[0]
            response_data = (
                normalized_payload.get("response", normalized_payload)
                if isinstance(normalized_payload, dict)
                else normalized_payload
            )
            payload_loop_event_id = (
                normalized_payload.get("loop_event_id")
                if isinstance(normalized_payload, dict)
                else None
            )
            if not payload_loop_event_id and isinstance(response_data, dict):
                payload_loop_event_id = response_data.get("loop_event_id")

            # Extract ctx variables from task sequence result and merge into execution state.
            # This syncs scoped set mutations from task policy rules back to the server.
            task_ctx = response_data.get("ctx", {})
            if task_ctx and isinstance(task_ctx, dict):
                for key, value in task_ctx.items():
                    state.variables[key] = value
                    logger.debug(f"[TASK_SEQ] Synced ctx variable '{key}' from task sequence to execution state")

            # Get parent step definition for loop handling
            parent_step_def = state.get_step(parent_step)

            # Promote the last tool's result to the top level of the stored step result.
            # This ensures {{ step_name.field }} works for both single-tool AND multi-tool sequences.
            # Without promotion, multi-tool results are nested: result["results"]["collect"]["has_more"]
            # and routing conditions like {{ fetch_with_limit.has_more }} would resolve to None.
            _results_dict = response_data.get("results", {})
            if _results_dict:
                _last_result = list(_results_dict.values())[-1]
                _promoted_data = {**_last_result, **response_data} if isinstance(_last_result, dict) else response_data
            else:
                _promoted_data = response_data

            # For non-loop steps: mark parent step completed BEFORE set processing.
            # set templates like {{ fetch_with_limit.collected_data }} need the step result
            # to already be in state.step_results when get_render_context() is called.
            _is_loop_step = parent_step_def and parent_step_def.loop and parent_step in state.loop_state

            # Guard: if the parent is a loop step but loop_state is missing, this pod
            # never initialised the loop (another pod started it while this pod had older
            # cached state).  Seed a minimal loop_state entry so the call.done is processed
            # as a loop iteration — otherwise the engine falls into the "not in loop" branch,
            # skips the NATS completion increment, and the loop stalls permanently.
            if parent_step_def and parent_step_def.loop and not _is_loop_step:
                logger.warning(
                    "[TASK_SEQ] loop_state missing for loop step '%s' (execution=%s) — "
                    "initialising from step definition to handle late call.done",
                    parent_step,
                    state.execution_id,
                )
                loop_iterator = (
                    parent_step_def.loop.iterator
                    if parent_step_def.loop.iterator
                    else "item"
                )
                loop_mode = (
                    parent_step_def.loop.mode
                    if parent_step_def.loop.mode
                    else "sequential"
                )
                state.loop_state[parent_step] = {
                    "collection": [],
                    "iterator": loop_iterator,
                    "index": 0,
                    "mode": loop_mode,
                    "completed": False,
                    "results": [],
                    "failed_count": 0,
                    "scheduled_count": 0,
                    "aggregation_finalized": False,
                    "event_id": payload_loop_event_id,
                    "omitted_results_count": 0,
                }
                _is_loop_step = True

            if not _is_loop_step:
                state.mark_step_completed(parent_step, _promoted_data)
                logger.debug("[TASK_SEQ] Pre-marked parent step '%s' completed with promoted result (before set)", parent_step)

            # Process step-level set for task sequence steps
            # This must happen BEFORE next transitions are evaluated so updated variables are available
            _parent_set = getattr(parent_step_def, "set", None) if parent_step_def else None
            if parent_step_def and _parent_set:
                # Get render context with the task sequence result available
                context = state.get_render_context(event)
                logger.debug(
                    "[SET] Processing step-level set for task sequence %s: keys=%s",
                    parent_step,
                    list(_parent_set.keys()),
                )
                _ts_set_rendered: dict = {}
                for key, value_template in _parent_set.items():
                    try:
                        if isinstance(value_template, str) and "{{" in value_template:
                            _ts_set_rendered[key] = self._render_template(value_template, context)
                        else:
                            _ts_set_rendered[key] = value_template
                        logger.debug("[SET] Rendered %s (type=%s)", key, type(_ts_set_rendered[key]).__name__)
                    except Exception as e:
                        logger.error(f"[SET] Failed to render {key}: {e}")
                _apply_set_mutations(state.variables, _ts_set_rendered)

            # Handle loop iteration tracking for task sequence steps
            if parent_step_def and parent_step_def.loop and parent_step in state.loop_state:
                loop_state = state.loop_state[parent_step]
                if not loop_state.get("aggregation_finalized", False):
                    # Add iteration result to loop aggregation
                    failed = response_data.get("status", "").upper() == "FAILED"
                    iteration_result = response_data.get("results", response_data)
                    state.add_loop_result(parent_step, iteration_result, failed=failed)
                    logger.info(f"[TASK_SEQ] Added iteration result to loop aggregation for {parent_step}")

                    # Sync completed count to NATS K/V
                    try:
                        nats_cache = await get_nats_cache()
                        # Prefer the epoch ID baked into the command at dispatch time.
                        # The worker propagates __loop_epoch_id (or loop_event_id) back in
                        # the call.done payload, so we can pin the epoch without going
                        # through _build_loop_event_id_candidates which may return stale
                        # candidates (e.g. step_event_ids from a previous epoch after a
                        # STATE-CACHE-INVALIDATE).
                        _pinned_epoch_id = (
                            str(normalized_payload.get("__loop_epoch_id"))
                            if isinstance(normalized_payload, dict) and normalized_payload.get("__loop_epoch_id")
                            else (str(payload_loop_event_id) if payload_loop_event_id else None)
                        )
                        event_id_candidates = []
                        if _pinned_epoch_id:
                            # Epoch is pinned from the command: skip stale candidate resolution.
                            event_id_candidates.append(_pinned_epoch_id)
                            # Add exec fallback only (not step_event_ids which may be stale).
                            exec_fallback = f"exec_{state.execution_id}"
                            if exec_fallback not in event_id_candidates:
                                event_id_candidates.append(exec_fallback)
                        else:
                            if payload_loop_event_id:
                                event_id_candidates.append(str(payload_loop_event_id))
                            for candidate in self._build_loop_event_id_candidates(
                                state, parent_step, loop_state
                            ):
                                if candidate not in event_id_candidates:
                                    event_id_candidates.append(candidate)
                        resolved_loop_event_id = (
                            event_id_candidates[0]
                            if event_id_candidates
                            else f"exec_{state.execution_id}"
                        )

                        new_count = -1
                        _stale_epoch_event = False
                        if payload_loop_event_id:
                            # Worker stamped the event with an explicit epoch ID.
                            # Only try that specific key — if it is gone (TTL expired or
                            # wrong epoch) the event belongs to an old, already-completed
                            # batch and must NOT be credited to the current epoch.
                            primary_count = await nats_cache.increment_loop_completed(
                                str(state.execution_id),
                                parent_step,
                                event_id=str(payload_loop_event_id),
                            )
                            if primary_count >= 0:
                                new_count = primary_count
                                resolved_loop_event_id = str(payload_loop_event_id)
                            else:
                                # Key missing: epoch key expired or belongs to a different
                                # execution epoch.  Mark as stale so we do NOT fall through
                                # and inflate the current epoch's counter.
                                _stale_epoch_event = True
                        else:
                            for candidate_event_id in event_id_candidates:
                                candidate_count = await nats_cache.increment_loop_completed(
                                    str(state.execution_id),
                                    parent_step,
                                    event_id=candidate_event_id,
                                )
                                if candidate_count >= 0:
                                    new_count = candidate_count
                                    resolved_loop_event_id = candidate_event_id
                                    break

                        _nats_count_reliable = True
                        if _stale_epoch_event:
                            _nats_count_reliable = False
                            logger.warning(
                                "[TASK_SEQ-LOOP] Stale call.done for %s (payload_epoch=%s current_epoch=%s) — "
                                "epoch key not found in NATS (TTL expired?); discarding to protect current epoch",
                                parent_step,
                                payload_loop_event_id,
                                loop_state.get("event_id"),
                            )
                        elif new_count < 0:
                            _nats_count_reliable = False
                            # Keep progress moving even if distributed cache increments fail.
                            # Prefer durable count from persisted call.done events over local in-memory counts.
                            new_count = state.get_loop_completed_count(parent_step)
                            persisted_count = await self._count_step_events(
                                state.execution_id,
                                event.step,
                                "call.done",
                            )
                            if persisted_count >= 0:
                                new_count = max(new_count, persisted_count)
                            logger.warning(
                                f"[TASK_SEQ-LOOP] Could not increment NATS loop count for {parent_step}; "
                                f"falling back to persisted/local count {new_count}"
                            )
                        else:
                            logger.debug(
                                f"[TASK_SEQ-LOOP] Incremented loop count in NATS K/V for "
                                f"{parent_step} via {resolved_loop_event_id}: {new_count}"
                            )

                        loop_state["event_id"] = resolved_loop_event_id

                        # Resolve collection size with distributed-safe fallback order:
                        # local cache -> NATS K/V metadata -> re-render loop expression.
                        collection = loop_state.get("collection")
                        collection_size = len(collection) if isinstance(collection, list) else 0

                        nats_loop_state = None
                        if collection_size == 0:
                            # When the epoch is pinned (command stamped __loop_epoch_id /
                            # loop_event_id), do NOT fall through to stale candidates that
                            # could override resolved_loop_event_id with an old epoch key
                            # still present in NATS (causing try_claim_loop_done to find an
                            # already-claimed epoch and silently skip loop.done dispatch).
                            if _pinned_epoch_id:
                                lookup_event_ids = [resolved_loop_event_id]
                            else:
                                lookup_event_ids = [resolved_loop_event_id] + [
                                    candidate
                                    for candidate in event_id_candidates
                                    if candidate != resolved_loop_event_id
                                ]
                            for candidate_event_id in lookup_event_ids:
                                candidate_state = await nats_cache.get_loop_state(
                                    str(state.execution_id),
                                    parent_step,
                                    event_id=candidate_event_id,
                                )
                                if candidate_state:
                                    nats_loop_state = candidate_state
                                    resolved_loop_event_id = candidate_event_id
                                    loop_state["event_id"] = candidate_event_id
                                    collection_size = int(candidate_state.get("collection_size", 0) or 0)
                                    break

                        if collection_size == 0:
                            context = state.get_render_context(event)
                            rendered_collection = self._render_template(parent_step_def.loop.in_, context)
                            rendered_collection = self._normalize_loop_collection(rendered_collection, parent_step)
                            loop_state["collection"] = list(rendered_collection)
                            collection_size = len(rendered_collection)
                            logger.info(f"[TASK_SEQ-LOOP] Re-rendered collection for {parent_step}: {collection_size} items")

                            # Backfill NATS metadata if it was missing.
                            if collection_size > 0 and not nats_loop_state:
                                await nats_cache.set_loop_state(
                                    str(state.execution_id),
                                    parent_step,
                                    {
                                        "collection_size": collection_size,
                                        "completed_count": max(new_count, 0),
                                        "scheduled_count": max(new_count, 0),
                                        "iterator": loop_state.get("iterator"),
                                        "mode": loop_state.get("mode"),
                                        "event_id": resolved_loop_event_id
                                    },
                                    event_id=resolved_loop_event_id
                                )

                        # If we had to use fallback counting, ensure distributed counter catches up.
                        if collection_size > 0 and new_count >= 0:
                            if not nats_loop_state:
                                nats_loop_state = await nats_cache.get_loop_state(
                                    str(state.execution_id),
                                    parent_step,
                                    event_id=resolved_loop_event_id,
                                )
                            if nats_loop_state:
                                current_completed = int(
                                    nats_loop_state.get("completed_count", 0) or 0
                                )
                                if new_count > current_completed:
                                    nats_loop_state["completed_count"] = new_count
                                    scheduled_count = int(
                                        nats_loop_state.get("scheduled_count", new_count) or new_count
                                    )
                                    if scheduled_count < new_count:
                                        scheduled_count = new_count
                                    nats_loop_state["scheduled_count"] = scheduled_count
                                    await nats_cache.set_loop_state(
                                        str(state.execution_id),
                                        parent_step,
                                        nats_loop_state,
                                        event_id=resolved_loop_event_id,
                                    )

                        # Check if loop is done
                        scheduled_count = max(
                            int((nats_loop_state or {}).get("scheduled_count", new_count) or new_count),
                            new_count,
                        )
                        remaining_count = max(0, collection_size - new_count)

                        # Tail-repair fallback:
                        # If all loop slots were scheduled but a small number of iterations never reached
                        # a terminal command event (started-only or dropped), reissue those exact indexes.
                        # This keeps loop.done from hanging indefinitely on missing tail items.
                        if (
                            _TASKSEQ_LOOP_REPAIR_THRESHOLD > 0
                            and collection_size > 0
                            and remaining_count > 0
                            and remaining_count <= _TASKSEQ_LOOP_REPAIR_THRESHOLD
                            and scheduled_count >= collection_size
                        ):
                            missing_indexes = await self._find_missing_loop_iteration_indices(
                                state.execution_id,
                                event.step,
                                loop_event_id=resolved_loop_event_id,
                                limit=_TASKSEQ_LOOP_REPAIR_THRESHOLD,
                            )
                            if missing_indexes:
                                issued_repairs_raw = loop_state.get("repair_issued_indexes", [])
                                issued_repairs = {
                                    int(idx)
                                    for idx in issued_repairs_raw
                                    if isinstance(idx, int) or (isinstance(idx, str) and idx.isdigit())
                                }
                                repaired_now: list[int] = []

                                for missing_idx in missing_indexes:
                                    if (
                                        missing_idx in issued_repairs
                                        or missing_idx < 0
                                        or missing_idx >= collection_size
                                    ):
                                        continue

                                    retry_command = await self._create_command_for_step(
                                        state,
                                        parent_step_def,
                                        {
                                            "__loop_continue": True,
                                            "__loop_retry": True,
                                            "__loop_retry_index": missing_idx,
                                        },
                                    )
                                    if retry_command:
                                        commands.append(retry_command)
                                        issued_repairs.add(missing_idx)
                                        repaired_now.append(missing_idx)

                                if repaired_now:
                                    loop_state["repair_issued_indexes"] = sorted(issued_repairs)
                                    logger.warning(
                                        "[TASK_SEQ-LOOP] Reissued missing tail iterations for %s: %s "
                                        "(completed=%s scheduled=%s size=%s)",
                                        parent_step,
                                        repaired_now,
                                        new_count,
                                        scheduled_count,
                                        collection_size,
                                    )

                        if collection_size > 0 and new_count >= collection_size:
                            if not _nats_count_reliable:
                                logger.warning(
                                    "[TASK_SEQ-LOOP] Fallback count %s >= size %s but NATS increment failed — "
                                    "skipping loop.done claim for %s (execution=%s); "
                                    "issuing continuation commands to avoid stall (cross-epoch inflation possible)",
                                    new_count,
                                    collection_size,
                                    parent_step,
                                    state.execution_id,
                                )
                                # When NATS is unreliable the fallback (_count_step_events) is cross-epoch
                                # inflated: it counts ALL call.done events across every prior epoch, not just
                                # the current one.  Treating that inflated total as a completion signal causes
                                # a silent deadlock: the loop-done path is skipped (guard below) AND the
                                # else-branch that issues more commands is never reached.  Instead, try to
                                # continue issuing commands; NATS claim_next_loop_index will gate on actual
                                # in-flight state and the DB work-queue's FOR UPDATE SKIP LOCKED handles the
                                # case where no patients remain.
                                next_cmds = await self._issue_loop_commands(
                                    state,
                                    parent_step_def,
                                    {"__loop_continue": True},
                                )
                                commands.extend(next_cmds)
                            else:
                                # Guard: atomically claim the right to fire loop.done for this epoch.
                                # Prevents duplicate loopback dispatches when multiple concurrent
                                # call.done handlers reach this point simultaneously (e.g. via the
                                # NATS-fallback count path where all handlers see the same persisted count).
                                _skip_loop_done = False
                                try:
                                    if not await nats_cache.try_claim_loop_done(
                                        str(state.execution_id),
                                        parent_step,
                                        event_id=resolved_loop_event_id,
                                    ):
                                        logger.info(
                                            "[TASK_SEQ-LOOP] loop.done already claimed for %s (execution=%s), skipping dispatch",
                                            parent_step,
                                            state.execution_id,
                                        )
                                        _skip_loop_done = True
                                        # Still update local state so the dedup guard in
                                        # _evaluate_next_transitions recognises the loop as
                                        # completed when a subsequent step routes back to it
                                        # (e.g. loopback pattern: fetch_assessments → load_patients
                                        # → fetch_assessments epoch 2).  Without this the pod that
                                        # did NOT fire loop.done has completed=False in its in-memory
                                        # loop_state and completed_steps, causing it to block the
                                        # re-dispatch via the issued_steps dedup guard.
                                        loop_state["completed"] = True
                                        loop_state["aggregation_finalized"] = True
                                        state.mark_step_completed(
                                            parent_step,
                                            state.get_loop_aggregation(parent_step),
                                        )

                                        # [CLAIM-RECOVERY] If the claim was lost (claimed in KV but event never persisted),
                                        # proceed with the transition anyway to avoid stalling the workflow.
                                        if not _is_loop_epoch_transition_emitted(
                                            state, parent_step, "loop.done", resolved_loop_event_id
                                        ):
                                            logger.warning(
                                                "[TASK_SEQ-LOOP] loop.done claim held for %s (epoch=%s) but no event found in history — "
                                                "RECOVERING transition to avoid stall",
                                                parent_step,
                                                resolved_loop_event_id,
                                            )
                                            _skip_loop_done = False
                                except Exception as _claim_err:
                                    logger.warning(
                                        "[TASK_SEQ-LOOP] try_claim_loop_done failed for %s: %s — proceeding with aggregation_finalized guard",
                                        parent_step,
                                        _claim_err,
                                    )
                                    # Fall through: aggregation_finalized is a second-layer in-process guard.

                                if not _skip_loop_done:
                                    # Loop done - mark completed and create loop.done event
                                    loop_state["completed"] = True
                                    loop_state["aggregation_finalized"] = True
                                    logger.info(f"[TASK_SEQ-LOOP] Loop completed for {parent_step}: {new_count}/{collection_size}")

                                    # Get aggregated result
                                    loop_aggregation = state.get_loop_aggregation(parent_step)
                                    state.mark_step_completed(parent_step, loop_aggregation)

                                    # Evaluate next transitions with loop.done event
                                    loop_done_event = Event(
                                        execution_id=event.execution_id,
                                        step=parent_step,
                                        name="loop.done",
                                        payload={
                                            "status": "completed",
                                            "iterations": new_count,
                                            "result": loop_aggregation,
                                            "loop_event_id": resolved_loop_event_id
                                        },
                                        parent_event_id=state.root_event_id
                                    )
                                    await self._persist_event(loop_done_event, state)
                                    state.add_emitted_loop_epoch(parent_step, "loop.done", str(resolved_loop_event_id))
                                    loop_done_commands = await self._evaluate_next_transitions(state, parent_step_def, loop_done_event)
                                    commands.extend(loop_done_commands)
                                    logger.info(f"[TASK_SEQ-LOOP] Generated {len(loop_done_commands)} commands from loop.done")
                        else:
                            # More iterations - create next command
                            if collection_size == 0:
                                logger.warning(
                                    f"[TASK_SEQ-LOOP] Collection size unresolved for {parent_step}; "
                                    f"continuing without completion check"
                                )
                            logger.info(
                                f"[TASK_SEQ-LOOP] Issuing iteration commands for {parent_step}: "
                                f"{new_count}/{collection_size} (mode={parent_step_def.loop.mode})"
                            )
                            next_cmds = await self._issue_loop_commands(
                                state,
                                parent_step_def,
                                {"__loop_continue": True},
                            )
                            commands.extend(next_cmds)

                    except Exception as e:
                        logger.error(f"[TASK_SEQ-LOOP] Error handling loop: {e}", exc_info=True)
            else:
                # Not in loop - parent step was already marked completed above (before set processing)
                # with the last tool's result promoted to the top level for flat template access.
                logger.info(f"[TASK_SEQ] Parent step '{parent_step}' already marked completed with promoted result")

                # Process remaining actions from task sequence result (next, etc.)
                remaining_actions = response_data.get("remaining_actions", [])
                if remaining_actions:
                    logger.debug("[TASK_SEQ] Processing remaining actions count=%s", len(remaining_actions))
                    seq_commands = await self._process_then_actions(
                        remaining_actions, state, event
                    )
                    commands.extend(seq_commands)
                    logger.info(f"[TASK_SEQ] Generated {len(seq_commands)} commands from remaining actions")
                else:
                    # No remaining actions - evaluate next transitions for parent step
                    next_commands = await self._evaluate_next_transitions(state, parent_step_def, event)
                    commands.extend(next_commands)
                    logger.info(f"[TASK_SEQ] Generated {len(next_commands)} commands from next transitions")

            for cmd in commands:
                pending_key = _pending_step_key(cmd.step)
                if not pending_key:
                    continue
                state.issued_steps.add(pending_key)
                logger.info(
                    "[ISSUED] Added task-sequence %s to issued_steps for execution %s, total issued=%s",
                    pending_key,
                    state.execution_id,
                    len(state.issued_steps),
                )

            # Task-sequence call.done can mutate loop_state, variables, and pending tracking
            # even when the next actionable command is emitted by the API after this method
            # returns. Persist that state before returning so later status/completion checks
            # do not see a stale pre-continuation snapshot.
            await self.state_store.save_state(state)
            if not already_persisted:
                await self._persist_event(event, state)
            return commands

        # Task-sequence lifecycle is driven by call.done/call.error. The corresponding
        # step.exit event is iteration-informative and should not trigger global
        # completion checks or structural routing.
        if event.step.endswith(":task_sequence") and event.name == "step.exit":
            logger.debug(f"[TASK_SEQ] Ignoring step.exit for task sequence step {event.step}")
            return commands

        # Strip :task_sequence suffix when looking up step definition
        # Task sequence steps have event.step like "fetch_page:task_sequence" but are defined as "fetch_page"
        step_name = event.step.replace(":task_sequence", "") if event.step.endswith(":task_sequence") else event.step
        step_def = state.get_step(step_name)
        if not step_def:
            logger.error(f"Step not found: {step_name} (original: {event.step})")
            return commands

        # Update current step (use original event.step to track task sequence state)
        state.set_current_step(event.step)
        
        # PRE-PROCESSING: Identify if a retry is triggered by worker eval rules
        # This is needed to handle pagination correctly in loops
        worker_eval_action = normalized_payload.get("eval_action") if isinstance(normalized_payload, dict) else None
        has_worker_retry = worker_eval_action and worker_eval_action.get("type") == "retry"

        # CRITICAL: Store call.done/call.error result in state BEFORE evaluating next transitions
        # This ensures the result is available in render context for subsequent steps
        if event.name == "call.done":
            response_data = (
                normalized_payload.get("response",
                    normalized_payload.get("result", normalized_payload))
                if isinstance(normalized_payload, dict)
                else normalized_payload
            )
            response_data = await _hydrate_reference_only_step_result(response_data)
            state.mark_step_completed(event.step, response_data)
            logger.debug(f"[CALL.DONE] Stored result for step {event.step} in state BEFORE next evaluation")
        elif event.name == "call.error":
            # Mark step as completed even on error - it finished executing (with failure)
            error_data = (
                normalized_payload.get("error", normalized_payload)
                if isinstance(normalized_payload, dict)
                else normalized_payload
            )
            state.completed_steps.add(event.step)
            # CRITICAL: Track that execution has failures for final status determination
            state.failed = True
            logger.debug(f"[CALL.ERROR] Marked step {event.step} as completed (with error), execution marked as failed")

        # Get render context AFTER storing call.done response
        context = state.get_render_context(event)

        # Process step-level set BEFORE evaluating next transitions
        # This ensures variables written by set are available in routing conditions
        step_set = getattr(step_def, "set", None)
        if event.name == "call.done" and step_set:
            logger.debug(
                "[SET] Processing step-level set for %s: keys=%s",
                event.step,
                list(step_set.keys()),
            )
            rendered_step_set: dict = {}
            for key, value_template in step_set.items():
                try:
                    if isinstance(value_template, str) and "{{" in value_template:
                        rendered_step_set[key] = self._render_template(value_template, context)
                    else:
                        rendered_step_set[key] = value_template
                    logger.debug("[SET] Rendered %s (type=%s)", key, type(rendered_step_set[key]).__name__)
                except Exception as e:
                    logger.error(f"[SET] Failed to render {key}: {e}")
            _apply_set_mutations(state.variables, rendered_step_set)
            # Refresh context after set to include new variables
            context = state.get_render_context(event)

        # Evaluate next[].when transitions ONCE and store results
        # This allows us to detect retries before deciding whether to aggregate results
        # IMPORTANT: Only process on call.done/call.error to avoid duplicate command generation
        # step.exit should NOT trigger next evaluation because the worker already emits call.done
        # which triggers next evaluation and generates transition commands
        # CRITICAL: For loop steps, skip next evaluation on call.done - the next transition
        # will be evaluated on loop.done event after all iterations complete. This prevents
        # fan-out where each loop iteration triggers the next step independently.
        next_commands: list[Command] = []
        next_any_matched: Optional[bool] = None
        is_loop_step = step_def.loop is not None and event.step in state.loop_state
        if event.name in ("call.done", "call.error") and not is_loop_step:
            next_commands, next_any_matched = await self._evaluate_next_transitions_with_match(
                state,
                step_def,
                event,
            )

        # Handle loop iteration counting for non-task_sequence loop steps on call.done.
        # Task sequence steps handle loop counting in the :task_sequence block above.
        # Non-task_sequence tools (playbook, postgres, python, etc.) in distributed loops
        # need loop counting here because step.exit is emitted as non-actionable and
        # never triggers handle_event().
        if event.name == "call.done" and is_loop_step:
            response_data = (
                normalized_payload.get("response",
                    normalized_payload.get("result", normalized_payload))
                if isinstance(normalized_payload, dict)
                else normalized_payload
            )
            loop_state = state.loop_state[event.step]
            if not loop_state.get("aggregation_finalized", False):
                status_str = ""
                if isinstance(response_data, dict):
                    status_str = response_data.get("status", "") or ""
                failed = status_str.upper() in ("FAILED", "ERROR")
                state.add_loop_result(event.step, response_data, failed=failed)
                logger.info(f"[LOOP-CALL.DONE] Added iteration result to loop aggregation for {event.step}")

                # Increment NATS K/V loop counter
                try:
                    nats_cache = await get_nats_cache()
                    payload_loop_event_id = (
                        event.payload.get("loop_event_id")
                        if isinstance(event.payload, dict)
                        else None
                    )
                    # Prefer the epoch ID baked into the command at dispatch time
                    # (__loop_epoch_id) over candidates that may include stale step_event_ids
                    # from a previous epoch after STATE-CACHE-INVALIDATE.
                    _pinned_epoch_id = (
                        str(event.payload.get("__loop_epoch_id"))
                        if isinstance(event.payload, dict) and event.payload.get("__loop_epoch_id")
                        else (str(payload_loop_event_id) if payload_loop_event_id else None)
                    )
                    loop_event_id = _pinned_epoch_id or loop_state.get("event_id")
                    event_id_candidates = []
                    if loop_event_id:
                        event_id_candidates.append(str(loop_event_id))
                    if not _pinned_epoch_id:
                        # No pinned epoch: fall back to full candidate resolution which
                        # may include stale step_event_ids (kept for backward compatibility).
                        for candidate in self._build_loop_event_id_candidates(state, event.step, loop_state):
                            if candidate not in event_id_candidates:
                                event_id_candidates.append(candidate)
                    else:
                        # Epoch is pinned: only add exec fallback, not stale step_event_ids.
                        exec_fallback = f"exec_{state.execution_id}"
                        if exec_fallback not in event_id_candidates:
                            event_id_candidates.append(exec_fallback)
                    resolved_loop_event_id = (
                        event_id_candidates[0] if event_id_candidates else f"exec_{state.execution_id}"
                    )

                    new_count = -1
                    for candidate_event_id in event_id_candidates:
                        candidate_count = await nats_cache.increment_loop_completed(
                            str(state.execution_id), event.step, event_id=candidate_event_id
                        )
                        if candidate_count >= 0:
                            new_count = candidate_count
                            resolved_loop_event_id = candidate_event_id
                            break

                    _nats_count_reliable = True
                    if new_count < 0:
                        _nats_count_reliable = False
                        new_count = state.get_loop_completed_count(event.step)
                        persisted_count = await self._count_step_events(
                            state.execution_id, event.step, "call.done"
                        )
                        if persisted_count >= 0:
                            new_count = max(new_count, persisted_count)
                        logger.warning(
                            f"[LOOP-CALL.DONE] Could not increment NATS loop count for {event.step}; "
                            f"falling back to persisted/local count {new_count}"
                        )
                    else:
                        logger.debug(
                            f"[LOOP-CALL.DONE] Incremented loop count in NATS K/V for "
                            f"{event.step} via {resolved_loop_event_id}: {new_count}"
                        )

                    loop_state["event_id"] = resolved_loop_event_id

                    # Resolve collection size from NATS or re-render
                    nats_loop_state = await nats_cache.get_loop_state(
                        str(state.execution_id), event.step, event_id=resolved_loop_event_id
                    )
                    collection_size = int((nats_loop_state or {}).get("collection_size", 0) or 0)

                    if collection_size == 0:
                        loop_context = state.get_render_context(event)
                        rendered_collection = self._render_template(step_def.loop.in_, loop_context)
                        rendered_collection = self._normalize_loop_collection(rendered_collection, event.step)
                        loop_state["collection"] = list(rendered_collection)
                        collection_size = len(rendered_collection)
                        logger.info(f"[LOOP-CALL.DONE] Re-rendered collection for {event.step}: {collection_size} items")

                    # Check if loop is done
                    if collection_size > 0 and new_count >= collection_size:
                        if not _nats_count_reliable:
                            logger.warning(
                                "[LOOP-CALL.DONE] Fallback count %s >= size %s but NATS increment failed — "
                                "skipping loop.done claim for %s (execution=%s); "
                                "next reliable call.done will claim it",
                                new_count,
                                collection_size,
                                event.step,
                                state.execution_id,
                            )
                        else:
                            # Guard: atomically claim the right to fire loop.done for this epoch.
                            # Prevents duplicate loopback dispatches when multiple concurrent
                            # call.done handlers reach this point simultaneously (e.g. via the
                            # NATS-fallback count path where all handlers see the same persisted count).
                            _skip_loop_done = False
                            try:
                                if not await nats_cache.try_claim_loop_done(
                                    str(state.execution_id),
                                    event.step,
                                    event_id=resolved_loop_event_id,
                                ):
                                    logger.info(
                                        "[LOOP-CALL.DONE] loop.done already claimed for %s (execution=%s), skipping dispatch",
                                        event.step,
                                        state.execution_id,
                                    )
                                    _skip_loop_done = True
                                    # Update local state so subsequent routing from a
                                    # loopback step (e.g. load_patients → fetch_assessments
                                    # epoch 2) is not blocked by the issued_steps dedup guard
                                    # on this pod, which did not fire loop.done itself.
                                    loop_state["completed"] = True
                                    loop_state["aggregation_finalized"] = True
                                    state.mark_step_completed(
                                        event.step,
                                        state.get_loop_aggregation(event.step),
                                    )

                                    # [CLAIM-RECOVERY] If the claim was lost (claimed in KV but event never persisted),
                                    # proceed with the transition anyway to avoid stalling the workflow.
                                    if not _is_loop_epoch_transition_emitted(
                                        state, event.step, "loop.done", resolved_loop_event_id
                                    ):
                                        logger.warning(
                                            "[LOOP-CALL.DONE] loop.done claim held for %s (epoch=%s) but no event found in history — "
                                            "RECOVERING transition to avoid stall",
                                            event.step,
                                            resolved_loop_event_id,
                                        )
                                        _skip_loop_done = False
                            except Exception as _claim_err:
                                logger.warning(
                                    "[LOOP-CALL.DONE] try_claim_loop_done failed for %s: %s — proceeding with aggregation_finalized guard",
                                    event.step,
                                    _claim_err,
                                )
                                # Fall through: aggregation_finalized is a second-layer in-process guard.

                            if not _skip_loop_done:
                                loop_state["completed"] = True
                                loop_state["aggregation_finalized"] = True
                                logger.info(f"[LOOP-CALL.DONE] Loop completed for {event.step}: {new_count}/{collection_size}")

                                loop_aggregation = state.get_loop_aggregation(event.step)
                                state.mark_step_completed(event.step, loop_aggregation)

                                loop_done_event = Event(
                                    execution_id=event.execution_id,
                                    step=event.step,
                                    name="loop.done",
                                    payload={
                                        "status": "completed",
                                        "iterations": new_count,
                                        "result": loop_aggregation,
                                        "loop_event_id": resolved_loop_event_id
                                    },
                                    parent_event_id=state.root_event_id
                                )
                                await self._persist_event(loop_done_event, state)
                                state.add_emitted_loop_epoch(event.step, "loop.done", str(resolved_loop_event_id))
                                loop_done_commands = await self._evaluate_next_transitions(
                                    state, step_def, loop_done_event
                                )
                                commands.extend(loop_done_commands)
                                logger.info(
                                    f"[LOOP-CALL.DONE] Generated {len(loop_done_commands)} commands from loop.done"
                                )
                    else:
                        # More iterations needed
                        logger.info(
                            f"[LOOP-CALL.DONE] Issuing iteration commands for {event.step}: "
                            f"{new_count}/{collection_size} (mode={step_def.loop.mode})"
                        )
                        iter_cmds = await self._issue_loop_commands(
                            state, step_def, {"__loop_continue": True}
                        )
                        commands.extend(iter_cmds)

                except Exception as e:
                    logger.error(f"[LOOP-CALL.DONE] Error handling loop: {e}", exc_info=True)

        # Identify retry commands (commands targeting the same step are retries)
        server_retry_commands = [c for c in next_commands if c.step == event.step]

        is_retrying = bool(server_retry_commands) or has_worker_retry
        if is_retrying:
            logger.info(f"[ENGINE] Step {event.step} is retrying (server_retry={bool(server_retry_commands)}, worker_retry={has_worker_retry})")
            state.pagination_state.setdefault(event.step, {})["pending_retry"] = True
        else:
            # If no retry triggered by THIS event, clear pending flag
            if event.step in state.pagination_state:
                state.pagination_state[event.step]["pending_retry"] = False

        # Store step result if this is a step.exit event
        logger.debug(
            "[LOOP_DEBUG] Checking step.exit: name=%s has_result=%s payload_keys=%s",
            event.name,
            "result" in event.payload,
            list(event.payload.keys()),
        )
        if event.name == "step.exit" and "result" in event.payload:
            logger.debug(
                "[LOOP_DEBUG] step.exit with result for %s loop=%s in_loop_state=%s",
                event.step,
                bool(step_def.loop),
                event.step in state.loop_state,
            )
            
            # Use the is_retrying flag we just determined
            if is_retrying:
                logger.debug(f"[LOOP_DEBUG] Pagination retry active for {event.step}; skipping aggregation and loop advance")
            
            # If pagination collected data for this step, merge it into the current result before aggregation
            # and reset pagination state for the next iteration/run when no retry is pending.
            pagination_state = state.pagination_state.get(event.step)
            if pagination_state and not is_retrying:
                collected_data = pagination_state.get("collected_data", [])
                if collected_data:
                    current_result = event.payload.get("result", {})

                    pagination_summary = {
                        "pages_collected": pagination_state.get("iteration_count", 0),
                        "all_items": collected_data,
                    }

                    flattened_items: list[Any] = []
                    for item in collected_data:
                        if isinstance(item, list):
                            flattened_items.extend(item)
                        else:
                            flattened_items.append(item)

                    if isinstance(current_result, dict):
                        current_result["_pagination"] = pagination_summary
                        current_result["_all_collected_items"] = flattened_items
                    else:
                        current_result = {
                            "original_result": current_result,
                            "_pagination": pagination_summary,
                            "_all_collected_items": flattened_items,
                        }

                    event.payload["result"] = current_result
                    logger.info(
                        f"[PAGINATION] Merged collected pagination data into result for {event.step}: "
                        f"{len(flattened_items)} total items over {pagination_state.get('iteration_count', 0)} pages"
                    )

                # Reset pagination state for next iteration/run to avoid bleed-over
                state.pagination_state[event.step] = {
                    "collected_data": [],
                    "iteration_count": 0,
                    "pending_retry": False,
                }
            
            # If in a loop, add iteration result to aggregation (for ALL iterations)
            if step_def.loop and event.step in state.loop_state and not is_retrying:
                # Check if loop aggregation already finalized (loop_done happened)
                loop_state = state.loop_state[event.step]
                logger.debug(
                    "[LOOP_DEBUG] Loop state: completed=%s finalized=%s results_count=%s buffered=%s omitted=%s",
                    loop_state.get("completed"),
                    loop_state.get("aggregation_finalized"),
                    _loop_results_total(loop_state),
                    len(loop_state.get("results", []))
                    if isinstance(loop_state.get("results"), list)
                    else 0,
                    int(loop_state.get("omitted_results_count", 0) or 0),
                )
                if not loop_state.get("aggregation_finalized", False):
                    failed = event.payload.get("status", "").upper() == "FAILED"
                    state.add_loop_result(event.step, event.payload["result"], failed=failed)
                    logger.info(f"Added iteration result to loop aggregation for step {event.step}")
                    
                    # Sync completed count to distributed NATS K/V cache for multi-server deployments
                    # NOTE: We only increment the count, NOT store the actual result
                    # Results are stored in event table and fetched via aggregate service
                    try:
                        nats_cache = await get_nats_cache()
                        # Get event_id from loop state to identify this loop instance
                        loop_event_id = loop_state.get("event_id")
                        new_count = await nats_cache.increment_loop_completed(
                            str(state.execution_id),
                            event.step,
                            event_id=str(loop_event_id) if loop_event_id else None
                        )
                        if new_count >= 0:
                            logger.debug(f"[LOOP-NATS] Incremented completion count in NATS K/V for {event.step}: {new_count}, event_id={loop_event_id}")
                        else:
                            logger.error(f"[LOOP-NATS] Failed to increment completion count in NATS K/V for {event.step}, event_id={loop_event_id}")
                    except Exception as e:
                        logger.error(f"[LOOP-NATS] Error syncing to NATS K/V: {e}", exc_info=True)
                else:
                    logger.info(f"Loop aggregation already finalized for {event.step}, skipping result storage")
            elif not is_retrying:
                # Not in loop or loop done - store as normal step result
                # SKIP for task sequence steps - the task sequence handler already stored
                # the properly unwrapped result on call.done event
                if event.step.endswith(":task_sequence"):
                    logger.debug(f"Skipping step.exit result storage for task sequence step {event.step} (already handled on call.done)")
                else:
                    hydrated_result = await _hydrate_reference_only_step_result(event.payload["result"])
                    state.mark_step_completed(event.step, hydrated_result)
                    logger.debug(f"Stored result for step {event.step} in state")
        
        # Note: call.done response was stored earlier (before next evaluation) to ensure
        # it's available in render_context when creating commands for subsequent steps

        # Add next transition commands we already generated to the final list
        commands.extend(next_commands)

        # DISABLED: Worker eval action processing
        # The server now evaluates all next[].when transitions on call.done events,
        # so we don't need to process worker eval actions. This prevents duplicate
        # command generation. The worker handles tool.eval for flow control (retry/fail/continue).
        should_process_worker_action = False  # Disabled to prevent duplicate commands
        if should_process_worker_action:
            action_type = worker_eval_action.get("type")
            # Worker sends "steps" for next actions, "config" for retry
            action_config = worker_eval_action.get("config") or worker_eval_action.get("steps", {})

            logger.info(
                "[ENGINE] Server matched no rules, but worker reported '%s' action. config_keys=%s",
                action_type,
                _sample_keys(action_config),
            )

            if action_type == "retry":
                # Use _process_then_actions to handle the action correctly
                # We wrap it in a 'then' block format
                worker_commands = await self._process_then_actions(
                    [{"retry": action_config}],
                    state,
                    event
                )
                commands.extend(worker_commands)
                logger.info(f"[ENGINE] Applied retry from worker for step {event.step}")

            elif action_type == "next":
                # Worker sends steps as a list: [{"step": "upsert_user"}]
                # _process_then_actions expects next items to be step names or {step: name, set: {...}}
                worker_commands = await self._process_then_actions(
                    [{"next": action_config}],
                    state,
                    event
                )
                commands.extend(worker_commands)
                logger.info(f"[ENGINE] Applied next from worker: {len(worker_commands)} commands generated")
        
        # Handle loop.item events - continue loop iteration
        # Only process if next transitions didn't generate commands
        if not commands and event.name == "loop.item" and step_def.loop:
            logger.debug(f"Processing loop.item event for {event.step}")
            command = await self._create_command_for_step(state, step_def, {})
            if command:
                commands.append(command)
                logger.debug(f"Created command for next loop iteration")
            else:
                # Loop completed, would emit loop.done below
                logger.debug(f"Loop iteration complete, will check for loop.done")

        # Check if step has completed loop - emit loop.done event
        # Check on step.exit regardless of whether next transitions generated commands
        # (next may have matched call.done and generated transition commands)
        logger.debug(
            "[LOOP-DEBUG] Checking step.exit: step=%s event=%s has_loop=%s",
            event.step,
            event.name,
            step_def.loop is not None,
        )
        if step_def.loop and event.name == "step.exit":
            logger.debug(f"[LOOP-DEBUG] Entering loop completion check for {event.step}")

            # Extract loop event ID for recovery check
            loop_state = state.loop_state.get(event.step)
            resolved_loop_event_id = loop_state.get("event_id") if loop_state else None

            pagination_retry_pending = state.pagination_state.get(event.step, {}).get("pending_retry", False)
            if pagination_retry_pending:
                logger.debug(f"[LOOP_DEBUG] Pagination retry pending for {event.step}; skipping completion/next iteration")
            else:
                # Get loop state from NATS K/V (distributed cache) or local fallback
                nats_cache = await get_nats_cache()
                loop_state = state.loop_state.get(event.step)
                loop_event_id = loop_state.get("event_id") if loop_state else None
                nats_loop_state = await nats_cache.get_loop_state(
                    str(state.execution_id),
                    event.step,
                    event_id=str(loop_event_id) if loop_event_id else None
                )
                
                if not loop_state and not nats_loop_state:
                    logger.warning(f"No loop state for step {event.step}")
                else:
                    # Use NATS count if available (authoritative), otherwise local cache
                    # NOTE: NATS K/V stores only completed_count, not results array
                    if nats_loop_state:
                        completed_count = nats_loop_state.get("completed_count", 0)
                        logger.debug(f"[LOOP-NATS] Got count from NATS K/V: {completed_count}")
                    elif loop_state:
                        completed_count = _loop_results_total(loop_state)
                        logger.debug(f"[LOOP-LOCAL] Got count from local cache: {completed_count}")
                    else:
                        completed_count = 0
                    
                    # Only render collection if not already cached (expensive operation)
                    if loop_state and not loop_state.get("collection"):
                        context = state.get_render_context(event)
                        collection = self._render_template(step_def.loop.in_, context)
                        collection = self._normalize_loop_collection(collection, event.step)
                        loop_state["collection"] = list(collection)
                        logger.info(f"[LOOP-SETUP] Rendered collection for {event.step}: {len(collection)} items")
                        
                        # Store initial loop state in NATS K/V with event_id
                        # NOTE: We store only metadata and completed_count, NOT results array
                        loop_event_id = loop_state.get("event_id")
                        await nats_cache.set_loop_state(
                            str(state.execution_id),
                            event.step,
                            {
                                "collection_size": len(collection),
                                "completed_count": completed_count,
                                "scheduled_count": max(
                                    int(loop_state.get("scheduled_count", completed_count) or completed_count),
                                    completed_count,
                                ),
                                "iterator": loop_state.get("iterator"),
                                "mode": loop_state.get("mode"),
                                "event_id": loop_event_id
                            },
                            event_id=str(loop_event_id) if loop_event_id else None
                        )
                    
                    collection_size = len(loop_state["collection"]) if loop_state else (nats_loop_state.get("collection_size", 0) if nats_loop_state else 0)
                    logger.info(f"[LOOP-CHECK] Step {event.step}: {completed_count}/{collection_size} iterations completed")
                    
                    if collection_size == 0:
                        logger.warning(
                            f"[LOOP-CHECK] Step {event.step}: collection size unresolved; "
                            "continuing loop without completion check"
                        )

                    if collection_size == 0 or completed_count < collection_size:
                        # More items to process - top up commands up to loop max_in_flight.
                        logger.info(
                            "[LOOP] Issuing iteration commands for %s (mode=%s)",
                            event.step,
                            step_def.loop.mode if step_def.loop else "sequential",
                        )
                        loop_commands = await self._issue_loop_commands(state, step_def, {})
                        commands.extend(loop_commands)
                    else:
                        # Guard: one concurrent step.exit fires loop.done.
                        _loop_event_id_for_cas = loop_state.get("event_id") if loop_state else None
                        _skip_loop_done = False
                        try:
                            if not await nats_cache.try_claim_loop_done(
                                str(state.execution_id),
                                event.step,
                                event_id=_loop_event_id_for_cas,
                            ):
                                logger.info(
                                    "[LOOP-STEP.EXIT] loop.done already claimed for %s (execution=%s), skipping",
                                    event.step,
                                    state.execution_id,
                                )
                                _skip_loop_done = True
                                # Update local state so the dedup guard does not block
                                # re-dispatch of this loop step in loopback patterns.
                                if loop_state:
                                    loop_state["completed"] = True
                                    loop_state["aggregation_finalized"] = True
                                    state.mark_step_completed(
                                        event.step,
                                        state.get_loop_aggregation(event.step),
                                    )

                                    # [CLAIM-RECOVERY] If the claim was lost (claimed in KV but event never persisted),
                                    # proceed with the transition anyway to avoid stalling the workflow.
                                    if (
                                        not _is_loop_epoch_transition_emitted(
                                            state,
                                            event.step,
                                            "loop.done",
                                            _loop_event_id_for_cas,
                                        )
                                    ):
                                        logger.warning(
                                            "[LOOP-STEP.EXIT] loop.done claim held for %s (epoch=%s) but no event found in history — "
                                            "RECOVERING transition to avoid stall",
                                            event.step,
                                            _loop_event_id_for_cas,
                                        )
                                        _skip_loop_done = False
                        except Exception as _cas_err:
                            logger.warning(
                                "[LOOP-STEP.EXIT] try_claim_loop_done failed for %s: %s — proceeding",
                                event.step,
                                _cas_err,
                            )
                        if not _skip_loop_done:
                            # Loop done - create aggregated result and store as step result
                            logger.info(f"[LOOP] Loop completed for step {event.step}, creating aggregated result")

                            # Mark loop as completed in local state
                            if loop_state:
                                loop_state["completed"] = True
                                loop_state["aggregation_finalized"] = True
                                # NOTE: Results are stored locally in loop_state["results"] during execution
                                # For distributed deployments, the aggregate service fetches from event table
                                # NATS K/V only stores counts, NOT results (to respect 1MB limit)
                                logger.debug(f"[LOOP-COMPLETE] Local results count: {len(loop_state.get('results', []))}")

                            # Get aggregated loop results from local state
                            # NOTE: For distributed scenarios where local results may be incomplete,
                            # use the aggregate service endpoint to fetch authoritative results from event table
                            loop_aggregation = state.get_loop_aggregation(event.step)

                            # Check if step has pagination data to merge
                            if event.step in state.pagination_state:
                                pagination_data = state.pagination_state[event.step]
                                if pagination_data["collected_data"]:
                                    # Merge pagination data into aggregated result
                                    loop_aggregation["pagination"] = {
                                        "collected_items": pagination_data["collected_data"],
                                        "iteration_count": pagination_data["iteration_count"]
                                    }
                                    logger.info(f"Merged pagination data into loop result: {pagination_data['iteration_count']} iterations")

                            # Store aggregated result as the step result
                            # This makes it available to next steps via {{ loop_step_name }}
                            state.mark_step_completed(event.step, loop_aggregation)
                            logger.info(f"Stored aggregated loop result for {event.step}: {loop_aggregation['stats']}")

                            # Process loop.done event through next transitions
                            loop_done_event = Event(
                                execution_id=event.execution_id,
                                step=event.step,
                                name="loop.done",
                                payload={
                                    "status": "completed",
                                    "iterations": state.loop_state[event.step]["index"],
                                    "result": loop_aggregation,  # Include aggregated result in payload
                                    "loop_event_id": resolved_loop_event_id
                                },
                                parent_event_id=state.root_event_id
                            )
                            await self._persist_event(loop_done_event, state)
                            state.add_emitted_loop_epoch(event.step, "loop.done", str(resolved_loop_event_id))
                            loop_done_commands = await self._evaluate_next_transitions(state, step_def, loop_done_event)
                            commands.extend(loop_done_commands)

        # NOTE: step.vars is REMOVED in strict v10 - use scoped `set` mutations.

        # If step.exit event and no next/loop matched, use structural next as fallback
        # NOTE: This code path should rarely be hit because next transitions are evaluated
        # on call.done events. This is a fallback for steps without conditional routing.
        if event.name == "step.exit" and step_def.next and not commands:
            # Check if step failed - don't process next if it did
            step_status = event.payload.get("status", "").upper()
            if step_status == "FAILED":
                logger.info(f"[STRUCTURAL-NEXT] Step {event.step} failed, skipping structural next")
            # Only proceed to next if loop is done (or no loop) and step didn't fail
            elif not step_def.loop or state.is_loop_done(event.step):
                # Get next_mode from next.spec.mode (canonical v10)
                next_mode = "exclusive"
                if step_def.next and isinstance(step_def.next, dict):
                    next_spec = step_def.next.get("spec", {})
                    if isinstance(next_spec, dict) and "mode" in next_spec:
                        next_mode = next_spec.get("mode", "exclusive")

                logger.info(
                    "[STRUCTURAL-NEXT] No next matched for step.exit, using structural next (mode=%s, next_count=%s)",
                    next_mode,
                    len(step_def.next) if isinstance(step_def.next, list) else 1,
                )
                # Handle structural next
                next_items = step_def.next
                if isinstance(next_items, str):
                    next_items = [next_items]

                context = state.get_render_context(event)

                for next_item in next_items:
                    if isinstance(next_item, str):
                        target_step = next_item
                        when_condition = None
                    elif isinstance(next_item, dict):
                        target_step = next_item.get("step")
                        when_condition = next_item.get("when")
                    else:
                        continue

                    # Evaluate when condition if present
                    if when_condition:
                        if not self._evaluate_condition(when_condition, context):
                            logger.debug(f"[STRUCTURAL-NEXT] Skipping {target_step}: condition not met ({when_condition})")
                            continue
                        logger.info(f"[STRUCTURAL-NEXT] Condition matched for {target_step}: {when_condition}")

                    next_step_def = state.get_step(target_step)
                    if next_step_def:
                        issued_cmds = await self._issue_loop_commands(state, next_step_def, {})
                        if issued_cmds:
                            commands.extend(issued_cmds)
                            logger.info(
                                f"[STRUCTURAL-NEXT] Created {len(issued_cmds)} command(s) for step {target_step}"
                            )

                            # In exclusive mode, stop after first match
                            if next_mode == "exclusive":
                                break

        # Finalize pagination data if step.exit and no retry commands were generated
        if event.name == "step.exit" and event.step in state.pagination_state and not (step_def and step_def.loop):
            # Check if any commands were created for this step (retry)
            has_retry = any(cmd.step == event.step for cmd in commands)
            
            if not has_retry:
                # No retry, so pagination is complete - merge collected data into step result
                pagination_data = state.pagination_state[event.step]
                if pagination_data["collected_data"]:
                    current_result = event.payload.get("result", {})
                    
                    # Create pagination summary
                    pagination_summary = {
                        "pages_collected": pagination_data["iteration_count"],
                        "all_items": pagination_data["collected_data"]
                    }
                    
                    # Flatten if data is nested lists
                    flattened_items = []
                    for item in pagination_data["collected_data"]:
                        if isinstance(item, list):
                            flattened_items.extend(item)
                        else:
                            flattened_items.append(item)
                    
                    # Add to result
                    if isinstance(current_result, dict):
                        current_result["_pagination"] = pagination_summary
                        current_result["_all_collected_items"] = flattened_items
                    else:
                        current_result = {
                            "original_result": current_result,
                            "_pagination": pagination_summary,
                            "_all_collected_items": flattened_items
                        }
                    
                    # Update the step result with pagination data
                    state.mark_step_completed(event.step, current_result)
                    logger.info(f"[PAGINATION] Finalized pagination for {event.step}: {len(flattened_items)} total items collected over {pagination_data['iteration_count']} pages")
        
        # Check for completion (only emit once) - prepare completion events but persist after current event
        # Completion primarily triggers on call.done/call.error, with step.exit kept as a
        # resilience fallback for replay/legacy paths that surface terminal boundaries via step.exit.
        completion_events = []
        logger.debug(
            "COMPLETION CHECK: event=%s step=%s commands=%s completed=%s has_next=%s has_error=%s",
            event.name,
            event.step,
            len(commands),
            state.completed,
            bool(step_def.next if step_def else False),
            bool(event.payload.get("error")),
        )

        # Check if step failed
        has_error = event.payload.get("error") is not None

        # Only trigger completion if:
        # 1. call.done/call.error (primary) or step.exit (fallback)
        # 2. No commands generated (no next transitions matched)
        # 3. EITHER: Step has NO next (true terminal step)
        #    OR: Step failed with no error handling (has error but no commands)
        # 4. Not already completed
        is_terminal_step = step_def and not step_def.next
        is_failed_with_no_handler = has_error and not commands
        is_completion_trigger = event.name in ("call.done", "call.error", "step.exit")

        # Check for pending commands using multiple methods:
        # 1. In-memory state tracking (issued_steps vs completed_steps)
        # 2. Database query as backup (only if in-memory state is uncertain)
        has_pending_commands = False

        # Debug: log current state before pending check
        logger.debug(
            "[PENDING-CHECK] execution=%s issued_steps=%s completed_steps=%s",
            event.execution_id,
            len(state.issued_steps) if hasattr(state, "issued_steps") else "N/A",
            len(state.completed_steps),
        )

        # First check in-memory: issued_steps that aren't in completed_steps.
        # Normalize synthetic task_sequence command keys back to their parent step names.
        issued_not_completed = set()
        if hasattr(state, "issued_steps"):
            # Build normalized completed set for comparison (handles task_sequence suffix mismatch)
            normalized_completed = {_pending_step_key(s) for s in state.completed_steps if s}
            for issued_step in state.issued_steps:
                pending_key = _pending_step_key(issued_step)
                if pending_key and pending_key not in normalized_completed:
                    issued_not_completed.add(pending_key)
        if issued_not_completed:
            has_pending_commands = True
            logger.debug(
                "[COMPLETION] execution=%s pending_in_memory=%s pending_steps=%s",
                event.execution_id,
                len(issued_not_completed),
                issued_not_completed,
            )
        elif not hasattr(state, 'issued_steps') or not state.issued_steps:
            # Only fall back to database query if in-memory state might be stale (e.g., after restart)
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT COUNT(*) as pending_count
                        FROM (
                            SELECT node_name
                            FROM noetl.event
                            WHERE execution_id = %(execution_id)s
                              AND event_type = 'command.issued'
                            EXCEPT
                            SELECT node_name
                            FROM noetl.event
                            WHERE execution_id = %(execution_id)s
                              AND event_type = 'call.done'
                        ) AS pending
                        """,
                        {"execution_id": int(event.execution_id)},
                    )
                    row = await cur.fetchone()
                    pending_count = row["pending_count"] if row else 0
                    has_pending_commands = pending_count > 0
                    if has_pending_commands:
                        logger.debug(f"[COMPLETION] execution={event.execution_id} pending_in_db={pending_count}")
        # If in-memory state shows no pending AND issued_steps is populated, trust it

        has_matching_next_transition = (
            (
                next_any_matched
                if next_any_matched is not None
                else self._has_matching_next_transition(state, step_def, context)
            )
            if (is_completion_trigger and step_def.next and not is_loop_step)
            else False
        )
        is_dead_end_no_match = (
            is_completion_trigger
            and bool(step_def.next)
            and not is_loop_step
            and not has_matching_next_transition
            and not commands
            and not has_pending_commands
        )
        if is_dead_end_no_match:
            logger.info(
                "[COMPLETION] Dead-end transition with no matching next arcs: execution=%s step=%s",
                event.execution_id,
                event.step,
            )

        if (
            is_completion_trigger
            and not commands
            and not has_pending_commands
            and (is_terminal_step or is_failed_with_no_handler or is_dead_end_no_match)
            and not state.completed
        ):
            # No more commands to execute - workflow and playbook are complete (or failed)
            state.completed = True
            # Check if ANY step failed during execution (state.failed) OR if this final step has error
            # This ensures we report failure even if execution continued past failed steps
            from noetl.core.dsl.v2.models import LifecycleEventPayload
            completion_status = "failed" if (state.failed or has_error) else "completed"
            if state.failed:
                logger.info(f"[COMPLETION] Execution {event.execution_id} marked as failed due to earlier step failures")
            
            # Persist current event FIRST to get its event_id for parent_event_id
            # Skip if already persisted by API caller
            if not already_persisted:
                await self._persist_event(event, state)
            
            # Now create completion events with current event as parent
            # This ensures proper ordering: call.done -> workflow_completion -> playbook_completion
            current_event_id = state.last_event_id
            
            # First, prepare workflow completion event
            workflow_completion_event = Event(
                execution_id=event.execution_id,
                step="workflow",
                name=f"workflow.{completion_status}",
                payload=LifecycleEventPayload(
                    status=completion_status,
                    final_step=event.step,
                    result=event.payload.get("result"),
                    error=event.payload.get("error")
                ).model_dump(),
                timestamp=datetime.now(timezone.utc),
                parent_event_id=current_event_id
            )
            completion_events.append(workflow_completion_event)
            logger.info(f"Workflow {completion_status}: execution_id={event.execution_id}, final_step={event.step}, parent_event_id={current_event_id}")
            
            # Then, prepare playbook completion event as final lifecycle event (parent is workflow_completion)
            # We'll set parent after persisting workflow_completion
            playbook_completion_event = Event(
                execution_id=event.execution_id,
                step=state.playbook.metadata.get("path", "playbook"),
                name=f"playbook.{completion_status}",
                payload=LifecycleEventPayload(
                    status=completion_status,
                    final_step=event.step,
                    result=event.payload.get("result"),
                    error=event.payload.get("error")
                ).model_dump(),
                timestamp=datetime.now(timezone.utc),
                parent_event_id=None  # Will be set after workflow_completion is persisted
            )
            completion_events.append(playbook_completion_event)
            logger.info(f"Playbook {completion_status}: execution_id={event.execution_id}, final_step={event.step}")
        
        # Save state
        await self.state_store.save_state(state)
        
        # Persist current event to database (if not already done for completion case)
        # Skip if event was already persisted by API caller
        if not completion_events and not already_persisted:
            await self._persist_event(event, state)
        
        # Persist completion events in order with proper parent_event_id chain
        for i, completion_event in enumerate(completion_events):
            if i > 0:
                # Set parent to previous completion event
                completion_event.parent_event_id = state.last_event_id
            await self._persist_event(completion_event, state)
        
        # CRITICAL: Stop generating commands if this is a failure event
        # Check AFTER persisting and completion events so they're all stored
        # Only check if we haven't already generated completion events (avoid duplicate stopping logic)
        if not completion_events:
            async def _emit_failed_terminal_events(final_step: str):
                if state.completed:
                    return

                from noetl.core.dsl.v2.models import LifecycleEventPayload

                state.completed = True
                current_event_id = state.last_event_id

                workflow_failed_event = Event(
                    execution_id=event.execution_id,
                    step="workflow",
                    name="workflow.failed",
                    payload=LifecycleEventPayload(
                        status="failed",
                        final_step=final_step,
                        result=event.payload.get("result"),
                        error=event.payload.get("error"),
                    ).model_dump(),
                    timestamp=datetime.now(timezone.utc),
                    parent_event_id=current_event_id,
                )
                await self._persist_event(workflow_failed_event, state)

                playbook_failed_event = Event(
                    execution_id=event.execution_id,
                    step=state.playbook.metadata.get("path", "playbook"),
                    name="playbook.failed",
                    payload=LifecycleEventPayload(
                        status="failed",
                        final_step=final_step,
                        result=event.payload.get("result"),
                        error=event.payload.get("error"),
                    ).model_dump(),
                    timestamp=datetime.now(timezone.utc),
                    parent_event_id=state.last_event_id,
                )
                await self._persist_event(playbook_failed_event, state)
                await self.state_store.save_state(state)

            if event.name == "command.failed":
                state.failed = True  # Track failure for final status
                # Only emit terminal events if the execution has NOT already recovered via a
                # call.error arc. If a prior call.error handler issued recovery steps (e.g., a
                # retry or fallback arc), has_pending_commands reflects those in-flight steps.
                # Emitting workflow.failed while recovery commands are pending would cut the
                # execution short and mark it failed even though it was progressing normally.
                if has_pending_commands:
                    logger.warning(
                        "[FAILURE] command.failed for step %s but execution has pending recovery "
                        "commands — skipping terminal emission to allow recovery to complete",
                        event.step,
                    )
                else:
                    logger.error(f"[FAILURE] Received command.failed event for step {event.step}, stopping execution")
                    await _emit_failed_terminal_events(event.step or "workflow")
                    return []  # Return empty commands list to stop workflow

            if event.name == "step.exit":
                step_status = event.payload.get("status", "").upper()
                if step_status == "FAILED":
                    state.failed = True  # Track failure for final status
                    logger.error(f"[FAILURE] Step {event.step} failed, stopping execution")
                    await _emit_failed_terminal_events(event.step or "workflow")
                    return []  # Return empty commands list to stop workflow

        # Track issued steps for pending commands detection
        for cmd in commands:
            pending_key = _pending_step_key(cmd.step)
            if not pending_key:
                continue
            state.issued_steps.add(pending_key)
            logger.info(
                f"[ISSUED] Added {pending_key} to issued_steps for execution {state.execution_id}, "
                f"total issued={len(state.issued_steps)}"
            )

        return commands
    
    async def _persist_event(self, event: Event, state: ExecutionState):
        """Persist event to database with state tracking."""
        # Use catalog_id from state, or lookup from existing events
        catalog_id = state.catalog_id
        
        if not catalog_id:
            # Fallback: lookup from existing events
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT catalog_id FROM noetl.event 
                        WHERE execution_id = %s 
                        LIMIT 1
                    """, (int(event.execution_id),))
                    result = await cur.fetchone()
                    catalog_id = result['catalog_id'] if result else None
        
        if not catalog_id:
            logger.error(f"Cannot persist event - no catalog_id for execution {event.execution_id}")
            return
        
        # Determine parent_event_id
        # Use event.parent_event_id if explicitly set (for completion events)
        # Otherwise, use default logic based on step or last event
        parent_event_id = event.parent_event_id
        if parent_event_id is None:
            if event.step:
                # For step events, parent is the last event in this step
                parent_event_id = state.step_event_ids.get(event.step)
            if not parent_event_id:
                # Otherwise, parent is the last event overall
                parent_event_id = state.last_event_id
        
        # Calculate duration for completion events
        # Set to 0 for other events to avoid NULL/undefined in UI
        duration_ms = 0
        event_timestamp = event.timestamp or datetime.now(timezone.utc)
        
        # Skip expensive duration DB query for loop iteration step.exit events
        # (task_sequence suffix indicates a loop iteration - these are high-frequency)
        is_loop_iteration_exit = (
            event.name == "step.exit"
            and event.step
            and (
                event.step.endswith(":task_sequence")
                or (event.step in state.loop_state if hasattr(state, 'loop_state') else False)
            )
        )
        
        if event.name == "step.exit" and event.step and not is_loop_iteration_exit:
            # Query for the corresponding step.enter event
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT created_at FROM noetl.event 
                        WHERE execution_id = %s 
                          AND node_id = %s 
                          AND event_type = 'step.enter'
                        ORDER BY event_id DESC
                        LIMIT 1
                    """, (int(event.execution_id), event.step))
                    enter_event = await cur.fetchone()
                    if enter_event and enter_event['created_at']:
                        start_time = enter_event['created_at']
                        # Ensure both timestamps are timezone-aware for subtraction
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                        if event_timestamp.tzinfo is None:
                            event_timestamp = event_timestamp.replace(tzinfo=timezone.utc)
                        duration_ms = int((event_timestamp - start_time).total_seconds() * 1000)
        
        elif "completed" in event.name or "failed" in event.name:
            # For workflow/playbook completion events, calculate total duration from workflow_initialized
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    # Determine which initialization event to use based on completion type
                    init_event_type = "workflow_initialized" if "workflow_" in event.name else "playbook_initialized"
                    
                    await cur.execute("""
                        SELECT created_at FROM noetl.event 
                        WHERE execution_id = %s 
                          AND event_type = %s
                        ORDER BY event_id ASC
                        LIMIT 1
                    """, (int(event.execution_id), init_event_type))
                    init_event = await cur.fetchone()
                    if init_event and init_event['created_at']:
                        start_time = init_event['created_at']
                        # Ensure both timestamps are timezone-aware for subtraction
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                        if event_timestamp.tzinfo is None:
                            event_timestamp = event_timestamp.replace(tzinfo=timezone.utc)
                        duration_ms = int((event_timestamp - start_time).total_seconds() * 1000)
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                # Generate event_id using the current cursor to avoid opening
                # a second pool connection (get_snowflake_id opens its own).
                await cur.execute("SELECT noetl.snowflake_id() AS snowflake_id")
                _sf_row = await cur.fetchone()
                event_id = int(_sf_row['snowflake_id'])
                
                # Store root_event_id on first event
                if event.name == "playbook_initialized" and state.root_event_id is None:
                    state.root_event_id = event_id
                
                # Build traceability metadata
                # CRITICAL: Convert all IDs to strings to prevent JavaScript precision loss with Snowflake IDs
                meta = {
                    "execution_id": str(event.execution_id),
                    "catalog_id": str(catalog_id) if catalog_id else None,
                    "root_event_id": str(state.root_event_id) if state.root_event_id else None,
                    "event_chain": [
                        str(state.root_event_id) if state.root_event_id else None,
                        str(parent_event_id) if parent_event_id else None,
                        str(event_id)
                    ] if state.root_event_id else [str(event_id)]
                }
                
                # Add parent execution link if present
                if state.parent_execution_id:
                    meta["parent_execution_id"] = str(state.parent_execution_id)
                
                # Add step-specific metadata
                if event.step:
                    meta["step"] = event.step
                    if event.step in state.step_event_ids:
                        meta["previous_step_event_id"] = str(state.step_event_ids[event.step])
                
                # Merge with existing context metadata from strict result envelope.
                context_data = {}
                payload_result = event.payload.get("result")
                if isinstance(payload_result, dict):
                    payload_context = payload_result.get("context")
                    if isinstance(payload_context, dict):
                        context_data = dict(payload_context)
                elif isinstance(event.payload.get("context"), dict):
                    # Transitional guard for non-step events that may still provide top-level context.
                    context_data = dict(event.payload.get("context") or {})

                if isinstance(context_data, dict):
                    # CRITICAL: Convert all IDs to strings to prevent JavaScript precision loss with Snowflake IDs
                    context_data["execution_id"] = str(event.execution_id)
                    context_data["catalog_id"] = str(catalog_id) if catalog_id else None
                    context_data["root_event_id"] = str(state.root_event_id) if state.root_event_id else None
                else:
                    context_data = {}
                
                # Determine status: Use payload status if provided, otherwise infer from event name
                payload_status = event.payload.get("status")
                if payload_status:
                    # Worker explicitly set status - use it (handles errors properly)
                    status = payload_status.upper() if isinstance(payload_status, str) else str(payload_status).upper()
                else:
                    # Fallback to event name-based status for events without explicit status
                    status = "FAILED" if "failed" in event.name else "COMPLETED" if ("step.exit" == event.name or "completed" in event.name) else "RUNNING"

                result_obj: dict[str, Any] = {"status": status}
                payload_reference = None
                if isinstance(payload_result, dict):
                    payload_reference = payload_result.get("reference")
                if not isinstance(payload_reference, dict):
                    payload_reference = event.payload.get("reference")
                if isinstance(payload_reference, dict):
                    result_obj["reference"] = payload_reference

                if event.name in ("loop.done", "loop.failed") and isinstance(event.payload, dict):
                    if "context" not in result_obj:
                        result_obj["context"] = {}
                    for k, v in event.payload.items():
                        if k not in result_obj["context"]:
                            result_obj["context"][k] = v

                await cur.execute("""
                    INSERT INTO noetl.event (
                        execution_id, catalog_id, event_id, parent_event_id, parent_execution_id, event_type,
                        node_id, node_name, status, context, result, 
                        error, stack_trace, worker_id, duration, meta, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    int(event.execution_id),
                    catalog_id,
                    event_id,
                    parent_event_id,
                    state.parent_execution_id,
                    event.name,
                    event.step,
                    event.step,
                    status,
                    Json(context_data) if context_data else None,
                    Json(result_obj),
                    Json(event.payload.get("error")) if event.payload.get("error") else None,
                    event.payload.get("stack_trace"),
                    event.worker_id,
                    duration_ms,
                    Json(meta),
                    event_timestamp
                ))
            await conn.commit()
        
        # Update tracking for next event
        state.last_event_id = event_id
        if event.step:
            state.step_event_ids[event.step] = event_id
    
    async def start_execution(
        self,
        playbook_path: str,
        payload: dict[str, Any],
        catalog_id: Optional[int] = None,
        parent_execution_id: Optional[int] = None
    ) -> tuple[str, list[Command]]:
        """
        Start a new playbook execution.
        
        Args:
            playbook_path: Path to playbook in catalog
            payload: Input data for execution
            catalog_id: Optional catalog ID
            parent_execution_id: Optional parent execution ID for sub-playbooks
        
        Returns (execution_id, initial_commands).
        """
        # Generate execution ID
        execution_id = str(await get_snowflake_id())
        
        # Load playbook - use catalog_id if provided to load specific version
        if catalog_id:
            playbook = await self.playbook_repo.load_playbook_by_id(catalog_id)
        else:
            playbook = await self.playbook_repo.load_playbook(playbook_path)
        
        if not playbook:
            raise ValueError(f"Playbook not found: catalog_id={catalog_id} path={playbook_path}")
        
        # Create execution state with catalog_id and parent_execution_id
        state = ExecutionState(execution_id, playbook, payload, catalog_id, parent_execution_id)
        await self.state_store.save_state(state)

        # Process keychain section before workflow starts
        if playbook.keychain and catalog_id:
            logger.info(f"ENGINE: Processing keychain section with {len(playbook.keychain)} entries")
            from noetl.server.keychain_processor import process_keychain_section
            try:
                keychain_data = await process_keychain_section(
                    keychain_section=playbook.keychain,
                    catalog_id=catalog_id,
                    execution_id=int(execution_id),
                    workload_vars=state.variables
                )
                if keychain_data:
                    # Expose keychain entries directly and under 'keychain' namespace for rendering
                    state.variables.update(keychain_data)
                    state.variables.setdefault("keychain", {}).update(keychain_data)
                logger.info(f"ENGINE: Keychain processing complete, created {len(keychain_data)} entries")
            except Exception as e:
                logger.error(f"ENGINE: Failed to process keychain section: {e}")
                # Don't fail execution, keychain errors will surface when workers try to resolve

        # Find entry step using canonical rules:
        # 1. executor.spec.entry_step if configured
        # 2. workflow[0].step (first step in workflow array)
        entry_step_name = playbook.get_entry_step()
        start_step = state.get_step(entry_step_name)
        if not start_step:
            # Fallback to legacy "start" step for backwards compatibility
            start_step = state.get_step("start")
            if start_step:
                entry_step_name = "start"
            else:
                raise ValueError(
                    f"Entry step '{entry_step_name}' not found in workflow. "
                    f"Available steps: {[s.step for s in playbook.workflow]}"
                )
        
        # Emit playbook.initialized event (playbook loaded and validated)
        # CRITICAL: Strip massive result objects from workload to prevent state pollution in sub-playbooks
        # Only keep genuine workload variables
        workload_snapshot = {}
        for k, v in state.variables.items():
            # Skip step result objects (they are usually dicts with 'id', 'status', 'data' keys)
            if isinstance(v, dict) and 'status' in v and ('data' in v or 'error' in v):
                continue
            # Skip large result proxies or objects
            if k in state.step_results:
                continue
            workload_snapshot[k] = v

        logger.info(
            "[PLAYBOOK-INIT] Workload snapshot prepared: keys=%s count=%s",
            _sample_keys(workload_snapshot),
            len(workload_snapshot),
        )

        from noetl.core.dsl.v2.models import LifecycleEventPayload
        playbook_init_event = Event(
            execution_id=execution_id,
            step=playbook_path,
            name="playbook.initialized",
            payload=LifecycleEventPayload(
                status="initialized",
                final_step=None,
                result={"workload": workload_snapshot, "playbook_path": playbook_path}
            ).model_dump(),
            timestamp=datetime.now(timezone.utc)
        )
        
        await self._persist_event(playbook_init_event, state)
        
        # Emit workflow.initialized event (workflow execution starting)
        workflow_init_event = Event(
            execution_id=execution_id,
            step="workflow",
            name="workflow.initialized",
            payload=LifecycleEventPayload(
                status="initialized",
                final_step=playbook.get_final_step(),  # Include final_step if configured
                result={"first_step": entry_step_name, "playbook_path": playbook_path, "workload": workload_snapshot}
            ).model_dump(),
            timestamp=datetime.now(timezone.utc)
        )
        
        await self._persist_event(workflow_init_event, state)
        
        # Create initial command(s) for start step.
        commands = await self._issue_loop_commands(state, start_step, payload)
        
        return execution_id, commands
