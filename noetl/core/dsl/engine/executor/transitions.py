from __future__ import annotations

from .common import *
from .state import ExecutionState
from .store import PlaybookRepo, StateStore

class TransitionMixin:
    def _get_loop_max_in_flight(self, step: Step) -> int:
        """Resolve max in-flight limit for loop scheduling.

        For cursor loops max_in_flight is the worker concurrency — the
        number of persistent worker commands dispatched in parallel —
        rather than a per-tick dispatch budget.
        """
        if not step.loop:
            return 1
        loop_mode = step.loop.mode
        if loop_mode not in ("parallel", "cursor"):
            return 1
        if step.loop.spec and step.loop.spec.max_in_flight:
            return max(1, int(step.loop.spec.max_in_flight))
        return 1

    async def _issue_cursor_loop_commands(
        self,
        state: "ExecutionState",
        step_def: Step,
        step_input: dict[str, Any],
    ) -> list[Command]:
        """Dispatch N persistent worker commands for a cursor-driven loop.

        One command per worker slot; each command runs the worker-side
        claim-process-release loop until the cursor is drained.  The
        engine does not claim loop indices, render the collection, or
        participate in per-item iteration — that all happens server-side
        in the worker against the cursor driver.

        Re-entry (``__loop_continue`` / ``__loop_retry``) is a no-op: a
        single dispatch per epoch is enough since each worker loops
        server-side until exhaustion.
        """
        import time
        from noetl.core.dsl.render import render_template as recursive_render

        if not step_def.loop or not step_def.loop.is_cursor:
            return []

        existing_loop_state = state.loop_state.get(step_def.step)
        is_continuation = bool(
            existing_loop_state
            and (step_input.get("__loop_continue") or step_input.get("__loop_retry"))
        )
        if is_continuation:
            # Workers self-continue; nothing to re-dispatch.
            return []

        worker_count = self._get_loop_max_in_flight(step_def)
        loop_event_id = f"loop_{state.execution_id}_{int(time.time() * 1_000_000)}"
        if existing_loop_state:
            del state.loop_state[step_def.step]

        # Seed loop_state so loop.done aggregation treats one worker
        # exit (call.done) as one "slot complete".  The synthetic
        # collection has length = worker_count; completed_count reaches
        # that value when all workers exit.
        state.init_loop(
            step_def.step,
            collection=list(range(worker_count)),
            iterator=step_def.loop.iterator,
            mode="cursor",
            event_id=loop_event_id,
        )

        # Render context built once at dispatch time; the worker renders
        # `iter.<iterator>` per-claim against its own row.  ctx/workload
        # come from the engine snapshot, same as a normal step.
        base_context = state.get_render_context(Event(
            execution_id=state.execution_id,
            step=step_def.step,
            name="cursor_loop_init",
            payload={},
        ))

        # Cursor spec — serialize so the worker receives a plain dict.
        cursor_spec = step_def.loop.cursor.model_dump()

        # Tool config: pipeline (list of labeled tasks) is the expected
        # shape for a cursor loop body; single-tool shorthand is allowed
        # and wrapped into a one-task pipeline for uniform execution.
        if step_def.tool is None:
            logger.error(
                "[CURSOR-LOOP] Step %s has loop.cursor but no tool pipeline; refusing to dispatch",
                step_def.step,
            )
            return []
        if isinstance(step_def.tool, list):
            tasks = step_def.tool
        else:
            tool_dict = step_def.tool.model_dump()
            tasks = [{"name": f"{step_def.step}_task", **tool_dict}]

        # Input bindings mirror the normal step path.
        step_args: dict[str, Any] = {}
        if step_def.input:
            step_args.update(step_def.input)
        filtered_input = {
            k: v for k, v in (step_input or {}).items()
            if not k.startswith("__")
        }
        step_args.update(filtered_input)
        rendered_input = recursive_render(self.jinja_env, step_args, base_context)

        # Next router passes through unchanged — evaluated when
        # loop.done fires (i.e. all workers exited).
        next_targets = None
        if step_def.next:
            next_targets = [arc.model_dump(exclude_none=True) for arc in _get_next_arcs(step_def)]
            next_mode = _get_next_mode(step_def)
        else:
            next_mode = "exclusive"
        command_spec = CommandSpec(next_mode=next_mode)

        commands: list[Command] = []
        for slot in range(worker_count):
            worker_slot_id = f"{loop_event_id}:slot-{slot}"
            tool_config = {
                "cursor": cursor_spec,
                "iterator": step_def.loop.iterator,
                "tasks": tasks,
                "worker_slot_id": worker_slot_id,
                "worker_slot_index": slot,
                "worker_count": worker_count,
                "loop_event_id": loop_event_id,
            }
            command_metadata = {
                "task_sequence": True,
                "parent_step": step_def.step,
                "cursor_worker": True,
                "worker_slot_id": worker_slot_id,
                "loop_step": step_def.step,
                "loop_event_id": loop_event_id,
                "__loop_epoch_id": loop_event_id,
                "loop_worker_count": worker_count,
                # Each worker slot counts as one loop iteration for
                # aggregation purposes: one terminal call.done per slot
                # advances completed_count by 1; loop.done fires when
                # completed_count == worker_count.
                "loop_iteration_index": slot,
            }
            command = Command(
                execution_id=state.execution_id,
                step=f"{step_def.step}:cursor_worker",
                tool=ToolCall(kind="cursor_worker", config=tool_config),
                input=rendered_input,
                render_context=base_context,
                pipeline=tasks,
                next_targets=next_targets,
                spec=command_spec,
                attempt=1,
                priority=0,
                metadata=command_metadata,
            )
            commands.append(command)

        logger.info(
            "[CURSOR-LOOP] Dispatched %d worker command(s) for step %s "
            "(kind=%s, epoch=%s)",
            len(commands), step_def.step, cursor_spec.get("kind"), loop_event_id,
        )
        return commands

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

        # Cursor loops take a different dispatch shape — N worker commands
        # up-front, each running its own claim-process-release loop.
        if step_def.loop.is_cursor:
            return await self._issue_cursor_loop_commands(state, step_def, step_input)

        # Optimization: Fetch loop collection once for the entire batch
        nats_cache = await get_nats_cache()
        
        existing_loop_state = state.loop_state.get(step_def.step)
        loop_event_id = str(existing_loop_state.get("event_id") or "") if existing_loop_state else ""
        
        # PERFORMANCE & CORRECTNESS FIX: If this is a fresh entry into the loop (not a continuation),
        # force a completely new epoch ID *before* we batch claim the NATS slots.
        if not existing_loop_state or (not step_input.get("__loop_continue") and not step_input.get("__loop_retry")):
            import time
            loop_event_id = f"loop_{state.execution_id}_{int(time.time() * 1000000)}"
            # Delete the local state so commands.py knows this is a fresh loop instance!
            if existing_loop_state:
                del state.loop_state[step_def.step]
            existing_loop_state = None
        
        collection = None
        if loop_event_id:
            collection = await nats_cache.get_loop_collection(str(state.execution_id), step_def.step, loop_event_id)
        
        # PERFORMANCE OPTIMIZATION: Always pre-build the render context once for the entire batch.
        # This context will be reused by _create_command_for_step for all N items.
        context = state.get_render_context(Event(
            execution_id=state.execution_id, step=step_def.step, name="loop_init", payload={}
        ))

        should_pre_render_collection = not (
            existing_loop_state is not None
            and (
                step_input.get("__loop_continue")
                or step_input.get("__loop_retry")
            )
        )

        if collection is None and should_pre_render_collection:
            # Render and save
            collection_expr = step_def.loop.in_
            collection = self._render_template(collection_expr, context)
            # Resolve reference if the template rendered to a step result with a
            # reference envelope (e.g. Postgres rows stored in TempStore).
            collection = await _resolve_collection_if_reference(collection)
            collection = self._normalize_loop_collection(collection, step_def.step)
            
            # Persist the real collection to NATS KV immediately so cold-state
            # recovery in _ensure_loop_state_for_epoch can restore actual item
            # payloads (e.g. patient row objects) instead of synthetic placeholders.
            if collection and loop_event_id:
                await nats_cache.save_loop_collection(
                    str(state.execution_id), step_def.step, loop_event_id, collection
                )

        issue_budget = self._get_loop_max_in_flight(step_def)
        commands: list[Command] = []
        shared_control_args = dict(step_input)
        shared_control_args["__base_context"] = context
        # Pass collection BY REFERENCE — the data lives in TempStore/NATS KV.
        # commands.py will fetch items by index from the cache, not from this arg.
        # This keeps the control-plane args bounded regardless of collection size.
        if collection is not None:
            shared_control_args["__loop_collection"] = collection
            shared_control_args["__loop_collection_size"] = len(collection)

        # PERFORMANCE OPTIMIZATION: Batch claim loop indices to avoid O(N) NATS round-trips
        claimed_indices = []
        if (collection or []) is not None:
            # Use nats_cache already initialized at start of method
            claimed_indices = await nats_cache.claim_next_loop_indices(
                str(state.execution_id),
                step_def.step,
                collection_size=len(collection or []),
                max_in_flight=issue_budget, 
                requested_count=issue_budget,
                event_id=loop_event_id
            )

        if claimed_indices:
            for i, idx in enumerate(claimed_indices):
                # Yield to the event loop every 10 iterations to prevent liveness probe failure
                await asyncio.sleep(0)
                
                args = dict(shared_control_args)
                args["__loop_claimed_index"] = idx
                args["__loop_epoch_id"] = loop_event_id  # Pass the newly generated epoch ID to commands.py!
                command = await self._create_command_for_step(state, step_def, args)
                if not command: continue
                commands.append(command)
                shared_control_args["__loop_continue"] = True
        else:
            for j in range(issue_budget):
                # Yield to the event loop every 10 iterations to prevent liveness probe failure
                await asyncio.sleep(0)
                
                args = dict(shared_control_args)
                args["__loop_epoch_id"] = loop_event_id  # Pass the newly generated epoch ID to commands.py!
                command = await self._create_command_for_step(state, step_def, args)
                if not command: break
                commands.append(command)
                shared_control_args["__loop_continue"] = True

        return commands
    
    def _evaluate_condition(self, when_expr: str, context: dict[str, Any]) -> bool:
        """Evaluate when condition."""
        matched, _raised = self._evaluate_condition_with_status(when_expr, context)
        return matched

    def _evaluate_condition_with_status(
        self, when_expr: str, context: dict[str, Any]
    ) -> tuple[bool, bool]:
        """Evaluate a `when` expression and report whether rendering raised.

        Returns (matched, raised). `raised=True` means the expression itself
        could not be rendered (e.g. StrictUndefined on a missing field) — the
        caller should treat this arc as indeterminate, not as a definitive
        False, so a missing result-store reference does not make a step look
        like a dead-end and prematurely complete the execution.
        """
        try:
            result = self._render_template(when_expr, context)

            if isinstance(result, bool):
                logger.debug("[COND] Evaluated condition -> %s", result)
                return result, False
            if isinstance(result, str):
                is_false = result.lower() in ("false", "0", "no", "none", "")
                matched = not is_false
                logger.debug("[COND] Evaluated string condition -> %s", matched)
                return matched, False
            matched = bool(result)
            logger.debug("[COND] Evaluated condition value_type=%s -> %s", type(result).__name__, matched)
            return matched, False
        except Exception as e:
            logger.error(
                "Condition evaluation error: %s | condition_preview=%s",
                e,
                (when_expr[:160] + "...") if isinstance(when_expr, str) and len(when_expr) > 160 else when_expr,
            )
            return False, True
    
    async def _evaluate_next_transitions(
        self,
        state: ExecutionState,
        step_def: Step,
        event: Event
    ) -> list[Command]:
        commands, _actionable_match, _raised = await self._evaluate_next_transitions_with_status(
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
        commands, matched, _raised = await self._evaluate_next_transitions_with_status(
            state,
            step_def,
            event,
        )
        return commands, matched

    async def _evaluate_next_transitions_with_status(
        self,
        state: ExecutionState,
        step_def: Step,
        event: Event,
    ) -> tuple[list[Command], bool, bool]:
        """
        Evaluate next.arcs[].when conditions and return commands plus matched-arc status.

        The boolean return is True when any arc condition matched AND the target step
        exists in the playbook.  A matched-but-deduplicated arc (target already in
        issued_steps) still returns True — the command is already in flight, so this
        is not a dead-end.

        Canonical format routing uses next.spec + next.arcs[]:
        - Each arc has optional 'when'
        - Arcs without 'when' always match
        - next.spec.mode controls evaluation: exclusive (first match) or inclusive (all matches)
        """
        commands = []
        context = state.get_render_context(event)

        if not step_def.next:
            return commands, False, False
        next_mode = _get_next_mode(step_def)
        next_items = _get_next_arcs(step_def)

        logger.info(f"[NEXT-EVAL] Step {event.step} has {len(next_items)} next targets, mode={next_mode}, evaluating for event {event.name}")

        any_matched = False
        any_raised = False

        for idx, next_target in enumerate(next_items):
            target_step = next_target.step
            when_condition = next_target.when
            arc_set = next_target.set or {}

            if not target_step:
                logger.warning(f"[NEXT-EVAL] Skipping next entry {idx} with no step")
                continue

            # Evaluate when condition (if present)
            if when_condition:
                logger.debug(f"[NEXT-EVAL] Evaluating next[{idx}].when: {when_condition}")
                matched, raised = self._evaluate_condition_with_status(when_condition, context)
                if raised:
                    any_raised = True
                if not matched:
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
                target_def = state.get_step(target_step)
                # Loop steps manage their own epoch transitions via NATS and local state resets.
                # Do not block re-dispatch based purely on stale in-memory 'completed' flags across pods.
                if target_def and getattr(target_def, "loop", None):
                    logger.debug(
                        "[NEXT-EVAL] Allowing re-dispatch of loop step '%s' — delegating epoch check to command creation",
                        target_step,
                    )
                else:
                    logger.warning(f"[NEXT-EVAL] Skipping duplicate command for step '{target_step}' - already in issued_steps")
                    continue

            # Apply arc-level set mutations to state before issuing the command.
            # Arc-level set writes to ctx/iter/step scopes.
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
        if any_raised:
            logger.warning(
                "[NEXT-EVAL] Step %s had arc condition(s) that raised during rendering; "
                "caller should treat outcome as indeterminate",
                event.step,
            )

        return commands, any_matched, any_raised

    def _has_matching_next_transition(
        self,
        state: ExecutionState,
        step_def: Step,
        context: dict[str, Any],
    ) -> bool:
        """Return True when a next arc condition matches and target step exists."""
        if not step_def.next:
            return False

        for next_target in _get_next_arcs(step_def):
            target_step = next_target.step
            if not target_step:
                continue
            when_condition = next_target.when
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
                next_value = action["next"]

                if isinstance(next_value, dict) and "next" in next_value:
                    next_items = next_value["next"]
                    if not isinstance(next_items, list):
                        next_items = [next_items]
                else:
                    next_items = next_value if isinstance(next_value, list) else [next_value]

                for next_item in next_items:
                    if isinstance(next_item, str):
                        # Simple step name
                        target_step = next_item
                        arc_set = {}
                    elif isinstance(next_item, dict):
                        # {step: name, set: {...}} (canonical)
                        target_step = next_item.get("step")
                        arc_set = next_item.get("set") or {}

                        # Render and apply arc-level set mutations
                        if arc_set:
                            rendered_arc = {}
                            for key, value in arc_set.items():
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

            if isinstance(next_value, dict) and "next" in next_value:
                next_items = next_value["next"]
                if not isinstance(next_items, list):
                    next_items = [next_items]
            else:
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
