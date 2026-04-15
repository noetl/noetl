from __future__ import annotations

from .common import *
from .state import ExecutionState
from .store import PlaybookRepo, StateStore

class CommandCreationMixin:
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
        loop_event_id_for_metadata: Optional[str] = control_args.get("__loop_epoch_id")
        claimed_index: Optional[int] = control_args.get("__loop_claimed_index")
        _nats_slot_incremented = claimed_index is not None  # tracks whether a NATS scheduled_count was incremented
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
            reuse_cached_collection = False # FORCE NEW EPOCHS FOR EVERY BATCH
            _unused = (
                existing_loop_state is not None
                and (loop_continue_requested or loop_retry_requested)
                and existing_loop_state.get("collection_size", 0) > 0
            )

            # Use passed collection if available (Optimization)
            collection = control_args.get("__loop_collection")
            
            if collection is None:
                # Distributed Loop Collection logic (Fallback)
                nats_cache = await get_nats_cache()
                loop_event_id = str(existing_loop_state.get("event_id") or "") if existing_loop_state else ""
                if loop_event_id:
                    collection = await nats_cache.get_loop_collection(str(state.execution_id), step.step, loop_event_id)

            if collection is None:
                # Final fallback: re-render
                context = state.get_render_context(Event(
                    execution_id=state.execution_id, step=step.step, name="loop_init", payload={}
                ))
                collection = self._render_template(step.loop.in_, context)
                collection = self._normalize_loop_collection(collection, step.step)

                # Guard: if the collection is empty after re-rendering on a loop continuation
                # or retry, the state reconstruction is incomplete (e.g., a reference-only
                # step result could not be hydrated from NATS after a cache miss).  Skip
                # dispatch entirely so we never call claim_next_loop_index and leak a slot.
                if len(collection or []) == 0 and (loop_continue_requested or loop_retry_requested):
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
                import time
                loop_event_id = loop_event_id_for_metadata or f"loop_{state.execution_id}_{int(time.time() * 1000000)}"
                state.init_loop(
                    step.step,
                    collection,
                    step.loop.iterator,
                    step.loop.mode,
                    event_id=loop_event_id,
                )
                # Save collection to NATS KV immediately after initialization
                await (await get_nats_cache()).save_loop_collection(str(state.execution_id), step.step, loop_event_id, collection)

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
                previous_size = existing_loop_state.get("collection_size", 0)
                
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
                        len(collection or []),
                        loop_event_id,
                    )
                else:
                    existing_loop_state["collection_size"] = len(collection or []) if hasattr(collection, "__len__") else 0
            loop_state = existing_loop_state
            # Preserving the passed epoch ID from transitions.py!
            loop_event_id_for_metadata = loop_event_id_for_metadata or (
                str(loop_state.get("event_id"))
                if loop_state.get("event_id") is not None
                else None
            )

            # Resolve distributed loop key candidates.
            if force_new_loop_instance:
                loop_event_id_for_metadata = loop_event_id_for_metadata or loop_state.get("event_id")
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
                    loop_event_id_for_metadata = candidate_event_id
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
                nats_size = int(nats_loop_state.get("collection_size", len(collection or [])) or len(collection or []))
                nats_loop_done_claimed = bool(nats_loop_state.get("loop_done_claimed", False))
                if (nats_size > 0 and nats_completed >= nats_size and nats_scheduled >= nats_size) or nats_loop_done_claimed:
                    # Let transitions.py handle the epoch ID!
                    loop_event_id = loop_event_id_for_metadata or f"loop_{state.last_event_id or time.time_ns()}"
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
                    loop_event_id_for_metadata = loop_event_id
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
            if nats_loop_state and len(collection or []) > 0:
                nats_collection_size = int(nats_loop_state.get("collection_size", 0) or 0)
                if nats_collection_size <= 0:
                    repaired_scheduled = int(
                        nats_loop_state.get("scheduled_count", completed_count) or completed_count
                    )
                    if repaired_scheduled < completed_count:
                        repaired_scheduled = completed_count
                    nats_loop_state["collection_size"] = len(collection or [])
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
                        len(collection or []),
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
                        "collection_size": len(collection or []),
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
                    if claimed_index is None: claimed_index = await nats_cache.claim_next_loop_index(
                        str(state.execution_id),
                        step.step,
                        collection_size=len(collection or []),
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
                    if scheduled_count < len(collection or []) and (scheduled_count - completed_count) < max_in_flight:
                        # Disable local fallback for batch loops to prevent index 0 skipping!
                        pass

            if claimed_index is None:
                scheduled_hint = int(
                    (nats_loop_state or {}).get(
                        "scheduled_count",
                        loop_state.get("scheduled_count", completed_count),
                    )
                    or completed_count
                )
                collection_size_hint = int(
                    (nats_loop_state or {}).get("collection_size", len(collection or [])) or len(collection or [])
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
                    supervisor_completed = await self._count_supervised_loop_terminal_iterations(
                        state.execution_id,
                        step.step,
                        resolved_loop_event_id,
                    )
                    if supervisor_completed >= 0:
                        supervisor_completed = min(
                            supervisor_completed,
                            collection_size_hint,
                        )
                        if supervisor_completed > completed_count:
                            repaired_completed = supervisor_completed
                            repaired_scheduled = min(
                                max(
                                    int(
                                        (nats_loop_state or {}).get(
                                            "scheduled_count",
                                            scheduled_hint,
                                        )
                                        or scheduled_hint
                                    ),
                                    repaired_completed,
                                ),
                                collection_size_hint,
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
                            if claimed_index is None: claimed_index = await nats_cache.claim_next_loop_index(
                                str(state.execution_id),
                                step.step,
                                collection_size=len(collection or []),
                                max_in_flight=max_in_flight,
                                event_id=resolved_loop_event_id,
                            )
                            if claimed_index is not None:
                                _nats_slot_incremented = True
                                logger.warning(
                                    "[LOOP-COUNTER-RECONCILE] Recovered claim slot for %s "
                                    "(event_id=%s completed=%s scheduled=%s size=%s claimed=%s source=supervisor)",
                                    step.step,
                                    resolved_loop_event_id,
                                    completed_count,
                                    scheduled_hint,
                                    collection_size_hint,
                                    claimed_index,
                                )

                    if claimed_index is None and reconcile_cooldown_elapsed:
                        missing_indexes = await self._find_supervised_missing_loop_iteration_indices(
                            str(state.execution_id),
                            step.step,
                            loop_event_id=resolved_loop_event_id,
                            limit=1,
                        )
                        if missing_indexes is None:
                            missing_indexes = await self._find_missing_loop_iteration_indices(
                                str(state.execution_id),
                                step.step,
                                loop_event_id=resolved_loop_event_id,
                                limit=1,
                            )
                        if not missing_indexes:
                            epoch_completed = await self._count_loop_terminal_iterations(
                                state.execution_id,
                                step.step,
                                resolved_loop_event_id,
                            )
                            persisted_completed = epoch_completed
                            if persisted_completed < 0 and scheduled_hint >= collection_size_hint:
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
                                    repaired_scheduled = min(
                                        max(
                                            int(
                                                (nats_loop_state or {}).get(
                                                    "scheduled_count",
                                                    scheduled_hint,
                                                )
                                                or scheduled_hint
                                            ),
                                            repaired_completed,
                                        ),
                                        collection_size_hint,
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
                                    if claimed_index is None: claimed_index = await nats_cache.claim_next_loop_index(
                                        str(state.execution_id),
                                        step.step,
                                        collection_size=len(collection or []),
                                        max_in_flight=max_in_flight,
                                        event_id=resolved_loop_event_id,
                                    )
                                    if claimed_index is not None:
                                        _nats_slot_incremented = True
                                        logger.warning(
                                            "[LOOP-COUNTER-RECONCILE] Recovered claim slot for %s "
                                            "(event_id=%s completed=%s scheduled=%s size=%s claimed=%s source=events)",
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
                        orphaned_indexes = await self._find_supervised_orphaned_loop_iteration_indices(
                            str(state.execution_id),
                            step.step,
                            loop_event_id=resolved_loop_event_id,
                            limit=max(1, _TASKSEQ_LOOP_REPAIR_THRESHOLD),
                        )
                        if orphaned_indexes is None:
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
                        len(collection or []),
                        in_flight,
                        max_in_flight,
                    )
                    return None

            if claimed_index is None or claimed_index >= len(collection or []):
                logger.warning(
                    "[LOOP] Claimed index %s is out of range or None for %s (col_size=%s); %s",
                    claimed_index,
                    step.step,
                    len(collection or []),
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
            loop_state["scheduled_count"] = max(
                int(loop_state.get("scheduled_count", 0) or 0),
                claimed_index + 1,
            )
            loop_state["collection_size"] = len(collection or [])
            loop_state["index"] = max(int(loop_state.get("index", 0) or 0), claimed_index + 1)
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
        # PERFORMANCE OPTIMIZATION: Prefer passed-in base context to avoid O(N) rebuilds.
        optimized_context = control_args.get("__base_context")
        if step.loop and (optimized_context is not None or (locals().get('context') is not None)):
            # Create a shallow copy to avoid mutating the shared base context across parallel loop items
            base_context = optimized_context if optimized_context is not None else context
            # PERFORMANCE & CORRECTNESS: Shallow copy the top-level context, 
            # but MUST clone the nested 'iter' namespace to avoid parallel clobbering.
            context = dict(base_context)
            if "iter" in context and isinstance(context["iter"], dict):
                context["iter"] = dict(context["iter"])
            
            iterator_value = state.variables.get(step.loop.iterator)
            # Update both top-level and 'iter' namespace for canonical v10 compatibility
            context[step.loop.iterator] = iterator_value
            context["loop_index"] = claimed_index
            if "iter" in context and isinstance(context["iter"], dict):
                context["iter"][step.loop.iterator] = iterator_value
                context["iter"]["_index"] = claimed_index
            context["ctx"] = state.variables
            context["workload"] = state.variables
            # Update iter namespace so {{ iter.<iterator>.<field> }} works
            if "iter" not in context or not isinstance(context.get("iter"), dict):
                context["iter"] = {}
            context["iter"][step.loop.iterator] = iterator_value
            context["iter"]["_index"] = claimed_index
            coll_len = len(collection or [])
            context["iter"]["_first"] = claimed_index == 0
            context["iter"]["_last"] = claimed_index >= coll_len - 1 if coll_len > 0 else True
            context["iter"]["loop_event_id"] = loop_event_id_for_metadata
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
            if k not in {"__loop_retry", "__loop_retry_index", "__loop_continue", "__loop_collection", "__base_context"}
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
            logger.info(f"[PIPELINE] Step '{step.step}' has pipeline with {len(pipeline or [])} tasks (deferred rendering)")

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
            next_targets = [arc.model_dump(exclude_none=True) for arc in _get_next_arcs(step)]
            logger.debug(f"[NEXT] Step '{step.step}' has {len(next_targets)} next targets")

        next_mode = _get_next_mode(step)
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
