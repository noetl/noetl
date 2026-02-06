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
        
        # Initialize workload variables
        if playbook.workload:
            self.variables.update(playbook.workload)
        
        # Merge payload into ctx (canonical v10: use ctx for execution-scoped variables)
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
        logger.info(f"[STATE-INIT] Final state: execution_id={execution_id}, variables_count={len(self.variables)}, variable_keys={list(self.variables.keys())[:10]}")

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
        
        self.loop_state[step_name]["results"].append(result)
        if failed:
            self.loop_state[step_name]["failed_count"] += 1
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
        # Log workload variables for debugging state reconstruction issues
        workload_vars = {k: v for k, v in self.variables.items() if not isinstance(v, dict) or 'status' not in v}
        logger.info(f"ENGINE: get_render_context called, catalog_id={self.catalog_id}, execution_id={self.execution_id}, variables_count={len(self.variables)}, workload_sample={list(workload_vars.items())[:5]}")
        
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
            # NOTE: Legacy 'workload' and 'vars' aliases REMOVED in strict v10
            "ctx": self.variables,  # Execution-scoped variables (canonical v10)
            "iter": iter_vars,      # Iteration-scoped variables (canonical v10)
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
            logger.info(f"[STATE-CACHE-HIT] Execution {execution_id}: found in cache, issued_steps={cached.issued_steps}, completed_steps={cached.completed_steps}")
            return cached
        logger.info(f"[STATE-CACHE-MISS] Execution {execution_id}: not in cache, reconstructing from events")
        
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
                logger.info(f"[STATE-LOAD] playbook.initialized query result: type={type(result)}, is_none={result is None}")
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
                logger.info(f"[STATE-LOAD] Raw event_result type: {type(event_result)}, truthy: {bool(event_result)}, is_dict: {isinstance(event_result, dict) if event_result else 'N/A'}")
                if event_result and isinstance(event_result, dict):
                    workload = event_result.get("workload", {})
                    logger.info(f"[STATE-LOAD] Restored workload from playbook.initialized event: keys={list(workload.keys()) if workload else 'empty'}")
                    if not workload:
                        logger.warning(f"[STATE-LOAD] Workload is empty! event_result keys: {list(event_result.keys())}, full event_result: {event_result}")
                else:
                    logger.warning(f"[STATE-LOAD] Could not extract workload from event_result - raw value: {str(event_result)[:500] if event_result else 'None'}")
                
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
                    SELECT node_name, event_type, result
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id
                """, (int(execution_id),))
                
                rows = await cur.fetchall()
                
                # Track loop iteration results during event replay
                loop_iteration_results = {}  # {step_name: [result1, result2, ...]}
                
                for row in rows:
                    if isinstance(row, dict):
                        node_name = row.get("node_name")
                        event_type = row.get("event_type")
                        result_data = row.get("result")
                    else:
                        node_name = row[0]
                        event_type = row[1]
                        result_data = row[2]

                    # Track issued commands for pending detection (race condition fix)
                    if event_type == 'command.issued':
                        state.issued_steps.add(node_name)
                        logger.debug(f"[STATE-LOAD] Reconstructed issued_step: {node_name}")
                    elif event_type == 'command.completed':
                        state.issued_steps.discard(node_name)
                        logger.debug(f"[STATE-LOAD] Removed completed command from issued_steps: {node_name}")

                    # For loop steps, collect iteration results from step.exit events
                    if event_type == 'step.exit' and result_data and node_name in loop_steps:
                        if node_name not in loop_iteration_results:
                            loop_iteration_results[node_name] = []
                        loop_iteration_results[node_name].append(result_data)

                    # Restore step results from step.exit events (final result only)
                    if event_type == 'step.exit' and result_data:
                        state.mark_step_completed(node_name, result_data)
                
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
                            "aggregation_finalized": False
                        }
                        logger.info(f"[STATE-LOAD] Initialized loop_state for {step_name}: index={iteration_count} (from {iteration_count} completed iterations)")
                    else:
                        # Restore collected results and update index
                        state.loop_state[step_name]["results"] = loop_iteration_results.get(step_name, [])
                        state.loop_state[step_name]["index"] = iteration_count
                        logger.info(f"[STATE-LOAD] Updated loop_state for {step_name}: index={iteration_count}")
                
                # Log reconstructed state for debugging
                if state.issued_steps:
                    logger.info(f"[STATE-LOAD] Reconstructed {len(state.issued_steps)} pending commands (issued_steps): {state.issued_steps}")
                logger.info(f"[STATE-LOAD] Execution {execution_id}: completed_steps={len(state.completed_steps)}, issued_steps={len(state.issued_steps)}")

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
            logger.error(f"Template rendering error: {e} | Template: {template_str} | Context keys: {list(context.keys())}")
            raise
    
    def _evaluate_condition(self, when_expr: str, context: dict[str, Any]) -> bool:
        """Evaluate when condition."""
        try:
            # Render the condition
            result = self._render_template(when_expr, context)
            
            # Convert to boolean
            if isinstance(result, bool):
                logger.info(f"[COND] Evaluated '{when_expr}' => {result}")
                return result
            if isinstance(result, str):
                # Check for explicit false values, otherwise treat non-empty strings as truthy
                is_false = result.lower() in ("false", "0", "no", "none", "")
                is_true = not is_false
                logger.info(f"[COND] Evaluated '{when_expr}' => '{result}' => {is_true}")
                return is_true
            bool_result = bool(result)
            logger.info(f"[COND] Evaluated '{when_expr}' => {result} (type={type(result)}) => {bool_result}")
            return bool_result
        except Exception as e:
            logger.error(f"Condition evaluation error: {e} | Condition: {when_expr}")
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

            # Create command for target step
            command = await self._create_command_for_step(state, target_step_def, rendered_args)
            if command:
                commands.append(command)
                # CRITICAL: Mark step as issued immediately to prevent duplicate commands
                # from parallel event processing
                state.issued_steps.add(target_step)
                logger.info(f"[NEXT-MATCH] Created command for step {target_step}, added to issued_steps")

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
                    command = await self._create_command_for_step(
                        state, step_def, args
                    )
                    if command:
                        commands.append(command)
            
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
                command = await self._create_command_for_step(state, step_def, updated_args)

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
                
                logger.info(f"[RETRY-ACTION] Creating retry command with args: {retry_args}")
                
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
                        f"[RETRY-ACTION] Re-attempting step {event.step} with args {retry_args} "
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
                command = await self._create_command_for_step(state, step_def, args)
                if command:
                    commands.append(command)
                    logger.info(f"[DEFERRED-NEXT] Created command for step: {target_step}")

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
        # Check if step has loop configuration
        if step.loop:
            logger.debug(f"[CREATE-CMD] Step {step.step} has loop: in={step.loop.in_}, iterator={step.loop.iterator}, mode={step.loop.mode}")
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
            
            if not isinstance(collection, list):
                logger.warning(f"Loop collection is not a list: {type(collection)}, converting")
                collection = list(collection) if hasattr(collection, '__iter__') else [collection]
            
            # Get completed count from NATS K/V (authoritative) or local fallback
            # Use last event_id for this step as the loop instance identifier
            # If no event_id yet (first time), use execution_id as fallback
            loop_event_id = state.step_event_ids.get(step.step)
            if loop_event_id is None:
                # For new loops, use execution_id as identifier until first event is created
                loop_event_id = f"exec_{state.execution_id}"
                logger.debug(f"[LOOP-INIT] No event_id yet for {step.step}, using execution fallback: {loop_event_id}")
            
            nats_cache = await get_nats_cache()
            nats_loop_state = await nats_cache.get_loop_state(
                str(state.execution_id),
                step.step,
                event_id=str(loop_event_id)
            )
            
            # Use NATS count if available (authoritative for distributed execution)
            if nats_loop_state:
                # Use completed_count field (not results array - results are stored in event table)
                completed_count = nats_loop_state.get("completed_count", 0)
                logger.debug(f"[LOOP-NATS] Got completed count from NATS K/V: {completed_count}")
            else:
                # Initialize loop state if not present (first iteration)
                if step.step not in state.loop_state:
                    state.init_loop(step.step, collection, step.loop.iterator, step.loop.mode, event_id=loop_event_id)
                    logger.info(f"Initialized loop for {step.step} with {len(collection)} items, event_id={loop_event_id}")
                    
                    # Store initial state in NATS K/V with event_id for instance uniqueness
                    # NOTE: We store only metadata and completed_count, NOT results array
                    # Results are stored in event table and fetched via aggregate service
                    await nats_cache.set_loop_state(
                        str(state.execution_id),
                        step.step,
                        {
                            "collection_size": len(collection),
                            "completed_count": 0,  # Count only, not results array
                            "iterator": step.loop.iterator,
                            "mode": step.loop.mode,
                            "event_id": loop_event_id
                        },
                        event_id=str(loop_event_id)
                    )
                
                loop_state = state.loop_state[step.step]
                completed_count = len(loop_state.get("results", []))
                logger.debug(f"[LOOP-LOCAL] Got completed count from local cache: {completed_count}")
            
            logger.info(f"[LOOP] Step {step.step}: {completed_count}/{len(collection)} iterations completed")
            
            # Check if we have more items to process
            if completed_count >= len(collection):
                # Loop completed
                logger.info(f"[LOOP] Loop completed for {step.step}: {completed_count}/{len(collection)} iterations")
                return None  # No command, will generate loop.done event
            
            # Get next item by index (stateless - just use completed_count as index)
            item = collection[completed_count]
            logger.info(f"[LOOP] Creating command for loop iteration {completed_count} of step {step.step}, item={item}")
            
            # Add loop variables to state for Jinja2 template rendering
            state.variables[step.loop.iterator] = item
            state.variables["loop_index"] = completed_count
            logger.info(f"[LOOP] Added to state.variables: {step.loop.iterator}={item}, loop_index={completed_count}")
        
        # Get render context for Jinja2 templates
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
            logger.error(f"DEBUG verify_result: step_results={list(state.step_results.keys())} | variables={list(state.variables.keys())} | run_python_from_gcs={gcs_result}")

        # Debug: Log loop variables in context
        if step.loop:
            logger.warning(f"[LOOP-DEBUG] Step {step.step}: context_keys={list(context.keys())} | iterator='{step.loop.iterator}'={context.get(step.loop.iterator, 'NOT_FOUND')} | loop_index={context.get('loop_index', 'NOT_FOUND')} | state.variables={state.variables}")

        # Build args separately - for step inputs
        step_args = {}
        if step.args:
            step_args.update(step.args)

        # Merge transition args
        step_args.update(args)

        # Render Jinja2 templates in args
        rendered_args = recursive_render(self.jinja_env, step_args, context)

        # Check if step.tool is a pipeline (list of labeled tasks) or single tool
        pipeline = None
        if isinstance(step.tool, list):
            # Pipeline: list of labeled tasks
            # Each item is {label: {kind: ..., args: ..., eval: ...}}
            pipeline = recursive_render(self.jinja_env, step.tool, context)
            logger.info(f"[PIPELINE] Step '{step.step}' has pipeline with {len(pipeline)} tasks")

            # For pipeline steps, use task_sequence as tool kind
            tool_kind = "task_sequence"
            tool_config = {"tasks": pipeline}  # Worker expects "tasks" key
        else:
            # Single tool (shorthand)
            tool_dict = step.tool.model_dump()
            tool_config = {k: v for k, v in tool_dict.items() if k != "kind"}
            tool_kind = step.tool.kind

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

        command = Command(
            execution_id=state.execution_id,
            step=step.step,
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
            priority=0
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
                        state.issued_steps.add(cmd.step)
                        logger.info(f"[ISSUED] Added deferred {cmd.step} to issued_steps for execution {state.execution_id}")
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

            # Store task sequence result under the parent step name
            state.mark_step_completed(parent_step, response_data)
            logger.info(f"[TASK_SEQ] Stored task sequence result for parent step '{parent_step}'")

            # Process remaining actions from task sequence result (next, etc.)
            remaining_actions = response_data.get("remaining_actions", [])
            if remaining_actions:
                logger.info(f"[TASK_SEQ] Processing remaining actions: {remaining_actions}")
                seq_commands = await self._process_then_actions(
                    remaining_actions, state, event
                )
                commands.extend(seq_commands)
                logger.info(f"[TASK_SEQ] Generated {len(seq_commands)} commands from remaining actions")

            return commands

        step_def = state.get_step(event.step)
        if not step_def:
            logger.error(f"Step not found: {event.step}")
            return commands
        
        # Update current step
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

        # Evaluate next[].when transitions ONCE and store results
        # This allows us to detect retries before deciding whether to aggregate results
        # IMPORTANT: Only process on call.done/call.error to avoid duplicate command generation
        # step.exit should NOT trigger next evaluation because the worker already emits call.done
        # which triggers next evaluation and generates transition commands
        next_commands = []
        if event.name in ("call.done", "call.error"):
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
        logger.info(f"[LOOP_DEBUG] Checking step.exit: name={event.name}, has_result={'result' in event.payload}, payload_keys={list(event.payload.keys())}")
        if event.name == "step.exit" and "result" in event.payload:
            logger.info(f"[LOOP_DEBUG] step.exit with result for {event.step}, step_def.loop={step_def.loop}, in_loop_state={event.step in state.loop_state}")
            
            # Use the is_retrying flag we just determined
            if is_retrying:
                logger.info(f"[LOOP_DEBUG] Pagination retry active for {event.step}; skipping result aggregation and loop advance")
            
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
                logger.info(f"[LOOP_DEBUG] Loop state: completed={loop_state.get('completed')}, finalized={loop_state.get('aggregation_finalized')}, results_count={len(loop_state.get('results', []))}")
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

            logger.info(f"[ENGINE] Server matched no rules, but worker reported '{action_type}' action. Processing worker action. config={action_config}")

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
        logger.info(f"[LOOP-DEBUG] Checking step.exit: step={event.step}, event.name={event.name}, has_loop={step_def.loop is not None}")
        if step_def.loop and event.name == "step.exit":
            logger.info(f"[LOOP-DEBUG] Entering loop completion check for {event.step}")
            pagination_retry_pending = state.pagination_state.get(event.step, {}).get("pending_retry", False)
            if pagination_retry_pending:
                logger.info(f"[LOOP_DEBUG] Pagination retry pending for {event.step}; skipping loop completion/next iteration")
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
                        if not isinstance(collection, list):
                            collection = list(collection) if hasattr(collection, '__iter__') else [collection]
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
                                "completed_count": 0,  # Count only, not results array
                                "iterator": loop_state.get("iterator"),
                                "mode": loop_state.get("mode"),
                                "event_id": loop_event_id
                            },
                            event_id=str(loop_event_id) if loop_event_id else None
                        )
                    
                    collection_size = len(loop_state["collection"]) if loop_state else (nats_loop_state.get("collection_size", 0) if nats_loop_state else 0)
                    logger.info(f"[LOOP-CHECK] Step {event.step}: {completed_count}/{collection_size} iterations completed")
                    
                    if completed_count < collection_size:
                        # More items to process - create next iteration command if not already created
                        if not any(cmd.step == event.step for cmd in commands):
                            logger.info(f"[LOOP] Creating next iteration command for {event.step}")
                            command = await self._create_command_for_step(state, step_def, {})
                            if command:
                                commands.append(command)
                            else:
                                logger.error(f"[LOOP] Failed to create command for next iteration of {event.step}")
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

                logger.info(f"[STRUCTURAL-NEXT] No next matched for step.exit, using structural next: {step_def.next}, mode={next_mode}")
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
                        command = await self._create_command_for_step(state, next_step_def, {})
                        if command:
                            commands.append(command)
                            logger.info(f"[STRUCTURAL-NEXT] Created command for step {target_step}")

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
        logger.info(f"COMPLETION CHECK: event={event.name}, step={event.step}, commands={len(commands)}, completed={state.completed}, has_next={bool(step_def.next if step_def else False)}, has_error={bool(event.payload.get('error'))}")

        # Check if step failed
        has_error = event.payload.get("error") is not None

        # Only trigger completion if:
        # 1. step.exit event
        # 2. No commands generated
        # 3. EITHER: Step has NO next (true terminal step)
        #    OR: Step failed with no error handling (has error but no commands)
        #    OR: Step has routing (next) but none matched/generated commands (effective terminal)
        # 4. Not already completed
        is_terminal_step = step_def and not step_def.next
        is_failed_with_no_handler = has_error and not commands

        # EFFECTIVE TERMINAL: Step has routing but no commands were generated
        # (e.g. all next[].when conditions failed, or structural next was skipped)
        is_effective_terminal = step_def and not commands and not state.completed

        # Check for pending commands using multiple methods:
        # 1. In-memory state tracking (issued_steps vs completed_steps)
        # 2. Database query as backup (only if in-memory state is uncertain)
        # This prevents premature completion when next transitions trigger on call.done but step.exit has no matching next
        has_pending_commands = False

        # Debug: log current state before pending check
        logger.info(f"[PENDING-CHECK] Execution {event.execution_id}: issued_steps={state.issued_steps if hasattr(state, 'issued_steps') else 'N/A'}, completed_steps={state.completed_steps}")

        # First check in-memory: issued_steps that aren't in completed_steps
        issued_not_completed = state.issued_steps - state.completed_steps if hasattr(state, 'issued_steps') else set()
        if issued_not_completed:
            has_pending_commands = True
            logger.info(f"[COMPLETION] Execution {event.execution_id} has {len(issued_not_completed)} pending commands in memory: {issued_not_completed}")
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
                        logger.info(f"[COMPLETION] Execution {event.execution_id} has {pending_count} pending commands in DB")
        # If in-memory state shows no pending AND issued_steps is populated, trust it
        # (DB check would cause false positives due to command.completed timing)

        if event.name == "step.exit" and not commands and not has_pending_commands and (is_terminal_step or is_failed_with_no_handler or is_effective_terminal) and not state.completed:
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
            if event.name == "command.failed":
                state.failed = True  # Track failure for final status
                logger.error(f"[FAILURE] Received command.failed event for step {event.step}, stopping execution")
                return []  # Return empty commands list to stop workflow

            if event.name == "step.exit":
                step_status = event.payload.get("status", "").upper()
                if step_status == "FAILED":
                    state.failed = True  # Track failure for final status
                    logger.error(f"[FAILURE] Step {event.step} failed, stopping execution")
                    return []  # Return empty commands list to stop workflow

        # Track issued steps for pending commands detection
        for cmd in commands:
            state.issued_steps.add(cmd.step)
            logger.info(f"[ISSUED] Added {cmd.step} to issued_steps for execution {state.execution_id}, total issued={len(state.issued_steps)}")

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
        
        if event.name == "step.exit" and event.step:
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

        logger.info(f"[PLAYBOOK-INIT] Workload snapshot keys: {list(workload_snapshot.keys())}, sample values: {list(workload_snapshot.items())[:5]}")

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
        
        # Create initial command for start step
        start_command = await self._create_command_for_step(state, start_step, payload)
        
        commands = [start_command] if start_command else []
        
        return execution_id, commands
