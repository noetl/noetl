from __future__ import annotations
import yaml
import json

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
        metadata = playbook.metadata if isinstance(playbook.metadata, dict) else {}
        for alias in (metadata.get("path"), metadata.get("name")):
            if isinstance(alias, str) and alias:
                self._cache.set_sync(alias, playbook)

    async def load_playbook(self, path: str, conn=None) -> Optional[Playbook]:
        """Load playbook from catalog by path."""
        # Check cache first
        cached = await self._cache.get(path)
        if cached:
            return cached

        if conn is None:
            async with get_pool_connection() as c:
                async with c.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "SELECT content FROM noetl.catalog WHERE path = %s LIMIT 1",
                        (path,)
                    )
                    row = await cur.fetchone()
        else:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT content FROM noetl.catalog WHERE path = %s LIMIT 1",
                    (path,)
                )
                row = await cur.fetchone()

        if row:
            try:
                playbook_dict = yaml.safe_load(row["content"])
                api_version = playbook_dict.get("apiVersion")
                if api_version != "noetl.io/v2":
                    logger.error(f"Playbook {path} has unsupported apiVersion: {api_version}")
                    return None
                    
                playbook = Playbook(**playbook_dict)
                # Cache for future reads
                await self._cache.set(path, playbook)
                return playbook
            except Exception as e:
                logger.error(f"Failed to parse playbook {path}: {e}")
                return None
                
        return None

    async def load_playbook_by_id(self, catalog_id: int, conn=None) -> Optional[Playbook]:
        """Load playbook from catalog by ID."""
        # Check if we have it in cache
        cache_key = f"id:{catalog_id}"
        cached = await self._cache.get(cache_key)
        if cached:
            return cached

        if conn is None:
            async with get_pool_connection() as c:
                async with c.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "SELECT content, layout, path FROM noetl.catalog WHERE catalog_id = %s LIMIT 1",
                        (catalog_id,)
                    )
                    row = await cur.fetchone()
        else:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT content, layout, path FROM noetl.catalog WHERE catalog_id = %s LIMIT 1",
                    (catalog_id,)
                )
                row = await cur.fetchone()

        if row:
            try:
                playbook_dict = yaml.safe_load(row["content"])
                api_version = playbook_dict.get("apiVersion")
                if api_version != "noetl.io/v2":
                    logger.error(f"Playbook {catalog_id} has unsupported apiVersion: {api_version}")
                    return None
                    
                playbook = Playbook(**playbook_dict)
                # Add layout if available (for UI rendering)
                if row.get("layout"):
                    playbook.layout = row["layout"]
                    
                # Cache by ID
                await self._cache.set(cache_key, playbook)
                
                # Also cache by path for consistency
                if row.get("path"):
                    await self._cache.set(row["path"], playbook)
                    
                return playbook
            except Exception as e:
                logger.error(f"Failed to parse playbook {catalog_id}: {e}")
                return None
                
        return None


