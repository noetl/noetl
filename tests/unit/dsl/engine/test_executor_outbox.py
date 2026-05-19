from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


class _FakeCursor:
    def __init__(self):
        self.query = ""
        self.executed = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, query, params=None):
        self.query = query
        self.executed.append((query, params))

    async def fetchone(self):
        if "snowflake_id" in self.query:
            return {"snowflake_id": 7001}
        return None


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, **_kwargs):
        return self._cursor


@pytest.mark.asyncio
async def test_persist_event_enqueues_outbox_inside_caller_transaction(monkeypatch):
    from noetl.core.dsl.engine.executor import lifecycle
    from noetl.core.dsl.engine.executor.lifecycle import LifecycleMixin

    enqueued = []
    drained = {"called": 0}
    cursor = _FakeCursor()

    async def fake_enqueue(_cur, event):
        enqueued.append(event)

    async def fake_drain():
        drained["called"] += 1

    monkeypatch.setattr(lifecycle, "enqueue_executor_outbox", fake_enqueue)
    monkeypatch.setattr(lifecycle, "drain_executor_outbox", fake_drain)

    event_time = datetime(2026, 5, 19, tzinfo=timezone.utc)
    event = SimpleNamespace(
        execution_id="7",
        step="fetch",
        name="command.started",
        payload={"command_id": 900},
        meta={"stage_id": "stage-1"},
        timestamp=event_time,
        parent_event_id=None,
        worker_id="worker-1",
    )
    state = SimpleNamespace(
        catalog_id=5,
        parent_execution_id=None,
        step_event_ids={},
        last_event_id=99,
    )

    await LifecycleMixin()._persist_event(event, state, conn=_FakeConnection(cursor))

    assert drained["called"] == 0
    assert state.last_event_id == 7001
    assert state.step_event_ids["fetch"] == 7001
    assert enqueued[0]["event_id"] == 7001
    assert enqueued[0]["event_type"] == "command.started"
    assert enqueued[0]["execution_id"] == 7
    assert enqueued[0]["catalog_id"] == 5
    assert enqueued[0]["parent_event_id"] == 99
    assert enqueued[0]["node_name"] == "fetch"
    assert enqueued[0]["context"] == {"command_id": 900}
    assert enqueued[0]["meta"] == {"stage_id": "stage-1"}
