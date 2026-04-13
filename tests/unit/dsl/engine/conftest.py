import json
import pytest
from contextlib import asynccontextmanager

class _StatefulCursor:
    def __init__(self, db):
        self._db = db
        self._one = None
        self._all = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, query, params=None):
        sql = " ".join(str(query).split())
        self._one = None
        self._all = []

        if sql.startswith("UPDATE noetl.execution"):
            state_json, status, _status_dup, last_event_id, execution_id = params
            state = json.loads(state_json) if isinstance(state_json, str) else state_json
            self._db["executions"][str(execution_id)] = {
                "state": state,
                "catalog_id": state.get("catalog_id"),
                "status": status,
                "last_event_id": last_event_id,
            }
            return

        if "SELECT state, catalog_id FROM noetl.execution" in sql:
            execution_id = str(params[0])
            row = self._db["executions"].get(execution_id)
            self._one = dict(row) if row is not None else None
            return

        if "SELECT catalog_id, context, result FROM noetl.event" in sql and "playbook.initialized" in sql:
            self._one = None
            return

        if "pending_count" in sql:
            self._one = {"pending_count": self._db.get("pending_count", 0)}
            return

    async def fetchone(self):
        return self._one

    async def fetchall(self):
        return list(self._all)


class _StatefulConnection:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def cursor(self, row_factory=None):  # noqa: ARG002
        return _StatefulCursor(self._db)


@asynccontextmanager
async def _mock_pool_connection(db):
    yield _StatefulConnection(db)

@pytest.fixture(autouse=True)
def mock_db_pool(monkeypatch):
    """Globally mock DB pool for all engine tests."""
    print("\nDEBUG: conftest.py mock_db_pool loaded")
    db = {"pending_count": 0, "executions": {}}
    monkeypatch.setattr("noetl.core.db.pool.get_pool_connection", lambda: _mock_pool_connection(db))
    monkeypatch.setattr("noetl.core.dsl.engine.executor.get_pool_connection", lambda: _mock_pool_connection(db))

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
    
    # Patch the public re-export; executor modules now resolve via the source module.
    import noetl.core.cache
    monkeypatch.setattr(noetl.core.cache, "get_nats_cache", _get_nats_cache)