class StateStore:
    """Stores and retrieves execution state using Postgres JSONB column with row locking."""

    def __init__(self, playbook_repo: 'PlaybookRepo'):
        self.playbook_repo = playbook_repo

    async def save_state(self, state: ExecutionState, conn=None):
        import time
        import logging
        log = logging.getLogger(__name__)
        t0 = time.perf_counter()
        
        state_dict = state.to_dict()
        t1 = time.perf_counter()
        
        last_event_id = state.last_event_id

        # Keep the active playbook reachable from the local repo cache so state reloads
        # do not depend on a follow-up catalog lookup during tests or local fallback flows.
        if state.playbook is not None:
            if getattr(state, "catalog_id", None):
                self.playbook_repo.register(state.playbook, f"id:{state.catalog_id}")
            metadata = state.playbook.metadata if isinstance(getattr(state.playbook, "metadata", None), dict) else {}
            for alias in (metadata.get("path"), metadata.get("name")):
                if isinstance(alias, str) and alias:
                    self.playbook_repo.register(state.playbook, alias)
        
        # Determine status for SQL update
        status = "FAILED" if state.failed else ("COMPLETED" if state.completed else "RUNNING")
        
        sql = """
            UPDATE noetl.execution 
            SET state = %s, 
                updated_at = CURRENT_TIMESTAMP,
                end_time = CASE
                    WHEN noetl.execution.end_time IS NULL AND %s IN ('COMPLETED', 'FAILED', 'CANCELLED') THEN CURRENT_TIMESTAMP
                    ELSE noetl.execution.end_time
                END,
                status = CASE 
                    WHEN status IN ('COMPLETED', 'FAILED', 'CANCELLED') THEN status 
                    ELSE %s 
                END,
                last_event_id = GREATEST(COALESCE(last_event_id, 0), %s)
            WHERE execution_id = %s
        """
        import json
        t2 = time.perf_counter()
        json_str = json.dumps(state_dict)
        t3 = time.perf_counter()
        params = (json_str, status, status, last_event_id, int(state.execution_id))

        
        if conn is None:
            async with get_pool_connection() as c:
                async with c.cursor() as cur:
                    await cur.execute(sql, params)
        else:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                
        t4 = time.perf_counter()
        log.info(f"[PERF] save_state total={t4-t0:.3f}s to_dict={t1-t0:.3f}s dumps={t3-t2:.3f}s db={t4-t3:.3f}s")


        logger.debug(f"[STATE-SAVE] State saved to Postgres for execution {state.execution_id}")

    async def should_refresh_cached_state(self, execution_id: str, last_event_id: Optional[int], allowed_missing_events: int = 1) -> bool:
        return False

    @staticmethod
    def _extract_init_workload(init_event: dict[str, Any]) -> dict[str, Any]:
        context = init_event.get("context")
        if isinstance(context, dict) and isinstance(context.get("workload"), dict):
            return dict(context["workload"])

        result = init_event.get("result")
        if isinstance(result, dict) and isinstance(result.get("workload"), dict):
            return dict(result["workload"])

        return {}

    async def _normalize_replay_result(self, value: Any) -> Any:
        current = value
        if isinstance(current, dict) and current.get("kind") in {"data", "ref", "refs"} and "data" in current:
            current = current.get("data")

        if isinstance(current, dict) and isinstance(current.get("reference"), dict):
            locator = current["reference"].get("locator") or current["reference"].get("ref")
            if locator:
                try:
                    resolved = await default_store.resolve({"ref": locator})
                    if resolved is not None:
                        current = resolved
                except Exception:
                    pass

        if isinstance(current, dict):
            if current.get("kind") in {"data", "ref", "refs"} and "data" in current:
                current = current.get("data")
            if isinstance(current.get("result"), dict):
                result_payload = dict(current.get("result") or {})
                flattened = dict(result_payload)
                flattened["result"] = result_payload
                flattened["data"] = dict(current)
                if "status" in current:
                    flattened["status"] = current.get("status")
                if isinstance(current.get("context"), dict):
                    flattened["context"] = dict(current.get("context") or {})
                    for key, item in flattened["context"].items():
                        if str(key).startswith("command_"):
                            flattened.setdefault(key, item)
                current = flattened
            context_payload = current.get("context")
            if isinstance(context_payload, dict):
                flattened = dict(current)
                for key, item in context_payload.items():
                    if str(key).startswith("command_"):
                        flattened.setdefault(key, item)
                current = flattened

        return current

    async def _replay_execution_events(
        self,
        state: ExecutionState,
        cursor,
    ) -> ExecutionState:
        from noetl.core.dsl.render import render_template as recursive_render

        await cursor.execute(
            """
            SELECT event_id, node_name, event_type, result, meta
            FROM noetl.event
            WHERE execution_id = %s
              AND event_type = ANY(%s)
            ORDER BY event_id ASC
            """,
            (int(state.execution_id), list(_STATE_REPLAY_EVENT_TYPES)),
        )
        rows = await cursor.fetchall()
        jinja_env = Environment(undefined=StrictUndefined)

        for row in rows:
            event_id = row.get("event_id")
            node_name = row.get("node_name")
            event_type = row.get("event_type")
            meta = row.get("meta") or {}

            if event_id is not None:
                state.last_event_id = int(event_id)
                if node_name:
                    state.step_event_ids[str(node_name)] = int(event_id)

            pending_key = _pending_step_key(node_name)
            if event_type == "command.issued":
                if pending_key:
                    state.issued_steps.add(pending_key)
                if isinstance(node_name, str) and node_name.endswith(":task_sequence"):
                    parent_step = node_name.rsplit(":", 1)[0]
                    parent_def = state.get_step(parent_step)
                    if parent_def and getattr(parent_def, "loop", None) and parent_step not in state.loop_state:
                        state.loop_state[parent_step] = {
                            "collection": [],
                            "iterator": parent_def.loop.iterator,
                            "index": 0,
                            "mode": parent_def.loop.mode,
                            "completed": False,
                            "results": [],
                            "failed_count": 0,
                            "break_count": 0,
                            "scheduled_count": 0,
                            "event_id": meta.get("loop_event_id") or meta.get("__loop_epoch_id"),
                            "omitted_results_count": 0,
                            "aggregation_finalized": False,
                        }
                continue

            if event_type in {"command.completed", "command.cancelled"}:
                if pending_key:
                    state.completed_steps.add(pending_key)
                continue

            if event_type == "command.failed":
                if pending_key:
                    state.completed_steps.add(pending_key)
                state.failed = True
                continue

            if event_type in {"workflow.failed", "playbook.failed"}:
                state.failed = True
                state.completed = True
                continue

            if event_type in {"workflow.completed", "playbook.completed", "execution.cancelled"}:
                state.completed = True
                continue

            if event_type not in {"step.exit", "call.done"} or not node_name:
                continue

            normalized_result = await self._normalize_replay_result(row.get("result"))

            if str(node_name).endswith(":task_sequence") and event_type == "step.exit":
                # task_sequence step.exit is an internal worker artifact, not a terminal step result
                continue

            state.mark_step_completed(str(node_name), normalized_result)

            step_def = state.get_step(str(node_name))
            if step_def and getattr(step_def, "loop", None):
                if step_def.step not in state.loop_state:
                    state.loop_state[step_def.step] = {
                        "collection": [],
                        "iterator": step_def.loop.iterator,
                        "index": 0,
                        "mode": step_def.loop.mode,
                        "completed": False,
                        "results": [],
                        "failed_count": 0,
                        "break_count": 0,
                        "scheduled_count": 0,
                        "event_id": None,
                        "omitted_results_count": 0,
                        "aggregation_finalized": False,
                    }
                loop_result = normalized_result
                if isinstance(normalized_result, dict) and isinstance(normalized_result.get("result"), dict):
                    loop_result = normalized_result["result"]
                state.add_loop_result(step_def.step, loop_result)
                completed_count = state.get_loop_completed_count(step_def.step)
                state.loop_state[step_def.step]["index"] = completed_count
                state.loop_state[step_def.step]["scheduled_count"] = completed_count

            if step_def and getattr(step_def, "set", None):
                replay_event = Event(
                    execution_id=state.execution_id,
                    step=str(node_name),
                    name=str(event_type),
                    payload={"result": normalized_result} if normalized_result is not None else {},
                )
                context = state.get_render_context(replay_event)
                rendered_set = recursive_render(jinja_env, step_def.set, context)
                _apply_set_mutations(state.variables, rendered_set)

        return state

    async def _load_state_from_init_event(
        self,
        execution_id: str,
        init_event: dict[str, Any],
        conn,
    ) -> Optional[ExecutionState]:
        catalog_id = init_event.get("catalog_id")
        try:
            playbook = await self.playbook_repo.load_playbook_by_id(catalog_id, conn)
        except TypeError:
            playbook = await self.playbook_repo.load_playbook_by_id(catalog_id)
        if not playbook:
            return None

        workload = self._extract_init_workload(init_event)
        state = ExecutionState(execution_id, playbook, workload, catalog_id)
        async with conn.cursor(row_factory=dict_row) as replay_cursor:
            return await self._replay_execution_events(state, replay_cursor)
    
    async def load_state(self, execution_id: str, conn=None) -> Optional[ExecutionState]:
        """Load execution state from Postgres. Does NOT lock."""
        if conn is None:
            async with get_pool_connection() as c:
                async with c.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "SELECT state, catalog_id FROM noetl.execution WHERE execution_id = %s",
                        (int(execution_id),)
                    )
                    row = await cur.fetchone()
                    
                    if row and row.get("state"):
                        catalog_id = row.get("catalog_id")
                        if catalog_id:
                            playbook = await self.playbook_repo.load_playbook_by_id(catalog_id, c)
                            if playbook:
                                return ExecutionState.from_dict(row["state"], playbook)
                        playbook_path = (row.get("state") or {}).get("playbook_path")
                        if playbook_path:
                            playbook = await self.playbook_repo.load_playbook(playbook_path, c)
                            if playbook:
                                return ExecutionState.from_dict(row["state"], playbook)
                    
                    await cur.execute("""
                        SELECT catalog_id, context, result
                        FROM noetl.event
                        WHERE execution_id = %s AND event_type = 'playbook.initialized'
                        LIMIT 1
                    """, (int(execution_id),))
                    init_event = await cur.fetchone()
                    if init_event:
                        return await self._load_state_from_init_event(execution_id, init_event, c)
        else:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT state, catalog_id FROM noetl.execution WHERE execution_id = %s",
                    (int(execution_id),)
                )
                row = await cur.fetchone()
                
                if row and row.get("state"):
                    catalog_id = row.get("catalog_id")
                    if catalog_id:
                        playbook = await self.playbook_repo.load_playbook_by_id(catalog_id, conn)
                        if playbook:
                            return ExecutionState.from_dict(row["state"], playbook)
                    playbook_path = (row.get("state") or {}).get("playbook_path")
                    if playbook_path:
                        playbook = await self.playbook_repo.load_playbook(playbook_path, conn)
                        if playbook:
                            return ExecutionState.from_dict(row["state"], playbook)
                
                await cur.execute("""
                    SELECT catalog_id, context, result
                    FROM noetl.event
                    WHERE execution_id = %s AND event_type = 'playbook.initialized'
                    LIMIT 1
                """, (int(execution_id),))
                init_event = await cur.fetchone()
                if init_event:
                    return await self._load_state_from_init_event(execution_id, init_event, conn)
        return None

    async def load_state_for_update(self, execution_id: str, conn) -> Optional[ExecutionState]:
        """Load execution state and lock the row FOR UPDATE. Must be used within a transaction."""
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT state, catalog_id FROM noetl.execution WHERE execution_id = %s FOR UPDATE",
                (int(execution_id),)
            )
            row = await cur.fetchone()
            
            if row and row.get("state"):
                catalog_id = row.get("catalog_id")
                if catalog_id:
                    playbook = await self.playbook_repo.load_playbook_by_id(catalog_id, conn)
                    if playbook:
                        return ExecutionState.from_dict(row["state"], playbook)
                playbook_path = (row.get("state") or {}).get("playbook_path")
                if playbook_path:
                    playbook = await self.playbook_repo.load_playbook(playbook_path, conn)
                    if playbook:
                        return ExecutionState.from_dict(row["state"], playbook)

            # Fallback to init event
            await cur.execute("""
                SELECT catalog_id, context, result
                FROM noetl.event
                WHERE execution_id = %s AND event_type = 'playbook.initialized'
                LIMIT 1
            """, (int(execution_id),))
            init_event = await cur.fetchone()
            if init_event:
                return await self._load_state_from_init_event(execution_id, init_event, conn)
                    
        return None

    def get_state(self, execution_id: str) -> Optional[ExecutionState]:
        """DEPRECATED."""
        return None

    async def evict_completed(self, execution_id: str):
        pass

    async def invalidate_state(self, execution_id: str, reason: str = "manual") -> bool:
        return True
