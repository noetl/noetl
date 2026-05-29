from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional

from .common import *
from .outbox import drain_executor_outbox, enqueue_executor_outbox
from .state import ExecutionState
from .store import PlaybookRepo, StateStore
from noetl.core.dsl.engine.models import Event, Command
from noetl.core.credential_refs import KEYCHAIN_MANIFEST_KEY, strip_keychain_namespaces

class LifecycleMixin:
    async def _persist_event(self, event: Event, state: ExecutionState, conn=None):
        """Persist event to database with state tracking."""
        # Use catalog_id from state, or lookup from existing events
        catalog_id = state.catalog_id
        
        async def _do_persist(c):
            nonlocal catalog_id
            if not catalog_id:
                async with c.cursor() as cur:
                    await cur.execute("SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1", (int(event.execution_id),))
                    result = await cur.fetchone()
                    catalog_id = result['catalog_id'] if result else None
            
            if not catalog_id:
                logger.error(f"Cannot persist event - no catalog_id for execution {event.execution_id}")
                return
            
            parent_event_id = event.parent_event_id
            if parent_event_id is None:
                if event.step:
                    parent_event_id = state.step_event_ids.get(event.step)
                if not parent_event_id:
                    parent_event_id = state.last_event_id
            
            duration_ms = 0
            event_timestamp = event.timestamp or datetime.now(timezone.utc)
            
            is_loop_iteration_exit = (
                event.name == "step.exit"
                and event.step
                and (
                    event.step.endswith(":task_sequence")
                    or (event.step in state.loop_state if hasattr(state, 'loop_state') else False)
                )
            )
            
            if event.name == "step.exit" and event.step and not is_loop_iteration_exit:
                async with c.cursor() as cur:
                    await cur.execute("SELECT created_at FROM noetl.event WHERE execution_id = %s AND node_id = %s AND event_type = 'step.enter' ORDER BY event_id DESC LIMIT 1", (int(event.execution_id), event.step))
                    enter_event = await cur.fetchone()
                    if enter_event and enter_event['created_at']:
                        start_time = enter_event['created_at']
                        duration_ms = int((event_timestamp - start_time).total_seconds() * 1000)
            
            elif "completed" in event.name or "failed" in event.name:
                async with c.cursor() as cur:
                    init_event_type = "workflow_initialized" if "workflow_" in event.name else "playbook_initialized"
                    await cur.execute("SELECT created_at FROM noetl.event WHERE execution_id = %s AND event_type = %s ORDER BY event_id ASC LIMIT 1", (int(event.execution_id), init_event_type))
                    init_event = await cur.fetchone()
                    if init_event and init_event['created_at']:
                        start_time = init_event['created_at']
                        duration_ms = int((event_timestamp - start_time).total_seconds() * 1000)

            async with c.cursor() as cur:
                await cur.execute("SELECT noetl.snowflake_id() AS snowflake_id")
                _sf_row = await cur.fetchone()
                if not _sf_row:
                    raise RuntimeError("Failed to generate snowflake ID")
                event_id = int(_sf_row['snowflake_id'])
            
            status = event.payload.get("status") if event.payload else None
            if not status and "completed" in event.name:
                status = "COMPLETED"
            elif not status and "failed" in event.name:
                status = "FAILED"
            elif not status:
                status = "RUNNING"
            
            # Map payload correctly: payload -> context, payload.result -> result
            payload_dict = event.payload if isinstance(event.payload, dict) else {}
            context_val = payload_dict
            result_val = payload_dict.get("result") if isinstance(payload_dict.get("result"), dict) and "status" in payload_dict["result"] else None

            async with c.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        execution_id, catalog_id, event_id, parent_event_id, parent_execution_id, 
                        created_at, event_type, node_id, node_name, status, duration, 
                        context, result, meta, error, worker_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        int(event.execution_id), catalog_id, event_id, parent_event_id, state.parent_execution_id,
                        event_timestamp, event.name, event.step, event.step, status, duration_ms,
                        Json(context_val) if context_val else None, 
                        Json(result_val) if result_val else None,
                        Json(event.meta) if event.meta else None,
                        event.payload.get("error") if isinstance(event.payload, dict) else None,
                        event.worker_id
                    )
                )
                await enqueue_executor_outbox(
                    cur,
                    {
                        "event_id": event_id,
                        "execution_id": int(event.execution_id),
                        "catalog_id": catalog_id,
                        "parent_event_id": parent_event_id,
                        "parent_execution_id": state.parent_execution_id,
                        "event_type": event.name,
                        "node_id": event.step,
                        "node_name": event.step,
                        "status": status,
                        "duration": duration_ms,
                        "context": context_val,
                        "result": result_val,
                        "meta": event.meta or {},
                        "error": event.payload.get("error") if isinstance(event.payload, dict) else None,
                        "worker_id": event.worker_id,
                        "event_time": event_timestamp,
                        "ingest_time": event_timestamp,
                        "created_at": event_timestamp,
                    },
                )

            state.last_event_id = event_id
            if event.step:
                state.step_event_ids[event.step] = event_id

        if conn is None:
            async with get_pool_connection() as c:
                await _do_persist(c)
            await drain_executor_outbox()
        else:
            await _do_persist(conn)

    async def _persist_cascade_events(
        self,
        events: list[Event],
        state: ExecutionState,
        conn=None,
    ) -> None:
        """Persist a cascade of related events with one batched ``INSERT``.

        Cascading completion chains (``workflow.completed`` ->
        ``playbook.completed`` and ``workflow.failed`` ->
        ``playbook.failed``) emit two events back-to-back inside one
        ``Engine.handle_event`` call.  Calling ``_persist_event_compat``
        twice does ~8 DB round-trips total (snowflake SELECT + duration
        SELECT + INSERT + outbox enqueue, x2).  Round-3 verification
        (noetl/ai-meta#29) measured ``persist_event_compat_ms`` p90 = 272ms
        for ``cg=0`` events — the single largest cost line.

        This method:
        - looks up ``catalog_id`` once (when missing)
        - allocates all snowflake IDs in one query
        - looks up the ``workflow_initialized`` / ``playbook_initialized``
          timestamp once and reuses it for every completion-shaped event
          in the cascade
        - chains ``parent_event_id`` through the batch in order
        - issues one ``executemany`` ``INSERT INTO noetl.event``
        - enqueues outbox rows in the same cursor
        - updates ``state.last_event_id`` to the final event's id

        For a 1-event "cascade" this falls through to the single-event
        path so callers can hand off a variable-length list without
        special-casing.
        """
        if not events:
            return
        if len(events) == 1 or conn is None:
            # Fallback path:
            # - single event: the batched path's reduced round-trips only
            #   pay off for cascades; one event has nothing to batch.
            # - no conn: the test environments that monkeypatch
            #   ``_persist_event`` drive the engine without a real DB
            #   connection.  Routing through ``_persist_event_compat`` lets
            #   those tests see cascade members the same way they see any
            #   other persisted event (via call_args / fake closures), and
            #   preserves the ``parent_event_id`` chain produced by the
            #   real ``_persist_event`` setting ``state.last_event_id``
            #   between calls.
            for event in events:
                await self._persist_event_compat(event, state, conn=conn)
            return

        catalog_id = state.catalog_id

        async def _do_persist_batch(c):
            nonlocal catalog_id
            if not catalog_id:
                async with c.cursor() as cur:
                    await cur.execute(
                        "SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1",
                        (int(events[0].execution_id),),
                    )
                    result = await cur.fetchone()
                    catalog_id = result["catalog_id"] if result else None
            if not catalog_id:
                logger.error(
                    "Cannot persist cascade events - no catalog_id for execution %s",
                    events[0].execution_id,
                )
                return

            # Pre-allocate one snowflake_id per event in a single query.
            async with c.cursor() as cur:
                await cur.execute(
                    "SELECT noetl.snowflake_id() AS snowflake_id "
                    "FROM generate_series(1, %s)",
                    (len(events),),
                )
                rows = await cur.fetchall()
                if not rows or len(rows) != len(events):
                    raise RuntimeError(
                        "Failed to allocate snowflake IDs for cascade batch"
                    )
                allocated_ids = [int(r["snowflake_id"]) for r in rows]

            # Resolve the shared init-event timestamp once per init kind.
            # workflow.* events look up workflow_initialized; playbook.*
            # events look up playbook_initialized.  Cache so a cascade of
            # workflow + playbook events does at most TWO lookups instead
            # of two per event.
            init_ts_cache: dict[str, Any] = {}

            async def _resolve_init_ts(event_name: str) -> Optional[Any]:
                init_event_type = (
                    "workflow_initialized"
                    if "workflow_" in event_name
                    else "playbook_initialized"
                )
                if init_event_type in init_ts_cache:
                    return init_ts_cache[init_event_type]
                async with c.cursor() as cur:
                    await cur.execute(
                        "SELECT created_at FROM noetl.event "
                        "WHERE execution_id = %s AND event_type = %s "
                        "ORDER BY event_id ASC LIMIT 1",
                        (int(events[0].execution_id), init_event_type),
                    )
                    init_row = await cur.fetchone()
                created_at = (
                    init_row["created_at"] if init_row else None
                )
                init_ts_cache[init_event_type] = created_at
                return created_at

            insert_rows: list[tuple] = []
            outbox_rows: list[dict[str, Any]] = []
            previous_event_id = state.last_event_id

            for idx, event in enumerate(events):
                new_event_id = allocated_ids[idx]
                parent_event_id = event.parent_event_id
                if parent_event_id is None:
                    if event.step:
                        parent_event_id = state.step_event_ids.get(event.step)
                    if not parent_event_id:
                        parent_event_id = previous_event_id

                event_timestamp = event.timestamp or datetime.now(timezone.utc)

                duration_ms = 0
                if "completed" in event.name or "failed" in event.name:
                    init_ts = await _resolve_init_ts(event.name)
                    if init_ts:
                        duration_ms = int(
                            (event_timestamp - init_ts).total_seconds() * 1000
                        )

                status = event.payload.get("status") if event.payload else None
                if not status and "completed" in event.name:
                    status = "COMPLETED"
                elif not status and "failed" in event.name:
                    status = "FAILED"
                elif not status:
                    status = "RUNNING"

                payload_dict = event.payload if isinstance(event.payload, dict) else {}
                context_val = payload_dict
                result_val = (
                    payload_dict.get("result")
                    if isinstance(payload_dict.get("result"), dict)
                    and "status" in payload_dict["result"]
                    else None
                )

                insert_rows.append(
                    (
                        int(event.execution_id),
                        catalog_id,
                        new_event_id,
                        parent_event_id,
                        state.parent_execution_id,
                        event_timestamp,
                        event.name,
                        event.step,
                        event.step,
                        status,
                        duration_ms,
                        Json(context_val) if context_val else None,
                        Json(result_val) if result_val else None,
                        Json(event.meta) if event.meta else None,
                        event.payload.get("error")
                        if isinstance(event.payload, dict)
                        else None,
                        event.worker_id,
                    )
                )
                outbox_rows.append(
                    {
                        "event_id": new_event_id,
                        "execution_id": int(event.execution_id),
                        "catalog_id": catalog_id,
                        "parent_event_id": parent_event_id,
                        "parent_execution_id": state.parent_execution_id,
                        "event_type": event.name,
                        "node_id": event.step,
                        "node_name": event.step,
                        "status": status,
                        "duration": duration_ms,
                        "context": context_val,
                        "result": result_val,
                        "meta": event.meta or {},
                        "error": event.payload.get("error")
                        if isinstance(event.payload, dict)
                        else None,
                        "worker_id": event.worker_id,
                        "event_time": event_timestamp,
                        "ingest_time": event_timestamp,
                        "created_at": event_timestamp,
                    }
                )
                # Subsequent events in the cascade chain to this id.
                previous_event_id = new_event_id

            async with c.cursor() as cur:
                await cur.executemany(
                    """
                    INSERT INTO noetl.event (
                        execution_id, catalog_id, event_id, parent_event_id, parent_execution_id,
                        created_at, event_type, node_id, node_name, status, duration,
                        context, result, meta, error, worker_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    insert_rows,
                )
                for outbox_event in outbox_rows:
                    await enqueue_executor_outbox(cur, outbox_event)

            # Update in-memory state to the final event in the cascade.
            for idx, event in enumerate(events):
                event_id = allocated_ids[idx]
                if event.step:
                    state.step_event_ids[event.step] = event_id
            state.last_event_id = allocated_ids[-1]

        t0 = time.perf_counter()
        try:
            if conn is None:
                async with get_pool_connection() as c:
                    await _do_persist_batch(c)
                await drain_executor_outbox()
            else:
                await _do_persist_batch(conn)
        finally:
            # Round-3 instrumentation: this batched path replaces 2x
            # _persist_event_compat calls.  Account for it under the same
            # field so operators can compare apples to apples in
            # batch.completed context.  We bump the call counter by the
            # number of events the cascade fused so the avg-calls metric
            # remains meaningful.
            elapsed = (time.perf_counter() - t0) * 1000
            accumulate_engine_phase_ms("persist_event_compat_ms", elapsed)
            # Bump the counter for any extra events beyond the first so
            # the *_calls average reflects the logical event count
            # (otherwise operators would see avg=1 once we cut over and
            # mistake it for "the events disappeared").
            for _ in range(len(events) - 1):
                accumulate_engine_phase_ms("persist_event_compat_ms", 0.0)

    async def start_execution(
        self,
        playbook_path: str,
        payload: dict[str, Any],
        catalog_id: Optional[int] = None,
        parent_execution_id: Optional[int] = None
    ) -> tuple[str, list[Command]]:
        """Start a new playbook execution."""
        execution_id = str(await get_snowflake_id())
        
        if catalog_id:
            playbook = await self.playbook_repo.load_playbook_by_id(catalog_id)
        else:
            playbook = await self.playbook_repo.load_playbook(playbook_path)
        
        if not playbook:
            raise ValueError(f"Playbook not found: catalog_id={catalog_id} path={playbook_path}")
        
        state = ExecutionState(execution_id, playbook, payload, catalog_id, parent_execution_id)
        
        # Initial save
        await self.state_store.save_state(state)

        if playbook.keychain and catalog_id:
            from noetl.server.keychain_processor import process_keychain_section
            try:
                keychain_manifest = await process_keychain_section(
                    keychain_section=playbook.keychain,
                    catalog_id=catalog_id,
                    execution_id=int(execution_id),
                    workload_vars=state.variables
                )
                if keychain_manifest:
                    state.variables[KEYCHAIN_MANIFEST_KEY] = keychain_manifest
            except Exception as e:
                logger.error(f"ENGINE: Failed to process keychain section: {e}")

        entry_step_name = playbook.get_entry_step()
        start_step = state.get_step(entry_step_name)
        if not start_step:
            raise ValueError(f"Entry step '{entry_step_name}' not found.")
        
        keychain_manifest = state.variables.get(KEYCHAIN_MANIFEST_KEY)
        workload_snapshot = {
            k: v if k == KEYCHAIN_MANIFEST_KEY else strip_keychain_namespaces(v, keychain_manifest)
            for k, v in state.variables.items()
            if not (isinstance(v, dict) and 'status' in v)
        }

        from noetl.core.dsl.engine.models import LifecycleEventPayload
        playbook_init_event = Event(
            execution_id=execution_id,
            step=playbook_path,
            name="playbook.initialized",
            payload=LifecycleEventPayload(
                status="initialized",
                result={"workload": workload_snapshot, "playbook_path": playbook_path}
            ).model_dump(),
            timestamp=datetime.now(timezone.utc)
        )
        await self._persist_event(playbook_init_event, state)
        
        workflow_init_event = Event(
            execution_id=execution_id,
            step="workflow",
            name="workflow.initialized",
            payload=LifecycleEventPayload(
                status="initialized",
                result={"first_step": entry_step_name, "playbook_path": playbook_path, "workload": workload_snapshot}
            ).model_dump(),
            timestamp=datetime.now(timezone.utc)
        )
        await self._persist_event(workflow_init_event, state)
        
        # Final save for initialization
        await self.state_store.save_state(state)
        
        commands = await self._issue_loop_commands(state, start_step, payload)
        
        # One last save to capture issued steps
        await self.state_store.save_state(state)
        
        return execution_id, commands
