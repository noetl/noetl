from datetime import datetime, timezone

import pytest


class _FakeCursor:
    def __init__(self):
        self.query = ""
        self.executed = []
        self.command_row_returned = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, query, params=None):
        self.query = query
        self.executed.append((query, params))

    async def fetchone(self):
        if "FROM noetl.command" in self.query:
            if self.command_row_returned:
                return None
            self.command_row_returned = True
            return {
                "command_id": 900,
                "execution_id": 7,
                "catalog_id": 5,
                "step_name": "fetch",
                "tool_kind": "http",
                "context": {"url": "https://example.test"},
                "meta": {"stage_id": "stage-1"},
                "status": "PENDING",
                "worker_id": None,
                "claimed_at": None,
                "started_at": None,
                "updated_at": None,
            }
        if "pg_try_advisory_xact_lock" in self.query:
            return {"lock_acquired": True}
        if "RETURNING event_id" in self.query:
            return {"event_id": 501}
        return None


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
async def test_claim_command_enqueues_claimed_event_before_drain(monkeypatch):
    from noetl.server.api.core import commands, events
    from noetl.server.api.core.models import ClaimRequest

    cursor = _FakeCursor()
    conn = _FakeConnection(cursor)
    enqueued = []

    async def fake_next_snowflake_id(_cur):
        return 501

    async def fake_enqueue(_cur, event):
        enqueued.append(event)

    async def fake_drain():
        assert conn.commits == 1

    monkeypatch.setattr(commands, "get_pool_connection", lambda **_kwargs: conn)
    monkeypatch.setattr(commands, "_next_snowflake_id", fake_next_snowflake_id)
    monkeypatch.setattr(commands, "_active_claim_cache_get", lambda _event_id: None)
    monkeypatch.setattr(commands, "_active_claim_cache_set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(commands, "_record_db_operation_success", lambda: None)
    monkeypatch.setattr(events, "_enqueue_event_outbox", fake_enqueue)
    monkeypatch.setattr(events, "_drain_core_outbox", fake_drain)

    response = await commands.claim_command(100, ClaimRequest(worker_id="worker-1"))

    assert response.status == "ok"
    assert enqueued[0]["event_id"] == 501
    assert enqueued[0]["event_type"] == "command.claimed"
    assert enqueued[0]["execution_id"] == 7
    assert enqueued[0]["catalog_id"] == 5
    assert enqueued[0]["command_id"] == 900
    assert enqueued[0]["node_name"] == "fetch"
    assert enqueued[0]["status"] == "RUNNING"
    assert enqueued[0]["meta"]["worker_id"] == "worker-1"
    assert isinstance(enqueued[0]["created_at"], datetime)
    assert enqueued[0]["created_at"].tzinfo == timezone.utc
