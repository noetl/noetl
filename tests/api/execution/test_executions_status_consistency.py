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
        self._query = ""

    async def execute(self, query, _params=None):
        self._query = query

    async def fetchall(self):
        return self._rows


class _GetExecutionCursor:
    def __init__(self, *, events, first_event, terminal_event, latest_event, pending_row):
        self._events = events
        self._first_event = first_event
        self._terminal_event = terminal_event
        self._latest_event = latest_event
        self._pending_row = pending_row
        self._query = ""

    async def execute(self, query, _params=None):
        self._query = query

    async def fetchall(self):
        if "SELECT event_id," in self._query and "ORDER BY event_id DESC" in self._query:
            return self._events
        raise AssertionError(f"Unexpected fetchall query: {self._query}")

    async def fetchone(self):
        if "SELECT COUNT(*) as total" in self._query:
            return {"total": len(self._events)}
        if "ORDER BY event_id ASC" in self._query:
            return self._first_event
        if "AND event_type IN ('execution.cancelled', 'playbook.failed', 'workflow.failed'" in self._query:
            return self._terminal_event
        if "SELECT event_type, node_name, created_at, status" in self._query:
            return self._latest_event
        if "SELECT COUNT(*) AS pending_count" in self._query:
            return self._pending_row
        raise AssertionError(f"Unexpected fetchone query: {self._query}")


class _CatalogCursor:
    def __init__(self, row):
        self._row = row

    async def execute(self, query, _params=None):
        self._query = query

    async def fetchone(self):
        return self._row


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


class _ConnectionFactory:
    def __init__(self, *connections):
        self._connections = list(connections)

    def __call__(self):
        if not self._connections:
            raise AssertionError("No more fake connections available")
        return _ConnCtx(self._connections.pop(0))


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


@pytest.mark.asyncio
async def test_get_execution_infers_completed_from_batch_done_without_pending_commands(monkeypatch):
    start = datetime(2026, 3, 21, 8, 12, 52, tzinfo=timezone.utc)
    latest = datetime(2026, 3, 21, 10, 3, 54, tzinfo=timezone.utc)
    event_rows = [
        {
            "event_id": 587372302669448146,
            "event_type": "batch.completed",
            "node_id": "events.batch",
            "node_name": "events.batch",
            "status": "COMPLETED",
            "created_at": latest,
            "context": None,
            "result": None,
            "error": None,
            "catalog_id": 7,
            "parent_execution_id": None,
            "parent_event_id": None,
            "duration": None,
        }
    ]
    first_event = {
        "event_id": 1,
        "event_type": "playbook.initialized",
        "catalog_id": 7,
        "parent_execution_id": None,
        "created_at": start,
        "status": "INITIALIZED",
    }
    latest_event = {
        "event_type": "batch.completed",
        "node_name": "events.batch",
        "created_at": latest,
        "status": "COMPLETED",
    }
    catalog_row = {"path": "bhs/state_report_generation_prod_v10", "version": 7}

    monkeypatch.setattr(
        execution_api,
        "get_pool_connection",
        _ConnectionFactory(
            _FakeConn(
                _GetExecutionCursor(
                    events=event_rows,
                    first_event=first_event,
                    terminal_event=None,
                    latest_event=latest_event,
                    pending_row={"pending_count": 0},
                )
            ),
            _FakeConn(_CatalogCursor(catalog_row)),
        ),
    )

    result = await execution_api.get_execution(
        "587316413618979403",
        page=1,
        page_size=100,
        since_event_id=None,
        event_type=None,
    )

    assert result["status"] == "COMPLETED"
    assert result["end_time"] == latest.isoformat()
    assert result["duration_human"] == "1h 51m 2s"
