from __future__ import annotations

from .common import *
from .state import ExecutionState
from .store import PlaybookRepo, StateStore

class LifecycleMixin:
    async def _persist_event(self, event: Event, state: ExecutionState, conn=None):
        """Persist event to database with state tracking."""
        # Use catalog_id from state, or lookup from existing events
        catalog_id = state.catalog_id
        
        if not catalog_id:
            if conn is None:
                async with get_pool_connection() as c:
                    async with c.cursor() as cur:
                        await cur.execute("SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1", (int(event.execution_id),))
                        result = await cur.fetchone()
                        catalog_id = result['catalog_id'] if result else None
            else:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1", (int(event.execution_id),))
                    result = await cur.fetchone()
                    catalog_id = result['catalog_id'] if result else None
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
