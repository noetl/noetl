from datetime import datetime, timezone

import pytest


class _FakeCursor:
    def __init__(self):
        self.executed = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, query, params=None):
        self.executed.append((query, params))


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def cursor(self, **_kwargs):
        return self._cursor

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_broker_emit_event_enqueues_outbox_before_drain(monkeypatch):
    from noetl.server.api.broker.schema import EventEmitRequest
    from noetl.server.api.broker import service

    cursor = _FakeCursor()
    conn = _FakeConnection(cursor)
    enqueued = []

    async def fake_enqueue(_cur, event):
        enqueued.append(event)

    async def fake_drain():
        assert conn.commits == 1

    monkeypatch.setattr(service, "get_pool_connection", lambda: conn)
    monkeypatch.setattr(service, "get_snowflake_id", lambda: _async_value(9001))
    monkeypatch.setattr(service, "_enqueue_broker_outbox", fake_enqueue)
    monkeypatch.setattr(service, "_drain_broker_outbox", fake_drain)

    created_at = datetime(2026, 5, 18, tzinfo=timezone.utc)
    result = await service.EventService.emit_event(
        EventEmitRequest(
            execution_id="7",
            catalog_id="5",
            event_type="step_completed",
            node_id="fetch",
            node_name="fetch",
            node_type="task",
            status="COMPLETED",
            context={"input": "ok"},
            output_inline={"rows": 1},
            meta={"stage_id": "stage-1"},
            actionable=False,
            informative=True,
            created_at=created_at,
        )
    )

    assert result.event_id == "9001"
    assert enqueued[0]["event_id"] == 9001
    assert enqueued[0]["event_type"] == "step_completed"
    assert enqueued[0]["execution_id"] == 7
    assert enqueued[0]["catalog_id"] == 5
    assert enqueued[0]["node_name"] == "fetch"
    assert enqueued[0]["result"] == {"rows": 1}
    assert enqueued[0]["meta"]["stage_id"] == "stage-1"


async def _async_value(value):
    return value
