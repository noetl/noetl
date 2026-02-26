async def finalize_abandoned_execution(self, execution_id: str, reason: str = "Abandoned or timed out"):
    """
    Forcibly finalize an execution by emitting workflow.failed and playbook.failed events if not already completed.
    This should be called by a periodic task or admin action for stuck/running executions with no activity.
    """
    # Load state
    state = await self.state_store.load_state(execution_id)
    if not state:
        logger.error(f"[FINALIZE] No state found for execution {execution_id}")
        return
    if state.completed:
        logger.info(f"[FINALIZE] Execution {execution_id} already completed; skipping.")
        return

    # Find last step (if any)
    last_step = state.current_step or (list(state.step_results.keys())[-1] if state.step_results else None)
    logger.warning(f"[FINALIZE] Forcibly finalizing execution {execution_id} at step {last_step} due to: {reason}")

    from noetl.core.dsl.v2.models import Event, LifecycleEventPayload
    from datetime import datetime, timezone

    # Emit workflow.failed event
    workflow_failed_event = Event(
        execution_id=execution_id,
        step="workflow",
        name="workflow.failed",
        payload=LifecycleEventPayload(
            status="failed",
            final_step=last_step,
            result=None,
            error={"message": reason}
        ).model_dump(),
        timestamp=datetime.now(timezone.utc)
    )
    await self._persist_event(workflow_failed_event, state)

    # Emit playbook.failed event
    playbook_path = state.playbook.metadata.get("path", "playbook")
    playbook_failed_event = Event(
        execution_id=execution_id,
        step=playbook_path,
        name="playbook.failed",
        payload=LifecycleEventPayload(
            status="failed",
            final_step=last_step,
            result=None,
            error={"message": reason}
        ).model_dump(),
        timestamp=datetime.now(timezone.utc)
    )
    await self._persist_event(playbook_failed_event, state)

    # Mark state as completed
    state.completed = True
    await self.state_store.save_state(state)
    logger.info(f"[FINALIZE] Emitted terminal events for execution {execution_id}")
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
_TASKSEQ_LOOP_REPAIR_THRESHOLD = max(
    0,
    int(os.getenv("NOETL_TASKSEQ_LOOP_REPAIR_THRESHOLD", "3")),
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
        self.loop_state[step_name] = {
            "collection": collection,
            "iterator": iterator,
            "index": 0,
            "mode": mode,
            "completed": False,
            "results": [],  # Track iteration results for aggregation
            "failed_count": 0,  # Track failed iterations
            "scheduled_count": 0,  # Track issued iterations for max_in_flight gating
            "event_id": event_id  # Track which event initiated this loop instance
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
        self.loop_state[step_name]["results"].append(stored_result)
        if failed:
            self.loop_state[step_name]["failed_count"] += 1
        if stored_result is not result:
            logger.info(
                "[LOOP] Compacted large iteration result for %s (max=%s bytes)",
                step_name,
                _LOOP_RESULT_MAX_BYTES,
            )
        logger.debug(f"Added iteration result to loop {step_name}: {len(self.loop_state[step_name]['results'])} total")
        
        # Note: Distributed sync to NATS K/V happens in engine.handle_event()
    
    def get_loop_aggregation(self, step_name: str) -> dict[str, Any]:
        """Get aggregated loop results in standard format."""
        if step_name not in self.loop_state:
            return {"results": [], "stats": {"total": 0, "success": 0, "failed": 0}}
        
        loop_state = self.loop_state[step_name]
        total = len(loop_state["results"])
        failed = loop_state["failed_count"]
        success = total - failed
        
        return {
            "results": loop_state["results"],
            "stats": {
                "total": total,
                "success": success,
                "failed": failed
            }
        }
    
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
                "payload": event.payload,
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
        
        # Add event-specific data
        if "response" in event.payload:
            context["response"] = event.payload["response"]
        elif "result" in event.payload:
            # Fallback: expose result as response for templates that expect {{ response.* }} on step.exit
            context["response"] = event.payload["result"]
        if "error" in event.payload:
            context["error"] = event.payload["error"]
        if "result" in event.payload:
            context["result"] = event.payload["result"]
        else:
            # CRITICAL FIX: For call.done events, the worker sends the tool response
            # directly as the payload (not wrapped in a "result" key). Make the entire
            # payload available as "result" so case conditions like
            # {{ result.sub is defined }} work correctly.
            if event.name == "call.done" and event.payload:
                context["result"] = event.payload
                # Only set response if not already extracted from "response" key
                # Worker may send {"response": actual_response} where actual_response
                # was already extracted at line 413
                if "response" not in context:
                    context["response"] = event.payload
                logger.debug(f"[RENDER_CTX] Set result/response from call.done payload for {event.step}")

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
        # Bounded cache: max 1000 executions, 1 hour TTL
        self._memory_cache: BoundedCache[ExecutionState] = BoundedCache(
            max_size=1000,
            ttl_seconds=3600
        )
        self.playbook_repo = playbook_repo

    async def save_state(self, state: ExecutionState):
        """Save execution state."""
        await self._memory_cache.set(state.execution_id, state)

        # Pure event-driven: State is fully reconstructable from events
        # No need to persist to workload table - it's redundant with event log
        # Just keep in memory cache for performance
        logger.debug(f"State cached in memory for execution {state.execution_id}")
    
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
                    SELECT catalog_id, result
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
                    event_result = result.get("result")
                else:
                    catalog_id = result[0]
                    event_result = result[1]
                if catalog_id is None:
                    return None
                
                # Extract workload from playbook.initialized event result
                # This contains the merged workload (playbook defaults + parent args)
                workload = {}
                logger.debug(
                    "[STATE-LOAD] event_result type=%s truthy=%s is_dict=%s",
                    type(event_result).__name__,
                    bool(event_result),
                    isinstance(event_result, dict) if event_result is not None else False,
                )
                if event_result and isinstance(event_result, dict):
                    workload = event_result.get("workload", {})
                    logger.debug(
                        "[STATE-LOAD] restored workload keys=%s",
                        list(workload.keys()) if isinstance(workload, dict) else [],
                    )
                    if not workload:
                        logger.warning(
                            "[STATE-LOAD] workload is empty (event_result keys=%s)",
                            list(event_result.keys()),
                        )
                else:
                    logger.warning(
                        "[STATE-LOAD] Could not extract workload from event_result (type=%s)",
                        type(event_result).__name__,
                    )
                
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
                if hasattr(playbook, 'workflow') and playbook.workflow:
                    for step in playbook.workflow:
                        if hasattr(step, 'loop') and step.loop:
                            loop_steps.add(step.step)
                
                # Replay events to rebuild state (event sourcing)
                await cur.execute("""
                    SELECT node_name, event_type, result, meta
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id
                """, (int(execution_id),))
                
                rows = await cur.fetchall()
                
                # Track loop iteration results during event replay
                loop_iteration_results = {}  # {step_name: [result1, result2, ...]}
                loop_event_ids = {}  # {step_name: loop_event_id}
                
                for row in rows:
                    if isinstance(row, dict):
                        node_name = row.get("node_name")
                        event_type = row.get("event_type")
                        result_data = row.get("result")
                        meta_data = row.get("meta")
                    else:
                        node_name = row[0]
                        event_type = row[1]
                        result_data = row[2]
                        meta_data = row[3] if len(row) > 3 else None

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
                    elif event_type == 'command.completed':
                        pending_key = _pending_step_key(node_name)
                        if pending_key:
                            state.issued_steps.discard(pending_key)
                            logger.debug(f"[STATE-LOAD] Removed completed command from issued_steps: {pending_key}")

                    # Stored event.result values are wrapped as {"kind": "...", "data": {...}}.
                    # Replay should work against payload semantics, not the storage wrapper.
                    event_payload = result_data
                    if isinstance(result_data, dict) and "kind" in result_data and "data" in result_data:
                        event_payload = result_data.get("data")

                    # For loop steps, collect iteration results from step.exit events
                    if event_type == 'step.exit' and event_payload and node_name in loop_steps:
                        if node_name not in loop_iteration_results:
                            loop_iteration_results[node_name] = []
                        iteration_result = (
                            event_payload.get("result", event_payload)
                            if isinstance(event_payload, dict)
                            else event_payload
                        )
                        loop_iteration_results[node_name].append(iteration_result)

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
                        state.mark_step_completed(node_name, step_result)
                
                # Initialize loop_state for loop steps with collected iteration results
                for step_name in loop_steps:
                    # Count iterations by counting step.exit events for this step
                    # This gives us the current loop index when reconstructing state
                    iteration_count = len(loop_iteration_results.get(step_name, []))
                    
                    if step_name not in state.loop_state:
                        state.loop_state[step_name] = {
                            "collection": [],
                            "index": iteration_count,  # Start from number of completed iterations
                            "completed": False,
                            "results": loop_iteration_results.get(step_name, []),
                            "failed_count": 0,
                            "scheduled_count": iteration_count,
                            "aggregation_finalized": False,
                            "event_id": loop_event_ids.get(step_name),
                        }
                        logger.debug(f"[STATE-LOAD] Initialized loop_state for {step_name}: index={iteration_count}")
                    else:
                        # Restore collected results and update index
                        state.loop_state[step_name]["results"] = loop_iteration_results.get(step_name, [])
                        state.loop_state[step_name]["index"] = iteration_count
                        state.loop_state[step_name]["scheduled_count"] = max(
                            int(state.loop_state[step_name].get("scheduled_count", 0) or 0),
                            iteration_count,
                        )
                        loop_event_id = loop_event_ids.get(step_name)
                        if loop_event_id:
                            state.loop_state[step_name]["event_id"] = loop_event_id
                        logger.debug(f"[STATE-LOAD] Updated loop_state for {step_name}: index={iteration_count}")
                
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
        deleted = await self._memory_cache.delete(execution_id)
        if deleted:
            logger.info(f"Evicted completed execution {execution_id} from cache")


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

    async def _count_step_events(
        self,
        execution_id: str,
        node_name: str,
        event_type: str,
    ) -> int:
        """Count persisted events for a node/event pair (best-effort fallback path)."""
        try:
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT COUNT(*) AS cnt
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND node_name = %s
                          AND event_type = %s
                        """,
                        (int(execution_id), node_name, event_type),
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

    async def _find_missing_loop_iteration_indices(
        self,
        execution_id: str,
        node_name: str,
        loop_event_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[int]:
        """Find loop iteration indexes that were issued but have no terminal command event."""
        if limit <= 0:
            return []

        try:
            loop_filter = ""
            issued_params: list[Any] = [int(execution_id), node_name]
            if loop_event_id:
                loop_filter = "AND meta->>'loop_event_id' = %s"
                issued_params.append(str(loop_event_id))

            params: list[Any] = [
                *issued_params,
                int(execution_id),
                node_name,
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
                              AND node_name = %s
                              AND event_type = 'command.issued'
                              {loop_filter}
                        ),
                        terminal AS (
                            SELECT DISTINCT result->'data'->>'command_id' AS command_id
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = %s
                              AND event_type IN ('command.completed', 'command.failed')
                        )
                        SELECT i.loop_iteration_index
                        FROM issued i
                        LEFT JOIN terminal t ON t.command_id = i.command_id
                        WHERE i.loop_iteration_index IS NOT NULL
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
                "[TASK_SEQ-LOOP] Failed to detect missing loop iterations for %s/%s: %s",
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
        args: dict[str, Any],
    ) -> list[Command]:
        """Issue one or more loop commands based on loop mode and max_in_flight."""
        if not step_def.loop:
            command = await self._create_command_for_step(state, step_def, args)
            return [command] if command else []

        issue_budget = self._get_loop_max_in_flight(step_def)
        commands: list[Command] = []

        for _ in range(issue_budget):
            command = await self._create_command_for_step(state, step_def, args)
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
        """
        Evaluate next[].when conditions and return commands for matching transitions.

        Canonical format routing using next[].when:
        - Each next entry has optional 'when' condition
        - Entries without 'when' always match
        - next_mode controls evaluation: exclusive (first match) or inclusive (all matches)

        Example:
            next:
              - step: success_handler
                when: "{{ outcome.status == 'success' }}"
              - step: error_handler
                when: "{{ outcome.status == 'error' }}"
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
            return commands

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
            target_args = next_target.get("args", {})

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

            any_matched = True

            # Get target step definition
            target_step_def = state.get_step(target_step)
            if not target_step_def:
                logger.error(f"[NEXT-EVAL] Target step not found: {target_step}")
                continue

            # DEDUPLICATION: Skip if command for this step is already pending
            # This prevents duplicate commands when multiple events trigger orchestration
            if target_step in state.issued_steps and target_step not in state.completed_steps:
                logger.warning(f"[NEXT-EVAL] Skipping duplicate command for step '{target_step}' - already in issued_steps")
                continue

            # Render target args
            rendered_args = {}
            if target_args:
                from noetl.core.dsl.render import render_template as recursive_render
                rendered_args = recursive_render(self.jinja_env, target_args, context)

            # Create command(s) for target step. Loop steps may issue multiple commands
            # immediately up to max_in_flight when parallel mode is configured.
            issued_cmds = await self._issue_loop_commands(state, target_step_def, rendered_args)
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

        return commands

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
        - Reserved action types: next, set, result, fail, collect, retry
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
        reserved_actions = {"next", "set", "result", "fail", "collect", "retry"}

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
                        key not in {"next", "set", "result", "fail", "collect", "retry"}
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

            # Still process non-next reserved actions (set, result, fail, collect)
            for action in actions:
                if not isinstance(action, dict):
                    continue
                # Process set, result, fail, collect immediately (they don't depend on inline tasks)
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
                        args = {}
                    elif isinstance(next_item, dict):
                        # {step: name, args: {...}}
                        target_step = next_item.get("step")
                        args = next_item.get("args", {})
                        
                        # Render args
                        rendered_args = {}
                        for key, value in args.items():
                            if isinstance(value, str) and "{{" in value:
                                rendered_args[key] = self._render_template(value, context)
                            else:
                                rendered_args[key] = value
                        args = rendered_args
                    else:
                        continue
                    
                    # Auto-inject loop_results when transitioning from loop.done event
                    # The loop step acts as an aggregator, and its result should be passed as loop_results
                    if event.name == "loop.done" and event.step in state.step_results:
                        loop_result = state.step_results[event.step]
                        if "loop_results" not in args:
                            args["loop_results"] = loop_result
                            logger.info(f"Auto-injected loop_results for {target_step} from loop step {event.step}")
                    
                    # Get target step definition
                    step_def = state.get_step(target_step)
                    if not step_def:
                        logger.error(f"Target step not found: {target_step}")
                        continue
                    
                    # Create command for target step
                    issued_cmds = await self._issue_loop_commands(
                        state, step_def, args
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
            
            elif "result" in action:
                # Set step result
                result_spec = action["result"]
                if isinstance(result_spec, dict) and "from" in result_spec:
                    from_key = result_spec["from"]
                    if from_key in state.variables:
                        state.mark_step_completed(event.step, state.variables[from_key])
                else:
                    state.mark_step_completed(event.step, result_spec)
            
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

                # Extract data from response using path
                result_data = event.payload.get("response")
                if result_data is None and "result" in event.payload:
                    result_data = event.payload["result"]

                if result_data is None:
                    logger.warning(f"[COLLECT] No response or result payload to collect for step {step_name}")
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

                    # HTTP tool expects runtime pagination overrides under args['params']
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

                # Create retry command with updated args (same step)
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
                args = call_spec.get("args", {})
                
                if not target_step:
                    logger.warning("Call action missing 'step' attribute")
                    continue
                
                # Render args
                rendered_args = {}
                for key, value in args.items():
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
                retry_args = retry_spec.get("args", {})  # Get rendered args from worker
                
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
                
                # Create retry command with rendered args from worker
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
        Process immediate (non-deferred) actions like set, result, fail, collect.
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

        # NOTE: 'vars' action is REMOVED in strict v10 - use 'set' or task.spec.policy.rules set_ctx

        if "result" in action:
            # Set step result
            result_spec = action["result"]
            if isinstance(result_spec, dict) and "from" in result_spec:
                from_key = result_spec["from"]
                if from_key in state.variables:
                    state.mark_step_completed(event.step, state.variables[from_key])
            else:
                state.mark_step_completed(event.step, result_spec)

        elif "fail" in action:
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
                    args = {}
                elif isinstance(next_item, dict):
                    target_step = next_item.get("step")
                    args = next_item.get("args", {})

                    # Render args
                    rendered_args = {}
                    for key, value in args.items():
                        if isinstance(value, str) and "{{" in value:
                            rendered_args[key] = self._render_template(value, context)
                        else:
                            rendered_args[key] = value
                    args = rendered_args
                else:
                    continue

                # Get target step definition
                step_def = state.get_step(target_step)
                if not step_def:
                    logger.error(f"[DEFERRED-NEXT] Target step not found: {target_step}")
                    continue

                # Create command for target step
                issued_cmds = await self._issue_loop_commands(state, step_def, args)
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
                  status: "{{ result.status }}"

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
            args={},
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
            args={},
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
        args: dict[str, Any]
    ) -> Optional[Command]:
        """Create a command to execute a step."""
        control_args = args if isinstance(args, dict) else {}
        loop_retry_requested = bool(control_args.get("__loop_retry"))
        loop_retry_index_raw = control_args.get("__loop_retry_index")
        loop_continue_requested = bool(control_args.get("__loop_continue"))
        loop_retry_index: Optional[int] = None
        loop_event_id_for_metadata: Optional[str] = None
        claimed_index: Optional[int] = None
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

            # Initialize local loop state if needed and refresh collection snapshot.
            # IMPORTANT: A loop step can be re-entered multiple times in the same execution
            # (e.g., load -> normalize -> process(loop) -> load). When the prior loop
            # invocation is already finalized, reset counters/results and use a fresh
            # distributed loop key so claim slots are not stuck at old scheduled/completed
            # counts (e.g., 100/100 from the previous batch).
            existing_loop_state = state.loop_state.get(step.step)
            force_new_loop_instance = False
            if existing_loop_state is None:
                loop_event_id = f"loop_{state.last_event_id or get_snowflake_id()}"
                state.init_loop(
                    step.step,
                    collection,
                    step.loop.iterator,
                    step.loop.mode,
                    event_id=loop_event_id,
                )
                existing_loop_state = state.loop_state[step.step]
            else:
                previous_collection = existing_loop_state.get("collection")
                previous_size = len(previous_collection) if isinstance(previous_collection, list) else 0
                previous_completed = len(existing_loop_state.get("results", []))
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

                should_reset_existing_loop = (
                    not loop_continue_requested
                    and not loop_retry_requested
                    and (previous_finalized or previous_exhausted)
                )

                if should_reset_existing_loop:
                    loop_event_id = f"loop_{state.last_event_id or get_snowflake_id()}"
                    state.init_loop(
                        step.step,
                        collection,
                        step.loop.iterator,
                        step.loop.mode,
                        event_id=loop_event_id,
                    )
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
                    existing_loop_state["collection"] = collection
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
                if nats_size > 0 and nats_completed >= nats_size and nats_scheduled >= nats_size:
                    loop_event_id = f"loop_{state.last_event_id or get_snowflake_id()}"
                    state.init_loop(
                        step.step,
                        collection,
                        step.loop.iterator,
                        step.loop.mode,
                        event_id=loop_event_id,
                    )
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

            completed_count_local = len(loop_state.get("results", []))
            completed_count = completed_count_local
            if nats_loop_state:
                completed_count = int(nats_loop_state.get("completed_count", completed_count_local) or completed_count_local)

            max_in_flight = self._get_loop_max_in_flight(step)

            # Ensure distributed loop metadata exists before claiming next slot.
            if not nats_loop_state:
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
                in_flight = max(0, scheduled_hint - completed_count)
                logger.info(
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
                logger.info(
                    "[LOOP] Claimed index %s is out of range for %s (size=%s)",
                    claimed_index,
                    step.step,
                    len(collection),
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

        # Build args separately - for step inputs
        step_args = {}
        if step.args:
            step_args.update(step.args)

        # Merge transition args
        filtered_args = {
            k: v for k, v in args.items()
            if k not in {"__loop_retry", "__loop_retry_index", "__loop_continue"}
        }
        step_args.update(filtered_args)

        # Render Jinja2 templates in args
        rendered_args = recursive_render(self.jinja_env, step_args, context)

        # Check if step.tool is a pipeline (list of labeled tasks) or single tool
        pipeline = None
        if isinstance(step.tool, list):
            # Pipeline: list of labeled tasks
            # Each item is {label: {kind: ..., args: ..., eval: ...}}
            # IMPORTANT: Do NOT pre-render pipeline templates here!
            # Task sequences may have templates that depend on variables set by earlier tasks
            # (e.g., set_ctx from policy rules). The worker's task_sequence_executor
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
            args=rendered_args,
            render_context=context,
            pipeline=pipeline,
            next_targets=next_targets,
            spec=command_spec,
            attempt=1,
            priority=0,
            metadata=command_metadata,
        )

        return command

    # NOTE: _process_vars_block REMOVED in strict v10 - use task.spec.policy.rules set_ctx

    async def handle_event(self, event: Event, already_persisted: bool = False) -> list[Command]:
        """
        Handle an event and return commands to enqueue.
        
        This is the core engine method called by the API.
        
        Args:
            event: The event to process
            already_persisted: If True, skip persisting the event (it was already persisted by caller)
        """
        logger.info(f"[ENGINE] handle_event called: event.name={event.name}, step={event.step}, execution={event.execution_id}, already_persisted={already_persisted}")
        commands: list[Command] = []
        
        # Load execution state (from memory cache or reconstruct from events)
        state = await self.state_store.load_state(event.execution_id)
        if not state:
            logger.error(f"Execution state not found: {event.execution_id}")
            return commands
        
        # Get current step
        if not event.step:
            logger.error("Event missing step name")
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
            response_data = event.payload.get("response", event.payload)
            payload_loop_event_id = (
                event.payload.get("loop_event_id")
                if isinstance(event.payload, dict)
                else None
            )
            if not payload_loop_event_id and isinstance(response_data, dict):
                payload_loop_event_id = response_data.get("loop_event_id")

            # Extract ctx variables from task sequence result and merge into execution state
            # This syncs set_ctx mutations from task policy rules back to the server
            task_ctx = response_data.get("ctx", {})
            if task_ctx and isinstance(task_ctx, dict):
                for key, value in task_ctx.items():
                    state.variables[key] = value
                    logger.debug(f"[TASK_SEQ] Synced ctx variable '{key}' from task sequence to execution state")

            # Get parent step definition for loop handling
            parent_step_def = state.get_step(parent_step)

            # Process step-level set_ctx for task sequence steps
            # This must happen BEFORE next transitions are evaluated so updated variables are available
            if parent_step_def and parent_step_def.set_ctx:
                # Get render context with the task sequence result available
                context = state.get_render_context(event)
                logger.debug(
                    "[SET_CTX] Processing step-level set_ctx for task sequence %s: keys=%s",
                    parent_step,
                    list(parent_step_def.set_ctx.keys()),
                )
                for key, value_template in parent_step_def.set_ctx.items():
                    try:
                        if isinstance(value_template, str) and "{{" in value_template:
                            rendered_value = self._render_template(value_template, context)
                        else:
                            rendered_value = value_template
                        state.variables[key] = rendered_value
                        logger.debug("[SET_CTX] Set %s (type=%s)", key, type(rendered_value).__name__)
                    except Exception as e:
                        logger.error(f"[SET_CTX] Failed to render {key}: {e}")

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
                        event_id_candidates = []
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

                        if new_count < 0:
                            # Keep progress moving even if distributed cache increments fail.
                            # Prefer durable count from persisted call.done events over local in-memory counts.
                            new_count = len(loop_state.get("results", []))
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
                            logger.info(
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
                            loop_state["collection"] = rendered_collection
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
                                    "result": loop_aggregation
                                }
                            )
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
                # Not in loop - store task sequence result under the parent step name
                # For single-task sequences (e.g., single tool with policy rules), unwrap the result
                # to maintain backward compatibility with templates like {{ step.data }}
                results = response_data.get("results", {})
                if len(results) == 1:
                    # Single task - merge its result at top level for backward compatibility
                    single_task_result = list(results.values())[0]
                    if isinstance(single_task_result, dict):
                        # Merge single task result at top level while preserving original structure
                        unwrapped_data = {**single_task_result, **response_data}
                        state.mark_step_completed(parent_step, unwrapped_data)
                        logger.info(f"[TASK_SEQ] Stored unwrapped single-task result for parent step '{parent_step}'")
                    else:
                        state.mark_step_completed(parent_step, response_data)
                        logger.info(f"[TASK_SEQ] Stored task sequence result for parent step '{parent_step}'")
                else:
                    state.mark_step_completed(parent_step, response_data)
                    logger.info(f"[TASK_SEQ] Stored task sequence result for parent step '{parent_step}'")

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
        worker_eval_action = event.payload.get("eval_action")
        has_worker_retry = worker_eval_action and worker_eval_action.get("type") == "retry"

        # CRITICAL: Store call.done/call.error response in state BEFORE evaluating next transitions
        # This ensures the result is available in render context for subsequent steps
        # Worker sends response directly as payload (not wrapped in "response" key)
        if event.name == "call.done":
            response_data = event.payload.get("response", event.payload)
            state.mark_step_completed(event.step, response_data)
            logger.debug(f"[CALL.DONE] Stored response for step {event.step} in state BEFORE next evaluation")
        elif event.name == "call.error":
            # Mark step as completed even on error - it finished executing (with failure)
            error_data = event.payload.get("error", event.payload)
            state.completed_steps.add(event.step)
            # CRITICAL: Track that execution has failures for final status determination
            state.failed = True
            logger.debug(f"[CALL.ERROR] Marked step {event.step} as completed (with error), execution marked as failed")

        # Get render context AFTER storing call.done response
        context = state.get_render_context(event)

        # Process step-level set_ctx BEFORE evaluating next transitions
        # This ensures variables set by set_ctx are available in routing conditions
        if event.name == "call.done" and step_def.set_ctx:
            logger.debug(
                "[SET_CTX] Processing step-level set_ctx for %s: keys=%s",
                event.step,
                list(step_def.set_ctx.keys()),
            )
            for key, value_template in step_def.set_ctx.items():
                try:
                    # Render the value template with current context (including step result)
                    if isinstance(value_template, str) and "{{" in value_template:
                        rendered_value = self._render_template(value_template, context)
                    else:
                        rendered_value = value_template
                    state.variables[key] = rendered_value
                    logger.debug("[SET_CTX] Set %s (type=%s)", key, type(rendered_value).__name__)
                except Exception as e:
                    logger.error(f"[SET_CTX] Failed to render {key}: {e}")
            # Refresh context after set_ctx to include new variables
            context = state.get_render_context(event)

        # Evaluate next[].when transitions ONCE and store results
        # This allows us to detect retries before deciding whether to aggregate results
        # IMPORTANT: Only process on call.done/call.error to avoid duplicate command generation
        # step.exit should NOT trigger next evaluation because the worker already emits call.done
        # which triggers next evaluation and generates transition commands
        # CRITICAL: For loop steps, skip next evaluation on call.done - the next transition
        # will be evaluated on loop.done event after all iterations complete. This prevents
        # fan-out where each loop iteration triggers the next step independently.
        next_commands = []
        is_loop_step = step_def.loop is not None and event.step in state.loop_state
        if event.name in ("call.done", "call.error") and not is_loop_step:
            next_commands = await self._evaluate_next_transitions(state, step_def, event)
            
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
                    "[LOOP_DEBUG] Loop state: completed=%s finalized=%s results_count=%s",
                    loop_state.get("completed"),
                    loop_state.get("aggregation_finalized"),
                    len(loop_state.get("results", [])),
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
                    state.mark_step_completed(event.step, event.payload["result"])
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
                # _process_then_actions expects next items to be step names or {step: name, args: {...}}
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
                        completed_count = len(loop_state.get("results", []))
                        logger.debug(f"[LOOP-LOCAL] Got count from local cache: {completed_count}")
                    else:
                        completed_count = 0
                    
                    # Only render collection if not already cached (expensive operation)
                    if loop_state and not loop_state.get("collection"):
                        context = state.get_render_context(event)
                        collection = self._render_template(step_def.loop.in_, context)
                        collection = self._normalize_loop_collection(collection, event.step)
                        loop_state["collection"] = collection
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
                                "result": loop_aggregation  # Include aggregated result in payload
                            }
                        )
                        loop_done_commands = await self._evaluate_next_transitions(state, step_def, loop_done_event)
                        commands.extend(loop_done_commands)

        # NOTE: step.vars is REMOVED in strict v10 - use task.spec.policy.rules set_ctx

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
        # Completion triggers when step.exit occurs with no commands generated AND step has no routing
        # This handles explicit terminal steps (no next blocks) only
        # OR when a step fails with no error handler (no commands generated despite having routing)
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
        # 1. step.exit event
        # 2. No commands generated
        # 3. EITHER: Step has NO next (true terminal step)
        #    OR: Step failed with no error handling (has error but no commands)
        # 4. Not already completed
        is_terminal_step = step_def and not step_def.next
        is_failed_with_no_handler = has_error and not commands

        # Check for pending commands using multiple methods:
        # 1. In-memory state tracking (issued_steps vs completed_steps)
        # 2. Database query as backup (only if in-memory state is uncertain)
        # This prevents premature completion when next transitions trigger on call.done but step.exit has no matching next
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
            for issued_step in state.issued_steps:
                pending_key = _pending_step_key(issued_step)
                if pending_key and pending_key not in state.completed_steps:
                    issued_not_completed.add(pending_key)
        if issued_not_completed:
            has_pending_commands = True
            logger.debug(
                "[COMPLETION] execution=%s pending_in_memory=%s",
                event.execution_id,
                len(issued_not_completed),
            )
        elif not hasattr(state, 'issued_steps') or not state.issued_steps:
            # Only fall back to database query if in-memory state might be stale (e.g., after restart)
            # IMPORTANT: Use step.exit instead of command.completed because command.completed is emitted
            # AFTER step.exit, so terminal step's command.completed won't exist when this check runs
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
                              AND event_type = 'step.exit'
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
        # (DB check would cause false positives due to command.completed timing)

        if event.name == "step.exit" and not commands and not has_pending_commands and (is_terminal_step or is_failed_with_no_handler) and not state.completed:
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
            # This ensures proper ordering: step.exit -> workflow_completion -> playbook_completion
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
        """Persist event to database."""
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
                # Generate event_id
                event_id = await get_snowflake_id()
                
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
                
                # Merge with existing context metadata
                context_data = event.payload.get("context", {})
                if isinstance(context_data, dict):
                    # CRITICAL: Convert all IDs to strings to prevent JavaScript precision loss with Snowflake IDs
                    context_data["execution_id"] = str(event.execution_id)
                    context_data["catalog_id"] = str(catalog_id) if catalog_id else None
                    context_data["root_event_id"] = str(state.root_event_id) if state.root_event_id else None
                
                # Determine status: Use payload status if provided, otherwise infer from event name
                payload_status = event.payload.get("status")
                if payload_status:
                    # Worker explicitly set status - use it (handles errors properly)
                    status = payload_status.upper() if isinstance(payload_status, str) else str(payload_status).upper()
                else:
                    # Fallback to event name-based status for events without explicit status
                    status = "FAILED" if "failed" in event.name else "COMPLETED" if ("step.exit" == event.name or "completed" in event.name) else "RUNNING"
                
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
                    Json(event.payload.get("result")) if event.payload.get("result") else None,
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
