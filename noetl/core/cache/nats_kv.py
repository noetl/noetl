"""
NATS K/V cache for distributed execution state.

Replaces in-memory cache with distributed NATS JetStream K/V store
to enable horizontal scaling of server pods.

IMPORTANT: NATS K/V has a 1MB max value size limit. This module stores ONLY:
- Loop metadata (collection_size, iterator, mode)
- Completion counts (completed_count integer)
- Pointers/references (event_id, execution_id)

NEVER store actual result values in NATS K/V - they are stored in the
event table and retrieved via the aggregate service when needed.
"""

import json
import asyncio
from typing import Any, Optional
from datetime import datetime, timezone
import nats
from nats.js import JetStreamContext
from nats.js.kv import KeyValue
from noetl.core.logger import setup_logger
from noetl.core.config import get_settings

logger = setup_logger(__name__, include_location=True)
settings = get_settings()

class NATSKVCache:
    """NATS K/V cache client for execution state."""
    
    def __init__(self):
        self._nc: Optional[nats.NATS] = None
        self._js: Optional[JetStreamContext] = None
        self._kv: Optional[KeyValue] = None
        self._bucket_name = "noetl_execution_state"
        self._lock = asyncio.Lock()
    
    async def connect(self, nats_url: Optional[str] = None):
        """Connect to NATS and create/get K/V bucket."""
        async with self._lock:
            if self._nc is not None:
                return  # Already connected
            
            try:
                # Use settings from config.py
                url = nats_url or settings.nats_url
                user = settings.nats_user
                password = settings.nats_password
                
                self._nc = await nats.connect(
                    servers=[url],
                    user=user,
                    password=password,
                    name="noetl_kv_cache"
                )
                self._js = self._nc.jetstream()
                
                # Create or get K/V bucket with TTL
                try:
                    self._kv = await self._js.create_key_value(
                        bucket=self._bucket_name,
                        description="NoETL execution state cache",
                        ttl=3600,  # 1 hour TTL
                        max_value_size=1024 * 1024,  # 1MB max value
                        history=5,  # Keep 5 versions
                    )
                    logger.debug(f"Created NATS K/V bucket: {self._bucket_name}")
                except Exception as e:
                    # Bucket might already exist
                    self._kv = await self._js.key_value(self._bucket_name)
                    logger.info(f"Connected to existing NATS K/V bucket: {self._bucket_name}")
                
                logger.info(f"NATS K/V cache connected to {url} (user: {user})")
                
            except Exception as e:
                logger.error(f"Failed to connect to NATS K/V: {e}")
                raise
    
    async def close(self):
        """Close NATS connection."""
        if self._nc:
            await self._nc.close()
            self._nc = None
            self._js = None
            self._kv = None
    
    def _make_key(self, execution_id: str, key_type: str) -> str:
        """Create namespaced key for execution state.
        
        NATS K/V keys must use dots as separators, not colons.
        Format: exec.{execution_id}.{key_type}
        """
        # Replace colons with dots in key_type (for nested keys like "loop:step:event")
        safe_key_type = key_type.replace(":", ".")
        return f"exec.{execution_id}.{safe_key_type}"
    
    async def get_loop_state(self, execution_id: str, step_name: str, event_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Get loop state for a specific step instance.
        
        Args:
            execution_id: Execution identifier
            step_name: Name of the step
            event_id: Event ID that initiated this step instance (for uniqueness)
        """
        if not self._kv:
            await self.connect()
        
        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)
        try:
            entry = await self._kv.get(key)
            if entry and entry.value:
                return json.loads(entry.value.decode('utf-8'))
            return None
        except Exception as e:
            logger.warning(f"Failed to get loop state from NATS K/V: {e}")
            return None
    
    async def set_loop_state(self, execution_id: str, step_name: str, state: dict[str, Any], event_id: Optional[str] = None) -> bool:
        """Set loop state for a specific step instance.

        IMPORTANT: state should contain only metadata and counts, NOT result values:
        - collection_size: int - number of items in the loop collection
        - completed_count: int - number of completed iterations
        - scheduled_count: int - number of claimed/issued iterations
        - iterator: str - iterator variable name
        - mode: str - sequential or parallel
        - event_id: str - event ID that initiated this loop

        NEVER include 'results' array with actual values - those belong in the event table.

        Args:
            execution_id: Execution identifier
            step_name: Name of the step
            state: Loop state dictionary (metadata only, no result values)
            event_id: Event ID that initiated this step instance (for uniqueness)
        """
        if not self._kv:
            await self.connect()

        # Safety check: warn and strip results if accidentally included
        if "results" in state:
            logger.warning(f"[NATS-KV] Stripping 'results' array from loop state for {step_name} - use completed_count instead")
            state = {k: v for k, v in state.items() if k != "results"}

        # Backward compatibility for older state payloads.
        if "completed_count" not in state:
            state["completed_count"] = 0
        if "scheduled_count" not in state:
            state["scheduled_count"] = state.get("completed_count", 0)

        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)
        try:
            value = json.dumps(state).encode('utf-8')
            await self._kv.put(key, value)
            logger.debug(f"Stored loop state in NATS K/V: {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to set loop state in NATS K/V: {e}")
            return False
    
    async def increment_loop_completed(self, execution_id: str, step_name: str, event_id: Optional[str] = None) -> int:
        """Atomically increment the completed_count for a loop.

        This replaces the old append_loop_result which stored actual results.
        NATS K/V now only tracks the count of completed iterations - actual
        results are stored in the event table and fetched via aggregate service.

        Args:
            execution_id: Execution identifier
            step_name: Name of the step
            event_id: Event ID that initiated this step instance (for uniqueness)

        Returns:
            The new completed_count value, or -1 on failure
        """
        if not self._kv:
            await self.connect()

        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)

        # Read-modify-write with retry logic (optimistic locking)
        max_retries = 5
        for attempt in range(max_retries):
            try:
                # Get current state
                entry = await self._kv.get(key)
                if not entry:
                    logger.warning(f"Loop state not found for {step_name}, cannot increment count")
                    return -1

                state = json.loads(entry.value.decode('utf-8'))

                # Increment completed count
                current_count = state.get("completed_count", 0)
                state["completed_count"] = current_count + 1
                scheduled_count = int(state.get("scheduled_count", state["completed_count"]) or state["completed_count"])
                if scheduled_count < state["completed_count"]:
                    scheduled_count = state["completed_count"]
                state["scheduled_count"] = scheduled_count

                # Update with revision check (optimistic locking)
                value = json.dumps(state).encode('utf-8')
                await self._kv.update(key, value, last=entry.revision)

                logger.debug(f"Incremented loop completed count: {key}, completed_count={state['completed_count']}")
                return state["completed_count"]

            except Exception as e:
                if "wrong last sequence" in str(e).lower() and attempt < max_retries - 1:
                    # Concurrent update, retry
                    await asyncio.sleep(0.01 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    logger.error(f"Failed to increment loop completed count: {e}")
                    return -1

        return -1

    async def claim_next_loop_index(
        self,
        execution_id: str,
        step_name: str,
        collection_size: int,
        max_in_flight: int,
        event_id: Optional[str] = None,
    ) -> Optional[int]:
        """Atomically claim the next loop iteration index with backpressure control.

        Returns:
            Claimed zero-based index, or None when no slot is currently available.
        """
        if not self._kv:
            await self.connect()

        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)

        safe_collection_size = max(0, int(collection_size or 0))
        safe_max_in_flight = max(1, int(max_in_flight or 1))

        max_retries = 5
        for attempt in range(max_retries):
            try:
                entry = await self._kv.get(key)
                if not entry:
                    return None

                state = json.loads(entry.value.decode("utf-8"))

                completed_count = int(state.get("completed_count", 0) or 0)
                scheduled_count = int(state.get("scheduled_count", completed_count) or completed_count)

                # Ensure state is coherent even if old payloads omitted fields.
                if scheduled_count < completed_count:
                    scheduled_count = completed_count
                state["completed_count"] = completed_count
                state["scheduled_count"] = scheduled_count

                if safe_collection_size <= 0:
                    state["collection_size"] = safe_collection_size
                    value = json.dumps(state).encode("utf-8")
                    await self._kv.update(key, value, last=entry.revision)
                    return None

                if scheduled_count >= safe_collection_size:
                    return None

                in_flight = max(0, scheduled_count - completed_count)
                if in_flight >= safe_max_in_flight:
                    return None

                claimed_index = scheduled_count
                state["collection_size"] = safe_collection_size
                state["scheduled_count"] = scheduled_count + 1

                value = json.dumps(state).encode("utf-8")
                await self._kv.update(key, value, last=entry.revision)
                return claimed_index

            except Exception as e:
                if "wrong last sequence" in str(e).lower() and attempt < max_retries - 1:
                    await asyncio.sleep(0.01 * (attempt + 1))
                    continue
                logger.error(f"Failed to claim next loop index: {e}")
                return None

        return None

    async def get_loop_completed_count(self, execution_id: str, step_name: str, event_id: Optional[str] = None) -> int:
        """Get the completed iteration count for a loop.

        Args:
            execution_id: Execution identifier
            step_name: Name of the step
            event_id: Event ID that initiated this step instance (for uniqueness)

        Returns:
            The completed_count value, or 0 if not found
        """
        state = await self.get_loop_state(execution_id, step_name, event_id)
        if state:
            return state.get("completed_count", 0)
        return 0
    
    async def delete_execution_state(self, execution_id: str):
        """Delete all state for an execution (cleanup)."""
        if not self._kv:
            await self.connect()
        
        # Delete all keys for this execution (using dot separator)
        prefix = f"exec.{execution_id}."
        try:
            keys = await self._kv.keys()
            for key in keys:
                if key.startswith(prefix):
                    await self._kv.delete(key)
            logger.debug(f"Deleted execution state from NATS K/V: {execution_id}")
        except Exception as e:
            logger.warning(f"Failed to delete execution state: {e}")


# Global cache instance
_nats_cache: Optional[NATSKVCache] = None
_init_lock = asyncio.Lock()


async def get_nats_cache() -> NATSKVCache:
    """Get or create global NATS K/V cache instance."""
    global _nats_cache
    
    async with _init_lock:
        if _nats_cache is None:
            _nats_cache = NATSKVCache()
            # Get NATS URL from environment
            import os
            nats_url = os.getenv("NATS_URL", "nats://nats.nats.svc.cluster.local:4222")
            await _nats_cache.connect(nats_url)
        
        return _nats_cache


async def close_nats_cache():
    """Close global NATS K/V cache connection."""
    global _nats_cache
    if _nats_cache:
        await _nats_cache.close()
        _nats_cache = None
