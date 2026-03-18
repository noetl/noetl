from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import noetl.server.api.v2 as v2_api


class _CursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeCursor:
    def __init__(self, start_time: datetime, latest_time: datetime, terminal_time: datetime):
        self._query = ""
        self._start_time = start_time
        self._latest_time = latest_time
        self._terminal_time = terminal_time

    async def execute(self, query, _params):
        self._query = query

    async def fetchone(self):
        if "ORDER BY event_id ASC" in self._query:
            return {"created_at": self._start_time}
        if "AND event_type IN (" in self._query:
            return {
                "event_type": "playbook.completed",
                "node_name": "bhs/state_report_generation_prod_v10",
                "status": "COMPLETED",
                "created_at": self._terminal_time,
            }
        if "ORDER BY event_id DESC" in self._query:
            return {
                "event_type": "batch.processing",
                "node_name": "events.batch",
                "status": "RUNNING",
                "created_at": self._latest_time,
            }
        raise AssertionError(f"Unexpected query in test cursor: {self._query}")


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, row_factory=None):  # noqa: ARG002
        return _CursorCtx(self._cursor)


class _ConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_status_prefers_terminal_event_when_latest_event_is_batch_processing(monkeypatch):
    start_time = datetime(2026, 3, 18, 3, 31, 10, tzinfo=timezone.utc)
    terminal_time = datetime(2026, 3, 18, 3, 33, 40, tzinfo=timezone.utc)
    latest_batch_time = datetime(2026, 3, 18, 3, 33, 42, tzinfo=timezone.utc)

    fake_state = SimpleNamespace(
        completed=False,
        failed=False,
        current_step="load_patients_for_adt",
        completed_steps={"start", "load_next_facility"},
        variables={},
    )
    fake_engine = SimpleNamespace(state_store=SimpleNamespace(get_state=lambda _execution_id: fake_state))
    fake_cursor = _FakeCursor(start_time, latest_batch_time, terminal_time)

    monkeypatch.setattr(v2_api, "get_engine", lambda: fake_engine)
    monkeypatch.setattr(v2_api, "get_pool_connection", lambda: _ConnCtx(_FakeConn(fake_cursor)))

    result = await v2_api.get_execution_status("585000300126142930")

    assert result["completed"] is True
    assert result["failed"] is False
    assert result["completion_inferred"] is True
    assert result["end_time"] == terminal_time.isoformat()
