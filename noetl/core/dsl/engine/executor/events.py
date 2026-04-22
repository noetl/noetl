from __future__ import annotations

from .common import *
from .state import ExecutionState
from .store import PlaybookRepo, StateStore

class EventHandlingMixin:
    async def _persist_event_compat(self, event: Event, state: ExecutionState, conn=None):
        """Call _persist_event while tolerating older monkeypatched test doubles."""
        try:
            return await self._persist_event(event, state, conn=conn)
        except TypeError as exc:
            if "unexpected keyword argument 'conn'" not in str(exc):
                raise
            return await self._persist_event(event, state)

    async def _count_durable_pending_commands(self, execution_id: str, conn=None) -> Optional[int]:
        """Return pending command count from noetl.command, or None if unavailable."""
        query = """
            SELECT COUNT(*) AS pending_count
            FROM noetl.command
            WHERE execution_id = %s
              AND status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')
        """
        try:
            if conn is not None:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(query, (int(execution_id),))
                    row = await cur.fetchone()
            else:
                async with get_pool_connection() as pool_conn:
                    async with pool_conn.cursor(row_factory=dict_row) as cur:
                        await cur.execute(query, (int(execution_id),))
                        row = await cur.fetchone()
            return int((row or {}).get("pending_count", 0) or 0)
        except Exception as exc:
            logger.debug(
                "[COMPLETION] Durable command pending-count lookup skipped for execution=%s: %s",
                execution_id,
                exc,
            )
            return None

    async def handle_event(self, event: Event, conn=None, already_persisted: bool = False) -> list[Command]:
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
        if event.name == "call.done" and "task_sequence" in str(event.step):
            pass
        commands: list[Command] = []
        normalized_payload = _unwrap_event_payload(event.payload)
        preserved_loop_snapshots: dict[str, dict[str, Any]] = {}
        cache_refreshed = False
        


        if conn:
            state = await self.state_store.load_state_for_update(event.execution_id, conn)
        else:
            state = await self.state_store.load_state(event.execution_id)
            if state and await self.state_store.should_refresh_cached_state(
                event.execution_id,
                state.last_event_id,
                allowed_missing_events=1,
            ):
                preserved_loop_snapshots = self._snapshot_loop_collections(state)
                await self.state_store.invalidate_state(
                    event.execution_id,
                    reason="stale_cache_newer_persisted_events",
                )
                state = await self.state_store.load_state(event.execution_id)
                cache_refreshed = True
        if not state:
            logger.error(f"Execution state not found: {event.execution_id}")
            return commands

        if cache_refreshed and preserved_loop_snapshots:
            self._restore_loop_collection_snapshots(state, preserved_loop_snapshots)

        # DIAG: dump load_next_facility step_result as seen after state load
        if event.step and (event.step.startswith("setup_") or event.step.startswith("fetch_")):
            try:
                _lnf = state.step_results.get("load_next_facility")
                _lnf_keys = list(_lnf.keys()) if isinstance(_lnf, dict) else type(_lnf).__name__
                _lnf_ctx = _lnf.get("context") if isinstance(_lnf, dict) else None
                _lnf_ctx_keys = list(_lnf_ctx.keys()) if isinstance(_lnf_ctx, dict) else type(_lnf_ctx).__name__
                _lnf_top_rows = _lnf.get("rows") if isinstance(_lnf, dict) else None
                _lnf_ctx_rows = _lnf_ctx.get("rows") if isinstance(_lnf_ctx, dict) else None
                logger.info(
                    "[DIAG-LOADED] event.step=%s event.name=%s lnf_keys=%s lnf_ctx_keys=%s "
                    "top_rows_len=%s ctx_rows_len=%s",
                    event.step, event.name, _lnf_keys, _lnf_ctx_keys,
                    len(_lnf_top_rows) if isinstance(_lnf_top_rows, list) else None,
                    len(_lnf_ctx_rows) if isinstance(_lnf_ctx_rows, list) else None,
                )
            except Exception as _e:
                logger.info("[DIAG-LOADED] failed: %s", _e)

        if state.completed:
            logger.info(
                "[ENGINE] Execution %s already completed; skipping orchestration for event %s/%s",
                event.execution_id,
                event.name,
                event.step,
            )
            if not already_persisted:
                await self._persist_event_compat(event, state, conn=conn)
                await self.state_store.save_state(state, conn)
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
            command_id = _extract_command_id_from_event_payload(normalized_payload, event.meta)
            if command_id:
                persisted_count = await self._count_persisted_command_events(
                    event.execution_id,
                    event.name,
                    command_id,
                )
                if persisted_count > 1:
                    persisted_event_id_raw = (event.meta or {}).get("persisted_event_id")
                    persisted_event_id = None
                    if persisted_event_id_raw is not None:
                        try:
                            persisted_event_id = int(persisted_event_id_raw)
                        except (TypeError, ValueError):
                            persisted_event_id = None

                    if persisted_event_id is not None:
                        is_first_persisted = await self._is_first_persisted_command_event(
                            event.execution_id,
                            event.name,
                            command_id,
                            persisted_event_id,
                        )
                        if not is_first_persisted:
                            logger.warning(
                                "[EVENT-DEDUPE] Ignoring duplicate persisted %s for execution=%s "
                                "step=%s command_id=%s count=%s event_id=%s",
                                event.name,
                                event.execution_id,
                                event.step,
                                command_id,
                                persisted_count,
                                persisted_event_id,
                            )
                            return commands
                    else:
                        logger.warning(
                            "[EVENT-DEDUPE] Ignoring duplicate persisted %s for execution=%s "
                            "step=%s command_id=%s count=%s (persisted_event_id unavailable)",
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
                await self._persist_event_compat(event, state, conn=conn)
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
                    await self.state_store.save_state(state, conn)
                    return commands

                # Check if all issued steps are now completed (workflow might be done)
                pending_steps = state.issued_steps - state.completed_steps
                if not pending_steps and not state.completed:
                    # All steps completed - emit workflow/playbook completion events
                    state.completed = True
                    from noetl.core.dsl.engine.models import LifecycleEventPayload

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
                    await self._persist_event_compat(workflow_completion_event, state, conn=conn)
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
                    await self._persist_event_compat(playbook_completion_event, state, conn=conn)
                    logger.info(f"Playbook completed (after inline task): execution_id={event.execution_id}")

                    await self.state_store.save_state(state, conn)
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
            if not payload_loop_event_id and isinstance(normalized_payload, dict):
                context_data = normalized_payload.get("context")
                if isinstance(context_data, dict):
                    payload_loop_event_id = context_data.get("loop_event_id")

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
                await state.mark_step_completed(parent_step, _promoted_data)
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
            if parent_step_def and parent_step_def.loop:
                meta_loop_epoch_id = event.meta.get("__loop_epoch_id") if isinstance(event.meta, dict) else None
                pinned_loop_epoch_id = (
                    str(meta_loop_epoch_id)
                    if meta_loop_epoch_id
                    else (
                        str(normalized_payload.get("__loop_epoch_id"))
                        if isinstance(normalized_payload, dict) and normalized_payload.get("__loop_epoch_id")
                        else (str(payload_loop_event_id) if payload_loop_event_id else None)
                    )
                )
                loop_state = await self._ensure_loop_state_for_epoch(
                    state,
                    parent_step_def,
                    event,
                    pinned_loop_epoch_id,
                )
                if loop_state is None:
                    loop_state = state.loop_state.get(parent_step)
                if loop_state is not None and parent_step not in state.loop_state:
                    state.loop_state[parent_step] = loop_state
                if loop_state and not loop_state.get("aggregation_finalized", False):
                    failed = response_data.get("status", "").upper() == "FAILED"
                    iteration_result = response_data.get("results", response_data)
                    loop_iteration_index = _extract_loop_iteration_index_from_event_payload(
                        normalized_payload,
                        event.meta,
                    )

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
                            str(pinned_loop_epoch_id)
                            if pinned_loop_epoch_id
                            else None
                        )
                        if _pinned_epoch_id and not self._loop_event_id_belongs_to_execution(
                            _pinned_epoch_id,
                            state.execution_id,
                        ):
                            logger.warning(
                                "[TASK_SEQ-LOOP] Ignoring stale pinned epoch for %s execution=%s epoch=%s",
                                parent_step,
                                state.execution_id,
                                _pinned_epoch_id,
                            )
                            _pinned_epoch_id = None
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

                        iteration_terminal_claim: Optional[bool] = True
                        if loop_iteration_index is not None and hasattr(nats_cache, "try_record_loop_iteration_terminal"):
                            iteration_terminal_claim = await nats_cache.try_record_loop_iteration_terminal(
                                str(state.execution_id),
                                parent_step,
                                int(loop_iteration_index),
                                event_id=str(resolved_loop_event_id),
                                command_id=_extract_command_id_from_event_payload(
                                    normalized_payload,
                                    event.meta,
                                ),
                                status="FAILED" if failed else "COMPLETED",
                                terminal_event_name=event.name,
                            )

                        if iteration_terminal_claim:
                            state.add_loop_result(parent_step, iteration_result, failed=failed)
                            logger.info(f"[TASK_SEQ] Added iteration result to loop aggregation for {parent_step}")
                        elif iteration_terminal_claim is False:
                            logger.info(
                                "[TASK_SEQ-LOOP] Duplicate terminal event ignored for %s epoch=%s iteration=%s",
                                parent_step,
                                resolved_loop_event_id,
                                loop_iteration_index,
                            )

                        new_count = -1
                        _stale_epoch_event = False
                        if iteration_terminal_claim is None:
                            _stale_epoch_event = True
                        elif iteration_terminal_claim is False:
                            current_loop_state = await nats_cache.get_loop_state(
                                str(state.execution_id),
                                parent_step,
                                event_id=str(resolved_loop_event_id),
                            )
                            new_count = int(
                                (current_loop_state or {}).get("completed_count", 0) or 0
                            )
                        elif _pinned_epoch_id:
                            # Worker stamped the event with an explicit epoch ID.
                            # Only try that specific key — if it is gone (TTL expired or
                            # wrong epoch) the event belongs to an old, already-completed
                            # batch and must NOT be credited to the current epoch.
                            primary_count = await nats_cache.increment_loop_completed(
                                str(state.execution_id),
                                parent_step,
                                event_id=str(_pinned_epoch_id),
                            )
                            if primary_count >= 0:
                                new_count = primary_count
                                resolved_loop_event_id = str(_pinned_epoch_id)
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
                            
                            # DO NOT fall back to global count(*), which artificially inflates cross-epoch values
                            # and causes immediate loop termination for multi-pass runs!
                            # Let the memory state or NATS state be authoritative.
                            if new_count <= 0 and nats_loop_state:
                                new_count = int(nats_loop_state.get("completed_count", 0))
                            logger.warning(
                                f"[TASK_SEQ-LOOP] Could not increment NATS loop count for {parent_step}; "
                                f"falling back to persisted/local count {new_count}"
                            )
                        else:
                            logger.debug(
                                f"[TASK_SEQ-LOOP] Incremented loop count in NATS K/V for "
                                f"{parent_step} via {resolved_loop_event_id}: {new_count}"
                            )

                        is_late_arrival = bool(
                            loop_state.get("event_id") 
                            and resolved_loop_event_id 
                            and resolved_loop_event_id != loop_state.get("event_id")
                        )
                        if is_late_arrival:
                            logger.info(
                                f"[TASK_SEQ-LOOP] Late call.done for {parent_step} epoch {resolved_loop_event_id} "
                                f"(active: {loop_state.get('event_id')}) — detaching loop_state"
                            )
                            loop_state = dict(loop_state)
                        else:
                            loop_state["event_id"] = resolved_loop_event_id

                        # Resolve collection size with distributed-safe fallback order:
                        # local cache -> NATS K/V metadata -> re-render loop expression.
                        collection = loop_state.get("collection")
                        collection_size = len(collection or []) if isinstance(collection, list) else 0

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
                            # Cursor loops never render a collection from a
                            # template — the "collection" is synthetic (one
                            # slot per worker).  Recover size from the step
                            # spec instead of trying to re-render loop.in_.
                            if parent_step_def.loop and parent_step_def.loop.is_cursor:
                                worker_count_fallback = 1
                                if parent_step_def.loop.spec and parent_step_def.loop.spec.max_in_flight:
                                    worker_count_fallback = max(1, int(parent_step_def.loop.spec.max_in_flight))
                                collection_size = worker_count_fallback
                                loop_state["collection_size"] = collection_size
                                logger.info(
                                    "[CURSOR-LOOP] Restored collection_size=%d from worker_count for %s",
                                    collection_size,
                                    parent_step,
                                )
                            else:
                                context = state.get_render_context(event)
                                rendered_collection = self._render_template(parent_step_def.loop.in_, context)
                                rendered_collection = self._normalize_loop_collection(rendered_collection, parent_step)
                                loop_state["collection"] = list(rendered_collection)
                                collection_size = len(rendered_collection or [])
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
                        # Covers two failure modes that both leave loop.done stuck:
                        #
                        # (a) All slots scheduled (scheduled_count >= collection_size) but a
                        #     handful of iterations never reached a terminal event — dispatched
                        #     to a worker that died, or the command event was lost in flight.
                        #
                        # (b) The head/dispatch side got CAS-throttled in
                        #     claim_next_loop_indices and some tail indices were never even
                        #     scheduled (scheduled_count < collection_size).  In that case
                        #     the gap between scheduled and collection_size is at least as
                        #     important as the remaining_count window — we need to reissue
                        #     the un-scheduled tail, otherwise loop.done waits forever.
                        #
                        # Both cases trigger a best-effort reissue when the remaining work
                        # is within the repair threshold.
                        _unscheduled_gap = max(0, collection_size - scheduled_count)
                        # Cursor loops do not tolerate tail-repair: each
                        # worker is a persistent slot, not an enumerable
                        # row.  Reclaim of crashed mid-flight rows is the
                        # driver's job (SQL claim prelude resets stale
                        # claims), not the engine's.
                        _is_cursor_loop_parent = bool(
                            parent_step_def.loop and parent_step_def.loop.is_cursor
                        )
                        _tail_needs_repair = (
                            not _is_cursor_loop_parent
                            and _TASKSEQ_LOOP_REPAIR_THRESHOLD > 0
                            and collection_size > 0
                            and remaining_count > 0
                            and remaining_count <= _TASKSEQ_LOOP_REPAIR_THRESHOLD
                            and (
                                scheduled_count >= collection_size
                                or _unscheduled_gap <= _TASKSEQ_LOOP_REPAIR_THRESHOLD
                            )
                        )
                        if _tail_needs_repair:
                            missing_indexes = await self._find_missing_loop_iteration_indices(
                                state.execution_id,
                                event.step,
                                loop_event_id=resolved_loop_event_id,
                                limit=_TASKSEQ_LOOP_REPAIR_THRESHOLD,
                            )
                            # When scheduled_count fell short of collection_size (CAS-throttled
                            # dispatch), the un-scheduled indices never got a command.issued
                            # event and therefore won't be found by _find_missing_loop_iteration_indices.
                            # Add them explicitly here.
                            if _unscheduled_gap > 0:
                                for _gap_idx in range(scheduled_count, collection_size):
                                    if _gap_idx not in missing_indexes:
                                        missing_indexes.append(_gap_idx)
                                        if len(missing_indexes) >= _TASKSEQ_LOOP_REPAIR_THRESHOLD:
                                            break
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
                                        if not is_late_arrival:
                                            loop_state["completed"] = True
                                            loop_state["aggregation_finalized"] = True
                                            await state.mark_step_completed(
                                                parent_step,
                                                state.get_loop_aggregation(parent_step),
                                            )

                                        # [CLAIM-RECOVERY] If the claim was lost (claimed in KV but event never persisted),
                                        # proceed with the transition anyway to avoid stalling the workflow.
                                        # Or if we just successfully pulled the claim, we shouldn't skip. Wait,
                                        # the problem is that `loop_done_commands` is NOT appended to `commands` in the 
                                        # Recovery branch if `_skip_loop_done` is flipped to False!
                                        # Ah! No, it falls through to `if not _skip_loop_done:`.
                                        if not is_late_arrival and not _is_loop_epoch_transition_emitted(
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

                                if not _skip_loop_done and not is_late_arrival:
                                    # Loop done - mark completed and create loop.done event
                                    loop_state["completed"] = True
                                    loop_state["aggregation_finalized"] = True
                                    logger.info(f"[TASK_SEQ-LOOP] Loop completed for {parent_step}: {new_count}/{collection_size}")

                                    # Get aggregated result
                                    loop_aggregation = state.get_loop_aggregation(parent_step)
                                    await state.mark_step_completed(parent_step, loop_aggregation)

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
                                    await self._persist_event_compat(loop_done_event, state, conn=conn)
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

            for idx, cmd in enumerate(commands):
                if idx % 50 == 0: await asyncio.sleep(0)
                pending_key = _pending_step_key(cmd.step)
                if not pending_key:
                    continue
                state.issued_steps.add(pending_key)
                if idx % 100 == 0: logger.info(
                    "[ISSUED] Added task-sequence %s to issued_steps for execution %s, total issued=%s",
                    pending_key,
                    state.execution_id,
                    len(state.issued_steps),
                )

            # Task-sequence call.done can mutate loop_state, variables, and pending tracking
            # even when the next actionable command is emitted by the API after this method
            # returns. Persist that state before returning so later status/completion checks
            # do not see a stale pre-continuation snapshot.
            await self.state_store.save_state(state, conn)
            if not already_persisted:
                await self._persist_event_compat(event, state, conn=conn)
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
            if event.step in ("load_next_facility", "setup_facility_work") or (isinstance(event.step, str) and event.step.startswith("mark_")):
                try:
                    _rd_keys = list(response_data.keys()) if isinstance(response_data, dict) else type(response_data).__name__
                    _ctx = response_data.get("context") if isinstance(response_data, dict) else None
                    _ctx_keys = list(_ctx.keys()) if isinstance(_ctx, dict) else type(_ctx).__name__
                    _top_rows = response_data.get("rows") if isinstance(response_data, dict) else None
                    _ctx_rows = _ctx.get("rows") if isinstance(_ctx, dict) else None
                    logger.info(
                        "[DIAG-SET] step=%s response_keys=%s context_keys=%s "
                        "top_rows_len=%s ctx_rows_len=%s",
                        event.step, _rd_keys, _ctx_keys,
                        len(_top_rows) if isinstance(_top_rows, list) else None,
                        len(_ctx_rows) if isinstance(_ctx_rows, list) else None,
                    )
                except Exception as _e:
                    logger.info("[DIAG-SET] failed to dump response_data: %s", _e)
            await state.mark_step_completed(event.step, response_data)
            if event.step in ("load_next_facility", "setup_facility_work") or (isinstance(event.step, str) and event.step.startswith("mark_")):
                try:
                    _sr = state.step_results.get(event.step)
                    _sr_keys = list(_sr.keys()) if isinstance(_sr, dict) else type(_sr).__name__
                    _sr_ctx = _sr.get("context") if isinstance(_sr, dict) else None
                    _sr_ctx_keys = list(_sr_ctx.keys()) if isinstance(_sr_ctx, dict) else type(_sr_ctx).__name__
                    _sr_top_rows = _sr.get("rows") if isinstance(_sr, dict) else None
                    _sr_ctx_rows = _sr_ctx.get("rows") if isinstance(_sr_ctx, dict) else None
                    logger.info(
                        "[DIAG-POST-MARK] step=%s keys=%s ctx_keys=%s top_rows_len=%s ctx_rows_len=%s",
                        event.step, _sr_keys, _sr_ctx_keys,
                        len(_sr_top_rows) if isinstance(_sr_top_rows, list) else None,
                        len(_sr_ctx_rows) if isinstance(_sr_ctx_rows, list) else None,
                    )
                except Exception as _e:
                    logger.info("[DIAG-POST-MARK] failed: %s", _e)
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
        next_any_raised: bool = False
        is_loop_step = step_def.loop is not None and event.step in state.loop_state
        if event.name in ("call.done", "call.error") and not is_loop_step:
            next_commands, next_any_matched, next_any_raised = await self._evaluate_next_transitions_with_status(
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
                loop_iteration_index = _extract_loop_iteration_index_from_event_payload(
                    normalized_payload,
                    event.meta,
                )

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
                    meta_loop_epoch_id = event.meta.get("__loop_epoch_id") if isinstance(event.meta, dict) else None
                    _pinned_epoch_id = (
                        str(meta_loop_epoch_id)
                        if meta_loop_epoch_id
                        else (
                            str(event.payload.get("__loop_epoch_id"))
                            if isinstance(event.payload, dict) and event.payload.get("__loop_epoch_id")
                            else (str(payload_loop_event_id) if payload_loop_event_id else None)
                        )
                    )
                    if _pinned_epoch_id and not self._loop_event_id_belongs_to_execution(
                        _pinned_epoch_id,
                        state.execution_id,
                    ):
                        logger.warning(
                            "[LOOP-CALL.DONE] Ignoring stale pinned epoch for %s execution=%s epoch=%s",
                            event.step,
                            state.execution_id,
                            _pinned_epoch_id,
                        )
                        _pinned_epoch_id = None
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

                    iteration_terminal_claim: Optional[bool] = True
                    if loop_iteration_index is not None and hasattr(nats_cache, "try_record_loop_iteration_terminal"):
                        iteration_terminal_claim = await nats_cache.try_record_loop_iteration_terminal(
                            str(state.execution_id),
                            event.step,
                            int(loop_iteration_index),
                            event_id=str(resolved_loop_event_id),
                            command_id=_extract_command_id_from_event_payload(
                                normalized_payload,
                                event.meta,
                            ),
                            status="FAILED" if failed else "COMPLETED",
                            terminal_event_name=event.name,
                        )

                    if iteration_terminal_claim:
                        state.add_loop_result(event.step, response_data, failed=failed)
                        logger.info(f"[LOOP-CALL.DONE] Added iteration result to loop aggregation for {event.step}")
                    elif iteration_terminal_claim is False:
                        logger.info(
                            "[LOOP-CALL.DONE] Duplicate terminal event ignored for %s epoch=%s iteration=%s",
                            event.step,
                            resolved_loop_event_id,
                            loop_iteration_index,
                        )

                    new_count = -1
                    _stale_epoch_event = False
                    if iteration_terminal_claim is None:
                        _stale_epoch_event = True
                    elif iteration_terminal_claim is False:
                        current_loop_state = await nats_cache.get_loop_state(
                            str(state.execution_id),
                            event.step,
                            event_id=str(resolved_loop_event_id),
                        )
                        new_count = int(
                            (current_loop_state or {}).get("completed_count", 0) or 0
                        )
                    elif _pinned_epoch_id:
                        primary_count = await nats_cache.increment_loop_completed(
                            str(state.execution_id), event.step, event_id=str(_pinned_epoch_id)
                        )
                        if primary_count >= 0:
                            new_count = primary_count
                            resolved_loop_event_id = str(_pinned_epoch_id)
                        else:
                            _stale_epoch_event = True
                    else:
                        for candidate_event_id in event_id_candidates:
                            candidate_count = await nats_cache.increment_loop_completed(
                                str(state.execution_id), event.step, event_id=candidate_event_id
                            )
                            if candidate_count >= 0:
                                new_count = candidate_count
                                resolved_loop_event_id = candidate_event_id
                                break

                    _nats_count_reliable = True
                    if _stale_epoch_event:
                        _nats_count_reliable = False
                        logger.warning(
                            "[LOOP-CALL.DONE] Stale call.done for %s (payload_epoch=%s) — "
                            "epoch key not found in NATS (TTL expired?); discarding to protect current epoch",
                            event.step,
                            payload_loop_event_id,
                        )
                    elif new_count < 0:
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

                    is_late_arrival = bool(
                        loop_state.get("event_id") 
                        and resolved_loop_event_id 
                        and resolved_loop_event_id != loop_state.get("event_id")
                    )
                    if is_late_arrival:
                        logger.info(
                            f"[LOOP-CALL.DONE] Late call.done for {event.step} epoch {resolved_loop_event_id} "
                            f"(active: {loop_state.get('event_id')}) — detaching loop_state"
                        )
                        loop_state = dict(loop_state)
                    else:
                        loop_state["event_id"] = resolved_loop_event_id

                    # Resolve collection size from NATS or re-render
                    nats_loop_state = await nats_cache.get_loop_state(
                        str(state.execution_id), event.step, event_id=resolved_loop_event_id
                    )
                    collection_size = int((nats_loop_state or {}).get("collection_size", 0) or 0)

                    if collection_size == 0:
                        if step_def.loop and step_def.loop.is_cursor:
                            # Cursor loops: collection_size == worker concurrency.
                            worker_count_fallback = 1
                            if step_def.loop.spec and step_def.loop.spec.max_in_flight:
                                worker_count_fallback = max(1, int(step_def.loop.spec.max_in_flight))
                            collection_size = worker_count_fallback
                            loop_state["collection_size"] = collection_size
                            logger.info(
                                "[CURSOR-LOOP] Restored collection_size=%d from worker_count for %s (call.done handler)",
                                collection_size,
                                event.step,
                            )
                        else:
                            loop_context = state.get_render_context(event)
                            rendered_collection = self._render_template(step_def.loop.in_, loop_context)
                            rendered_collection = self._normalize_loop_collection(rendered_collection, event.step)
                            loop_state["collection"] = list(rendered_collection)
                            collection_size = len(rendered_collection or [])
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
                                    if not is_late_arrival:
                                        loop_state["completed"] = True
                                        loop_state["aggregation_finalized"] = True
                                        await state.mark_step_completed(
                                            event.step,
                                            state.get_loop_aggregation(event.step),
                                        )

                                    # [CLAIM-RECOVERY] If the claim was lost (claimed in KV but event never persisted),
                                    # proceed with the transition anyway to avoid stalling the workflow.
                                    if not is_late_arrival and not _is_loop_epoch_transition_emitted(
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

                            if not _skip_loop_done and not is_late_arrival:
                                loop_state["completed"] = True
                                loop_state["aggregation_finalized"] = True
                                logger.info(f"[LOOP-CALL.DONE] Loop completed for {event.step}: {new_count}/{collection_size}")

                                loop_aggregation = state.get_loop_aggregation(event.step)
                                await state.mark_step_completed(event.step, loop_aggregation)

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
                                await self._persist_event_compat(loop_done_event, state, conn=conn)
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
                    if event.step in ("load_next_facility", "setup_facility_work") or (isinstance(event.step, str) and event.step.startswith("mark_")):
                        try:
                            _hr_keys = list(hydrated_result.keys()) if isinstance(hydrated_result, dict) else type(hydrated_result).__name__
                            _ctx = hydrated_result.get("context") if isinstance(hydrated_result, dict) else None
                            _ctx_keys = list(_ctx.keys()) if isinstance(_ctx, dict) else type(_ctx).__name__
                            _top_rows = hydrated_result.get("rows") if isinstance(hydrated_result, dict) else None
                            _ctx_rows = _ctx.get("rows") if isinstance(_ctx, dict) else None
                            logger.info(
                                "[DIAG-EXIT] step=%s hydrated_keys=%s context_keys=%s "
                                "top_rows_len=%s ctx_rows_len=%s",
                                event.step, _hr_keys, _ctx_keys,
                                len(_top_rows) if isinstance(_top_rows, list) else None,
                                len(_ctx_rows) if isinstance(_ctx_rows, list) else None,
                            )
                        except Exception as _e:
                            logger.info("[DIAG-EXIT] failed: %s", _e)
                    await state.mark_step_completed(event.step, hydrated_result)
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

                    supervisor_completed_count = await self._count_supervised_loop_terminal_iterations(
                        str(state.execution_id),
                        event.step,
                        event_id=str(resolved_loop_event_id)
                    )
                    if supervisor_completed_count > completed_count:
                        completed_count = supervisor_completed_count
                        if nats_loop_state:
                            repaired_at = datetime.now(timezone.utc).isoformat()
                            nats_loop_state["completed_count"] = completed_count
                            nats_loop_state["scheduled_count"] = max(
                                int(nats_loop_state.get("scheduled_count", completed_count) or completed_count),
                                completed_count,
                            )
                            nats_loop_state["last_counter_reconcile_at"] = repaired_at
                            nats_loop_state["last_progress_at"] = repaired_at
                            nats_loop_state["updated_at"] = repaired_at
                            loop_state["scheduled_count"] = nats_loop_state["scheduled_count"]
                            loop_state["last_counter_reconcile_at"] = repaired_at
                            await nats_cache.set_loop_state(
                                str(state.execution_id),
                                event.step,
                                nats_loop_state,
                                event_id=str(resolved_loop_event_id) if resolved_loop_event_id else None,
                            )
                        logger.warning(
                            "[LOOP-STEP.EXIT] Reconciled %s completion from supervisor state "
                            "(event_id=%s completed=%s)",
                            event.step,
                            resolved_loop_event_id,
                            completed_count,
                        )
                    
                    # Only render collection if not already cached (expensive operation)
                    if loop_state and not loop_state.get("collection"):
                        if step_def.loop and step_def.loop.is_cursor:
                            # Cursor loops: collection is synthetic (one
                            # slot per worker); there is no loop.in_ to
                            # render.  Rebuild the synthetic collection.
                            worker_count_fallback = 1
                            if step_def.loop.spec and step_def.loop.spec.max_in_flight:
                                worker_count_fallback = max(1, int(step_def.loop.spec.max_in_flight))
                            collection = list(range(worker_count_fallback))
                            loop_state["collection"] = collection
                            logger.info(
                                "[CURSOR-LOOP] Rebuilt synthetic collection (size=%d) for %s",
                                len(collection), event.step,
                            )
                        else:
                            context = state.get_render_context(event)
                            collection = self._render_template(step_def.loop.in_, context)
                            collection = self._normalize_loop_collection(collection, event.step)
                            loop_state["collection"] = list(collection)
                            logger.info(f"[LOOP-SETUP] Rendered collection for {event.step}: {len(collection or [])} items")
                        
                        # Store initial loop state in NATS K/V with event_id
                        # NOTE: We store only metadata and completed_count, NOT results array
                        loop_event_id = loop_state.get("event_id")
                        await nats_cache.set_loop_state(
                            str(state.execution_id),
                            event.step,
                            {
                                "collection_size": len(collection or []),
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
                                    await state.mark_step_completed(
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
                            await state.mark_step_completed(event.step, loop_aggregation)
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
                            await self._persist_event_compat(loop_done_event, state, conn=conn)
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
                next_mode = _get_next_mode(step_def)
                next_arcs = _get_next_arcs(step_def)

                logger.info(
                    "[STRUCTURAL-NEXT] No next matched for step.exit, using structural next (mode=%s, next_count=%s)",
                    next_mode,
                    len(next_arcs),
                )

                context = state.get_render_context(event)

                for next_item in next_arcs:
                    target_step = next_item.step
                    when_condition = next_item.when

                    # Evaluate when condition if present
                    if when_condition:
                        if not self._evaluate_condition(when_condition, context):
                            logger.debug(f"[STRUCTURAL-NEXT] Skipping {target_step}: condition not met ({when_condition})")
                            continue
                        logger.info(f"[STRUCTURAL-NEXT] Condition matched for {target_step}: {when_condition}")

                    next_step_def = state.get_step(target_step)
                    if next_step_def:
                        pending_target = _pending_step_key(target_step)
                        if (
                            pending_target
                            and pending_target in state.issued_steps
                            and pending_target not in state.completed_steps
                        ):
                            target_def = state.get_step(target_step)
                            if target_def and getattr(target_def, "loop", None):
                                logger.debug(
                                    "[STRUCTURAL-NEXT] Allowing re-dispatch of loop step '%s' during fallback",
                                    target_step,
                                )
                            else:
                                logger.info(
                                    "[STRUCTURAL-NEXT] Skipping duplicate fallback dispatch for '%s' - already pending",
                                    target_step,
                                )
                                continue

                        issued_cmds = await self._issue_loop_commands(state, next_step_def, {})
                        if issued_cmds:
                            commands.extend(issued_cmds)
                            state.completed_steps.discard(target_step)
                            if pending_target:
                                state.issued_steps.add(pending_target)
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
                    await state.mark_step_completed(event.step, current_result)
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
            pending_count: Optional[int] = None
            try:
                nats_cache = await get_nats_cache()
                pending_count = await nats_cache.get_pending_command_count(
                    str(event.execution_id)
                )
                if pending_count is not None:
                    has_pending_commands = pending_count > 0
                    logger.debug(
                        "[COMPLETION] execution=%s pending_in_supervisor=%s",
                        event.execution_id,
                        pending_count,
                    )
            except Exception as cache_exc:
                logger.debug(
                    "[COMPLETION] Supervisor pending-count lookup skipped for execution=%s: %s",
                    event.execution_id,
                    cache_exc,
                )

            if pending_count is None:
                # Only fall back to database query if in-memory state might be stale (e.g., after restart)
                if conn is None:
                    async with get_pool_connection() as c:
                        async with c.cursor(row_factory=dict_row) as cur:
                            await cur.execute("SELECT pending_count FROM noetl.runtime WHERE scope = 'cluster'")
                            row = await cur.fetchone()
                else:
                    async with conn.cursor(row_factory=dict_row) as cur:
                        await cur.execute("SELECT pending_count FROM noetl.runtime WHERE scope = 'cluster'")
                        row = await cur.fetchone()
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
        # Durable projection is the last word before a dead-end can complete an
        # execution. This keeps distributed pods from trusting an incomplete
        # in-memory issued/completed step set while command rows are still live.
        if not has_pending_commands and is_completion_trigger:
            durable_pending_count = await self._count_durable_pending_commands(
                event.execution_id,
                conn=conn,
            )
            if durable_pending_count is not None:
                has_pending_commands = durable_pending_count > 0
                if has_pending_commands:
                    logger.debug(
                        "[COMPLETION] execution=%s pending_in_command_table=%s",
                        event.execution_id,
                        durable_pending_count,
                    )
        # If in-memory state shows no pending AND command table agrees, trust it.

        # Also probe arc rendering for step.exit and other fallback paths that did
        # not go through _evaluate_next_transitions_with_status (which sets
        # next_any_raised).  Without this, a step.exit arriving after a call.done
        # whose arcs all raised would appear dead-end-eligible and prematurely fire
        # workflow.completed.
        if not next_any_raised and is_completion_trigger and step_def.next and not is_loop_step:
            from .transitions import _get_next_arcs  # local import to avoid cycles
            for probe in _get_next_arcs(step_def):
                probe_when = getattr(probe, "when", None)
                if not probe_when:
                    continue
                try:
                    self._render_template(probe_when, context)
                except Exception:
                    next_any_raised = True
                    logger.warning(
                        "[COMPLETION] Arc probe raised on step=%s event=%s when=%r — "
                        "treating completion check as indeterminate",
                        event.step, event.name,
                        (probe_when[:80] + "...") if isinstance(probe_when, str) and len(probe_when) > 80 else probe_when,
                    )
                    break

        has_matching_next_transition = (
            (
                next_any_matched
                if next_any_matched is not None
                else self._has_matching_next_transition(state, step_def, context)
            )
            if (is_completion_trigger and step_def.next and not is_loop_step)
            else False
        )
        next_no_match_action = "complete"
        if step_def and step_def.next and getattr(step_def.next, "spec", None):
            next_no_match_action = str(
                getattr(step_def.next.spec, "on_no_match", "complete") or "complete"
            ).lower()
        quiet_no_match = next_no_match_action == "quiet"
        is_dead_end_no_match = (
            is_completion_trigger
            and bool(step_def.next)
            and not is_loop_step
            and not has_matching_next_transition
            and not commands
            and not has_pending_commands
            and not next_any_raised
            and not quiet_no_match
        )
        if quiet_no_match and is_completion_trigger and bool(step_def.next) and not has_matching_next_transition and not commands:
            logger.info(
                "[COMPLETION] Quiet branch end: execution=%s step=%s has no matching next arcs",
                event.execution_id,
                event.step,
            )
        if next_any_raised:
            logger.warning(
                "[COMPLETION] Skipping dead-end completion for execution=%s step=%s: "
                "arc condition(s) raised during evaluation — treating as indeterminate "
                "to avoid prematurely emitting workflow.completed on a rendering failure",
                event.execution_id,
                event.step,
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
            from noetl.core.dsl.engine.models import LifecycleEventPayload
            completion_status = "failed" if (state.failed or has_error) else "completed"
            if state.failed:
                logger.info(f"[COMPLETION] Execution {event.execution_id} marked as failed due to earlier step failures")
            
            # Persist current event FIRST to get its event_id for parent_event_id
            # Skip if already persisted by API caller
            if not already_persisted:
                await self._persist_event_compat(event, state, conn=conn)
            
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
        await self.state_store.save_state(state, conn)
        
        # Persist current event to database (if not already done for completion case)
        # Skip if event was already persisted by API caller
        if not completion_events and not already_persisted:
            await self._persist_event_compat(event, state, conn=conn)
        
        # Persist completion events in order with proper parent_event_id chain
        for i, completion_event in enumerate(completion_events):
            if i > 0:
                # Set parent to previous completion event
                completion_event.parent_event_id = state.last_event_id
            await self._persist_event_compat(completion_event, state, conn=conn)
        
        # CRITICAL: Stop generating commands if this is a failure event
        # Check AFTER persisting and completion events so they're all stored
        # Only check if we haven't already generated completion events (avoid duplicate stopping logic)
        if not completion_events:
            async def _emit_failed_terminal_events(final_step: str):
                if state.completed:
                    return

                from noetl.core.dsl.engine.models import LifecycleEventPayload

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
                await self._persist_event_compat(workflow_failed_event, state, conn=conn)

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
                await self._persist_event_compat(playbook_failed_event, state, conn=conn)
                await self.state_store.save_state(state, conn)

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
        for idx, cmd in enumerate(commands):
            if idx % 50 == 0: await asyncio.sleep(0)
            pending_key = _pending_step_key(cmd.step)
            if not pending_key:
                continue
            state.issued_steps.add(pending_key)
            logger.info(
                f"[ISSUED] Added {pending_key} to issued_steps for execution {state.execution_id}, "
                f"total issued={len(state.issued_steps)}"
            )

        # Persist state periodically so the next handle_event can use the
        # fast from_dict path. Writing on EVERY event causes row-level lock
        # contention on noetl.execution under high concurrency. Instead,
        # save only when the event count since last save exceeds a threshold
        # or when a significant lifecycle transition occurred.
        _save_interval = 10  # save every N events
        events_since_save = (state.last_event_id or 0) - (getattr(state, '_last_saved_event_id', 0) or 0)
        is_lifecycle = event.name in (
            "loop.done", "step.exit", "command.failed",
            "playbook.completed", "playbook.failed",
            "workflow.completed", "workflow.failed",
        )
        if is_lifecycle or events_since_save >= _save_interval:
            try:
                await self.state_store.save_state(state, conn)
                state._last_saved_event_id = state.last_event_id
            except Exception as exc:
                logger.warning("[ENGINE] Failed to save state: %s", exc)

        return commands
