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
        path = playbook.metadata.get("path") if isinstance(playbook.metadata, dict) else None
        if isinstance(path, str) and path:
            self._cache.set_sync(path, playbook)

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
        """Save execution state to Postgres execution table."""
        state_dict = state.to_dict()
        last_event_id = state.last_event_id
        
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
        params = (json.dumps(state_dict), status, status, last_event_id, int(state.execution_id))
        
        if conn is None:
            async with get_pool_connection() as c:
                async with c.cursor() as cur:
                    await cur.execute(sql, params)
        else:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)

        logger.debug(f"[STATE-SAVE] State saved to Postgres for execution {state.execution_id}")

    async def should_refresh_cached_state(self, execution_id: str, last_event_id: Optional[int], allowed_missing_events: int = 1) -> bool:
        return False
    
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
                    
                    await cur.execute("""
                        SELECT catalog_id, context, result
                        FROM noetl.event
                        WHERE execution_id = %s AND event_type = 'playbook.initialized'
                        LIMIT 1
                    """, (int(execution_id),))
                    init_event = await cur.fetchone()
                    if init_event:
                        catalog_id = init_event.get("catalog_id")
                        playbook = await self.playbook_repo.load_playbook_by_id(catalog_id, c)
                        if playbook:
                            workload = init_event.get("context", {}).get("workload", {}) if init_event.get("context") else {}
                            state = ExecutionState(execution_id, playbook, workload, catalog_id)
                            return state
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
                
                await cur.execute("""
                    SELECT catalog_id, context, result
                    FROM noetl.event
                    WHERE execution_id = %s AND event_type = 'playbook.initialized'
                    LIMIT 1
                """, (int(execution_id),))
                init_event = await cur.fetchone()
                if init_event:
                    catalog_id = init_event.get("catalog_id")
                    playbook = await self.playbook_repo.load_playbook_by_id(catalog_id, conn)
                    if playbook:
                        workload = init_event.get("context", {}).get("workload", {}) if init_event.get("context") else {}
                        state = ExecutionState(execution_id, playbook, workload, catalog_id)
                        return state
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

            # Fallback to init event
            await cur.execute("""
                SELECT catalog_id, context, result
                FROM noetl.event
                WHERE execution_id = %s AND event_type = 'playbook.initialized'
                LIMIT 1
            """, (int(execution_id),))
            init_event = await cur.fetchone()
            if init_event:
                catalog_id = init_event.get("catalog_id")
                playbook = await self.playbook_repo.load_playbook_by_id(catalog_id, conn)
                if playbook:
                    workload = init_event.get("context", {}).get("workload", {}) if init_event.get("context") else {}
                    state = ExecutionState(execution_id, playbook, workload, catalog_id)
                    return state
                    
        return None

    def get_state(self, execution_id: str) -> Optional[ExecutionState]:
        """DEPRECATED."""
        return None

    async def evict_completed(self, execution_id: str):
        pass

    async def invalidate_state(self, execution_id: str, reason: str = "manual") -> bool:
        return True
