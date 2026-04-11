from __future__ import annotations

from .common import *
from .state import ExecutionState

class PlaybookRepo:
    """Repository for loading playbooks from catalog with bounded cache."""

    def __init__(self):
        # Bounded cache: max 500 playbooks, 30 min TTL
        self._cache: BoundedCache[Playbook] = BoundedCache(
            max_size=500,
            ttl_seconds=1800
        )

    def register(self, playbook: Playbook, key: str):
        """Register a playbook in the local cache for tests and local orchestration."""
        self._cache.set_sync(key, playbook)
        path = playbook.metadata.get("path") if isinstance(playbook.metadata, dict) else None
        if isinstance(path, str) and path:
            self._cache.set_sync(path, playbook)

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
                            loop_step = (
                                node_name.replace(":task_sequence", "")
                                if isinstance(node_name, str)
                                else node_name
                            )
                            loop_event_id = meta_data.get("loop_event_id")
                            # Only reset the epoch state if we are actually crossing into a NEW epoch
                            # (i.e. the loop_event_id has changed from the one we were previously tracking).
                            # Otherwise, we would falsely wipe the array on every single iteration's command.issued!
                            if loop_event_id and str(loop_event_id) != loop_event_ids.get(loop_step):
                                if loop_step in loop_iteration_state:
                                    loop_iteration_state[loop_step].pop("completed", None)
                                    loop_iteration_state[loop_step].pop("aggregation_finalized", None)
                                    loop_iteration_state[loop_step]["results"] = []
                                    loop_iteration_state[loop_step]["omitted_results_count"] = 0
                                    loop_iteration_state[loop_step]["scheduled_count"] = 0
                                    loop_iteration_state[loop_step]["failed_count"] = 0
                                    loop_iteration_state[loop_step]["index"] = 0
                                    state.completed_steps.discard(loop_step)
                                    state.step_results.pop(loop_step, None)
                            if loop_event_id:
                                if loop_step not in loop_iteration_state:
                                    loop_iteration_state[loop_step] = {
                                        "results": [],
                                        "failed_count": 0,
                                        "break_count": 0,
                                        "scheduled_count": 0,
                                        "omitted_results_count": 0,
                                        "completed": False,
                                        "aggregation_finalized": False
                                    }
                                loop_iteration_state[loop_step]["event_id"] = str(loop_event_id)
                                loop_event_ids[loop_step] = str(loop_event_id)
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
                                # Protect against late call.done events from previous epochs
                                # overwriting the active epoch ID (which corrupts the loop state).
                                existing_id = loop_event_ids.get(loop_step_name)
                                if not existing_id or str(loop_event_id) >= existing_id:
                                    loop_event_ids[loop_step_name] = str(loop_event_id)

                    # Restore non-loop step results from call.done events.
                    #
                    # Cross-pod routing happens on call.done, not step.exit. When another
                    # server reconstructs state from persisted events, it must be able to
                    # render follow-up loop inputs like {{ claim_step.rows }} immediately
                    # from the call.done result, even if step.exit has not been persisted
                    # yet for that command.
                    if event_type == 'call.done' and event_payload:
                        if not node_name.endswith(":task_sequence") and node_name not in loop_steps:
                            step_result = (
                                event_payload.get("result", event_payload)
                                if isinstance(event_payload, dict)
                                else event_payload
                            )
                            step_result = await _hydrate_reference_only_step_result(step_result)
                            state.mark_step_completed(node_name, step_result)

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

