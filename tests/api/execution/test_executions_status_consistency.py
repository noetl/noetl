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
        self._params = None

    async def execute(self, query, _params=None):
        self._query = query
        self._params = _params

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


def test_pending_command_count_sql_tracks_command_ids():
    sql = " ".join(execution_api._PENDING_COMMAND_COUNT_SQL.split())
    assert "meta->>'command_id'" in sql
    assert "result->'data'->>'command_id'" in sql
    assert "UNION ALL" in sql
    assert "SELECT node_name" not in sql


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
    async def fake_pending_counts(cursor, execution_ids):  # noqa: ARG001
        return {"123": 1}

    monkeypatch.setattr(
        execution_api,
        "_fetch_pending_command_counts_for_executions",
        fake_pending_counts,
    )

    result = await execution_api.get_executions()
    assert len(result) == 1
    assert result[0].status == "RUNNING"
    assert result[0].end_time is None
    assert result[0].duration_seconds is not None
    assert result[0].duration_human is not None


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
    assert result[0].duration_seconds == 0.0
    assert result[0].duration_human == "0s"


@pytest.mark.asyncio
async def test_get_executions_infers_completed_from_batch_done_without_pending(monkeypatch):
    now = datetime(2026, 3, 21, 7, 0, 0, tzinfo=timezone.utc)
    rows = [
        {
            "execution_id": "123",
            "catalog_id": "321",
            "event_type": "batch.completed",
            "node_name": "events.batch",
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
    async def fake_pending_counts(cursor, execution_ids):  # noqa: ARG001
        return {"123": 0}

    monkeypatch.setattr(
        execution_api,
        "_fetch_pending_command_counts_for_executions",
        fake_pending_counts,
    )

    result = await execution_api.get_executions()
    assert len(result) == 1
    assert result[0].status == "COMPLETED"
    assert result[0].end_time == now


@pytest.mark.asyncio
async def test_get_executions_applies_page_size_and_offset(monkeypatch):
    now = datetime(2026, 3, 21, 7, 0, 0, tzinfo=timezone.utc)
    rows = [
        {
            "execution_id": "123",
            "catalog_id": "321",
            "event_type": "playbook.completed",
            "node_name": "end",
            "status": "COMPLETED",
            "derived_event_type": "playbook.completed",
            "start_time": now,
            "end_time": now,
            "result": None,
            "error": None,
            "parent_execution_id": None,
            "path": "tests/example",
            "version": 1,
        }
    ]
    cursor = _FakeCursor(rows)

    monkeypatch.setattr(
        execution_api,
        "get_pool_connection",
        lambda: _ConnCtx(_FakeConn(cursor)),
    )

    result = await execution_api.get_executions(page=2, page_size=25)

    assert len(result) == 1
    assert cursor._params == {"limit": 25, "offset": 25}


@pytest.mark.asyncio
async def test_get_executions_rejects_excessive_offset(monkeypatch):
    monkeypatch.setattr(
        execution_api,
        "get_pool_connection",
        lambda: _ConnCtx(_FakeConn(_FakeCursor([]))),
    )

    with pytest.raises(execution_api.HTTPException) as exc_info:
        await execution_api.get_executions(page=1000, page_size=100)

    assert exc_info.value.status_code == 422
    assert "Max supported offset" in exc_info.value.detail


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


@pytest.mark.asyncio
async def test_get_execution_keeps_running_when_batch_done_still_has_pending_commands(monkeypatch):
    start = datetime(2026, 3, 22, 22, 12, 2, tzinfo=timezone.utc)
    latest = datetime(2026, 3, 22, 22, 17, 1, tzinfo=timezone.utc)
    event_rows = [
        {
            "event_id": 588466061222084806,
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
                    pending_row={"pending_count": 1},
                )
            ),
            _FakeConn(_CatalogCursor(catalog_row)),
        ),
    )

    result = await execution_api.get_execution(
        "588463546770392019",
        page=1,
        page_size=100,
        since_event_id=None,
        event_type=None,
    )

    assert result["status"] == "RUNNING"
    assert result["end_time"] is None


@pytest.mark.asyncio
async def test_get_execution_can_omit_events_payload(monkeypatch):
    start = datetime(2026, 3, 21, 8, 12, 52, tzinfo=timezone.utc)
    latest = datetime(2026, 3, 21, 10, 3, 54, tzinfo=timezone.utc)
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
                    events=[],
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
        include_events=False,
    )

    assert result["events"] == []
    assert result["events_included"] is False
    assert result["events_endpoint"] == "/api/executions/587316413618979403/events"
    assert result["pagination"] is None


@pytest.mark.asyncio
async def test_get_execution_prefers_terminal_failure_over_batch_completion_inference(monkeypatch):
    start = datetime(2026, 3, 21, 8, 12, 52, tzinfo=timezone.utc)
    latest = datetime(2026, 3, 21, 10, 3, 54, tzinfo=timezone.utc)
    terminal = datetime(2026, 3, 21, 10, 3, 40, tzinfo=timezone.utc)
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
    terminal_event = {
        "event_type": "playbook.failed",
        "status": "FAILED",
        "created_at": terminal,
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
                    terminal_event=terminal_event,
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

    assert result["status"] == "FAILED"
    assert result["end_time"] == terminal.isoformat()
