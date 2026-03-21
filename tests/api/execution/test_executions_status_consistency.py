from datetime import datetime, timezone

import pytest

import noetl.server.api.execution.endpoint as execution_api


class _CursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, query, _params=None):
        self._query = query

    async def fetchall(self):
        return self._rows


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


def test_derive_status_keeps_non_terminal_completed_running():
    row = {"event_type": "batch.completed", "status": "COMPLETED"}
    assert execution_api._derive_execution_terminal_status(row) == "RUNNING"


@pytest.mark.asyncio
async def test_get_executions_normalizes_non_terminal_completed_to_running(monkeypatch):
    now = datetime(2026, 3, 21, 7, 0, 0, tzinfo=timezone.utc)
    rows = [
        {
            "execution_id": "123",
            "catalog_id": "321",
            "event_type": "batch.completed",
            "status": "COMPLETED",
            "derived_event_type": "batch.completed",
            "start_time": now,
            "end_time": now,
            "result": None,
            "error": None,
            "parent_execution_id": None,
            "path": "bhs/state_report_generation_prod_v10",
            "version": 1,
        }
    ]

    monkeypatch.setattr(
        execution_api,
        "get_pool_connection",
        lambda: _ConnCtx(_FakeConn(_FakeCursor(rows))),
    )

    result = await execution_api.get_executions()
    assert len(result) == 1
    assert result[0].status == "RUNNING"
    assert result[0].end_time is None


@pytest.mark.asyncio
async def test_get_executions_keeps_terminal_completed(monkeypatch):
    now = datetime(2026, 3, 21, 7, 0, 0, tzinfo=timezone.utc)
    rows = [
        {
            "execution_id": "123",
            "catalog_id": "321",
            "event_type": "playbook.completed",
            "status": "COMPLETED",
            "derived_event_type": "playbook.completed",
            "start_time": now,
            "end_time": now,
            "result": None,
            "error": None,
            "parent_execution_id": None,
            "path": "bhs/state_report_generation_prod_v10",
            "version": 1,
        }
    ]

    monkeypatch.setattr(
        execution_api,
        "get_pool_connection",
        lambda: _ConnCtx(_FakeConn(_FakeCursor(rows))),
    )

    result = await execution_api.get_executions()
    assert len(result) == 1
    assert result[0].status == "COMPLETED"
    assert result[0].end_time == now
