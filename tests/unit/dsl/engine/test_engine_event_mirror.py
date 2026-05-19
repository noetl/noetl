from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from noetl.core.dsl.engine.models import Event


class _CursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Cursor:
    def __init__(self):
        self.query = ""
        self.inserts = []

    async def execute(self, query, params=None):
        self.query = query
        if "INSERT INTO noetl.event" in query:
            self.inserts.append(params)

    async def fetchone(self):
        if "noetl.snowflake_id()" in self.query:
            return {"snowflake_id": 101}
        return None


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, **_kwargs):
        return _CursorCtx(self._cursor)


class _Engine:
    from noetl.core.dsl.engine.executor.lifecycle import LifecycleMixin

    _persist_event = LifecycleMixin._persist_event


@pytest.mark.asyncio
async def test_engine_owned_persist_event_mirrors_after_connection_context(monkeypatch):
    import noetl.core.dsl.engine.executor.lifecycle as lifecycle

    cursor = _Cursor()
    mirrored = []

    async def fake_mirror(events):
        mirrored.extend(events)

    monkeypatch.setattr(lifecycle, "get_pool_connection", lambda: _ConnCtx(_Conn(cursor)))
    monkeypatch.setattr(lifecycle, "_mirror_engine_events", fake_mirror)

    state = SimpleNamespace(
        catalog_id=5,
        parent_execution_id=None,
        step_event_ids={},
        last_event_id=77,
        loop_state={},
    )
    event_time = datetime(2026, 5, 18, 20, 0, tzinfo=timezone.utc)

    await _Engine()._persist_event(
        Event(
            execution_id="7",
            step="workflow",
            name="workflow.initialized",
            payload={"status": "initialized", "result": {"status": "RUNNING"}},
            meta={"stage_id": "stage-1"},
            timestamp=event_time,
        ),
        state,
    )

    assert cursor.inserts
    assert state.last_event_id == 101
    assert mirrored[0]["event_id"] == 101
    assert mirrored[0]["event_type"] == "workflow.initialized"
    assert mirrored[0]["execution_id"] == 7
    assert mirrored[0]["catalog_id"] == 5
    assert mirrored[0]["parent_event_id"] == 77
    assert mirrored[0]["stage_id"] == "stage-1"
    assert mirrored[0]["event_time"] == event_time


@pytest.mark.asyncio
async def test_engine_caller_owned_persist_event_does_not_mirror_before_external_commit(monkeypatch):
    import noetl.core.dsl.engine.executor.lifecycle as lifecycle

    mirrored = []

    async def fake_mirror(events):
        mirrored.extend(events)

    monkeypatch.setattr(lifecycle, "_mirror_engine_events", fake_mirror)

    state = SimpleNamespace(
        catalog_id=5,
        parent_execution_id=None,
        step_event_ids={},
        last_event_id=None,
        loop_state={},
    )

    await _Engine()._persist_event(
        Event(
            execution_id="7",
            step="workflow",
            name="workflow.initialized",
            payload={"status": "initialized"},
        ),
        state,
        conn=_Conn(_Cursor()),
    )

    assert mirrored == []
