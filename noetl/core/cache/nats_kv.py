"""
NATS K/V cache for distributed execution state.

Replaces in-memory cache with distributed NATS JetStream K/V store
to enable horizontal scaling of server pods.
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
        
        Args:
            execution_id: Execution identifier
            step_name: Name of the step
            state: Loop state dictionary
            event_id: Event ID that initiated this step instance (for uniqueness)
        """
        if not self._kv:
            await self.connect()
        
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
    
    async def append_loop_result(self, execution_id: str, step_name: str, result: Any, event_id: Optional[str] = None) -> bool:
        """Atomically append result to loop results array.
        
        Args:
            execution_id: Execution identifier
            step_name: Name of the step
            result: Result to append
            event_id: Event ID that initiated this step instance (for uniqueness)
        """
        if not self._kv:
            await self.connect()
        
        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)
        
        # Read-modify-write with retry logic
        max_retries = 5
        for attempt in range(max_retries):
            try:
                # Get current state
                entry = await self._kv.get(key)
                if not entry:
                    logger.warning(f"Loop state not found for {step_name}, cannot append result")
                    return False
                
                state = json.loads(entry.value.decode('utf-8'))
                
                # Append result
                if "results" not in state:
                    state["results"] = []
                state["results"].append(result)
                
                # Update with revision check (optimistic locking)
                value = json.dumps(state).encode('utf-8')
                await self._kv.update(key, value, last=entry.revision)
                
                logger.debug(f"Appended result to loop state: {key}, results_count={len(state['results'])}")
                return True
                
            except Exception as e:
                if "wrong last sequence" in str(e).lower() and attempt < max_retries - 1:
                    # Concurrent update, retry
                    await asyncio.sleep(0.01 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    logger.error(f"Failed to append loop result: {e}")
                    return False
        
        return False
    
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
