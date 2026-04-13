import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

@asynccontextmanager
async def _mock_pool_connection(pending_count: int = 0):
    """Async context manager that returns a fake DB connection/cursor yielding pending_count."""
    cur = AsyncMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    cur.fetchone = AsyncMock(return_value={"pending_count": pending_count})
    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cur)
    yield conn

@pytest.fixture(autouse=True)
def mock_db_pool(monkeypatch):
    """Globally mock DB pool for all engine tests."""
    print("\nDEBUG: conftest.py mock_db_pool loaded")
    monkeypatch.setattr("noetl.core.db.pool.get_pool_connection", lambda: _mock_pool_connection(0))
    # Also monkeypatch where it might have been already imported
    monkeypatch.setattr("noetl.core.dsl.engine.executor.common.get_pool_connection", lambda: _mock_pool_connection(0))
    monkeypatch.setattr("noetl.core.dsl.engine.executor.store.get_pool_connection", lambda: _mock_pool_connection(0))
    monkeypatch.setattr("noetl.core.dsl.engine.executor.control_flow.get_pool_connection", lambda: _mock_pool_connection(0))
    monkeypatch.setattr("noetl.core.dsl.engine.executor.events.get_pool_connection", lambda: _mock_pool_connection(0))
    monkeypatch.setattr("noetl.core.dsl.engine.executor.commands.get_pool_connection", lambda: _mock_pool_connection(0))
    monkeypatch.setattr("noetl.core.dsl.engine.executor.transitions.get_pool_connection", lambda: _mock_pool_connection(0))

@pytest.fixture(autouse=True)
def mock_nats(monkeypatch):
    """Globally mock NATS for all engine tests."""
    class _NoopNatsCache:
        def __init__(self):
            self.collections = {}
            self.states = {}
            self.completed_counts = {}
            self.scheduled_counts = {}
            
        async def get_loop_collection(self, execution_id, step_name, loop_event_id):
            return self.collections.get(f"{execution_id}:{step_name}:{loop_event_id}")
            
        async def save_loop_collection(self, execution_id, step_name, loop_event_id, collection):
            self.collections[f"{execution_id}:{step_name}:{loop_event_id}"] = collection
            
        async def get_loop_state(self, execution_id, step_name, event_id=None):
            return self.states.get(f"{execution_id}:{step_name}:{event_id}")
            
        async def set_loop_state(self, execution_id, step_name, state, event_id=None):
            self.states[f"{execution_id}:{step_name}:{event_id}"] = state
            return True
            
        async def get_loop_completed_count(self, execution_id, step_name, event_id=None):
            return self.completed_counts.get(f"{execution_id}:{step_name}:{event_id}", 0)
            
        async def increment_loop_completed(self, execution_id, step_name, event_id=None):
            key = f"{execution_id}:{step_name}:{event_id}"
            count = self.completed_counts.get(key, 0) + 1
            self.completed_counts[key] = count
            return count
            
        async def claim_next_loop_index(self, execution_id, step_name, collection_size, max_in_flight, event_id=None):
            key = f"{execution_id}:{step_name}:{event_id}"
            scheduled = self.scheduled_counts.get(key, 0)
            completed = self.completed_counts.get(key, 0)
            if scheduled < collection_size and (scheduled - completed) < max_in_flight:
                self.scheduled_counts[key] = scheduled + 1
                return scheduled
            return None
            
        async def get_pending_command_count(self, execution_id):
            return 0
            
        async def connect(self): pass
        async def close(self): pass
        async def get_execution_state(self, *args, **kwargs): return None
        async def set_execution_state(self, *args, **kwargs): return True
        async def register_command_issued(self, *args, **kwargs): return True
        async def mark_command_terminal(self, *args, **kwargs): return True
    
    async def _get_nats_cache(): return _NoopNatsCache()
    
    # Patch the source
    monkeypatch.setattr("noetl.core.cache.nats_kv.get_nats_cache", _get_nats_cache)
    
    # Patch all known re-exports and imports
    import noetl.core.cache
    monkeypatch.setattr(noetl.core.cache, "get_nats_cache", _get_nats_cache)
    
    import noetl.core.dsl.engine.executor.common
    monkeypatch.setattr(noetl.core.dsl.engine.executor.common, "get_nats_cache", _get_nats_cache)
    
    import noetl.core.dsl.engine.executor.transitions
    monkeypatch.setattr(noetl.core.dsl.engine.executor.transitions, "get_nats_cache", _get_nats_cache)
    
    import noetl.core.dsl.engine.executor.commands
    monkeypatch.setattr(noetl.core.dsl.engine.executor.commands, "get_nats_cache", _get_nats_cache)
    
    import noetl.core.dsl.engine.executor.events
    monkeypatch.setattr(noetl.core.dsl.engine.executor.events, "get_nats_cache", _get_nats_cache)
    
    import noetl.core.dsl.engine.executor.store
    monkeypatch.setattr(noetl.core.dsl.engine.executor.store, "get_nats_cache", _get_nats_cache)
