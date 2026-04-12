from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import noetl.server.api.core as v2_api


class _CursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeCursor:
    def __init__(
        self,
        start_time: datetime,
        latest_time: datetime,
        terminal_time: datetime | None,
        pending_count: int = 0,
        latest_event_type: str = "batch.processing",
        latest_status: str = "RUNNING",
        terminal_event_type: str = "playbook.completed",
    ):
        self._query = ""
        self._start_time = start_time
        self._latest_time = latest_time
        self._terminal_time = terminal_time
        self._pending_count = pending_count
        self._latest_event_type = latest_event_type
        self._latest_status = latest_status
        self._terminal_event_type = terminal_event_type

    async def execute(self, query, _params):
        self._query = query

    async def fetchall(self):
        if "event_type = 'step.exit'" in self._query:
            return []
        raise AssertionError(f"Unexpected fetchall query in test cursor: {self._query}")

    async def fetchone(self):
        if "ORDER BY event_id ASC" in self._query:
            return {"created_at": self._start_time}
        if "SELECT COUNT(*) AS pending_count" in self._query:
            return {"pending_count": self._pending_count}
        if "AND event_type IN (" in self._query:
            if self._terminal_time is None:
                return None
            return {
                "event_type": self._terminal_event_type,
                "node_name": "bhs/state_report_generation_prod_v10",
                "status": "COMPLETED",
                "created_at": self._terminal_time,
            }
        if "ORDER BY event_id DESC" in self._query:
            return {
                "event_type": self._latest_event_type,
                "node_name": "events.batch",
                "status": self._latest_status,
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


def test_v2_pending_command_count_sql_tracks_command_ids():
    sql = " ".join(v2_api._PENDING_COMMAND_COUNT_SQL.split())
    assert "meta->>'command_id'" in sql
    assert "result->'data'->>'command_id'" not in sql
    assert "EXCEPT" in sql
    assert "SELECT node_name" not in sql
    assert "'call.done'" not in sql
    assert "'command.completed'" in sql
    assert "'command.failed'" in sql
    assert "'command.cancelled'" in sql


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
    fake_cursor = _FakeCursor(start_time, latest_batch_time, terminal_time, pending_count=0)

    monkeypatch.setattr(v2_api, "get_engine", lambda: fake_engine)
    monkeypatch.setattr(v2_api, "get_pool_connection", lambda: _ConnCtx(_FakeConn(fake_cursor)))

    result = await v2_api.get_execution_status("585000300126142930")

    assert result["completed"] is True
    assert result["failed"] is False
    assert result["completion_inferred"] is True
    assert result["end_time"] == terminal_time.isoformat()


@pytest.mark.asyncio
async def test_status_infers_completion_from_batch_completed_without_pending_commands(monkeypatch):
    start_time = datetime(2026, 3, 18, 3, 41, 55, tzinfo=timezone.utc)
    latest_batch_time = datetime(2026, 3, 18, 3, 47, 41, tzinfo=timezone.utc)

    fake_state = SimpleNamespace(
        completed=False,
        failed=False,
        current_step="events.batch",
        completed_steps={"start"},
        variables={},
    )
    fake_engine = SimpleNamespace(state_store=SimpleNamespace(get_state=lambda _execution_id: fake_state))
    fake_cursor = _FakeCursor(
        start_time,
        latest_batch_time,
        terminal_time=None,
        pending_count=0,
        latest_event_type="batch.completed",
        latest_status="COMPLETED",
    )

    monkeypatch.setattr(v2_api, "get_engine", lambda: fake_engine)
    monkeypatch.setattr(v2_api, "get_pool_connection", lambda: _ConnCtx(_FakeConn(fake_cursor)))

    result = await v2_api.get_execution_status("585005709285130319")

    assert result["completed"] is True
    assert result["failed"] is False
    assert result["completion_inferred"] is True
    assert result["end_time"] == latest_batch_time.isoformat()


@pytest.mark.asyncio
async def test_status_keeps_running_when_batch_completed_still_has_pending_commands(monkeypatch):
    start_time = datetime(2026, 3, 22, 22, 12, 2, tzinfo=timezone.utc)
    latest_batch_time = datetime(2026, 3, 22, 22, 17, 1, tzinfo=timezone.utc)

    fake_state = SimpleNamespace(
        completed=False,
        failed=False,
        current_step="run_mds_batch_workers",
        completed_steps={"start", "build_mds_batch_plan"},
        variables={},
    )
    fake_engine = SimpleNamespace(state_store=SimpleNamespace(get_state=lambda _execution_id: fake_state))
    fake_cursor = _FakeCursor(
        start_time,
        latest_batch_time,
        terminal_time=None,
        pending_count=1,
        latest_event_type="batch.completed",
        latest_status="COMPLETED",
    )

    monkeypatch.setattr(v2_api, "get_engine", lambda: fake_engine)
    monkeypatch.setattr(v2_api, "get_pool_connection", lambda: _ConnCtx(_FakeConn(fake_cursor)))

    result = await v2_api.get_execution_status("588463546770392019")

    assert result["completed"] is False
    assert result["failed"] is False
    assert result["completion_inferred"] is False
    assert result["end_time"] is None


@pytest.mark.asyncio
async def test_status_event_log_fallback_keeps_completion_inferred_false_for_non_terminal_call_done(monkeypatch):
    start_time = datetime(2026, 3, 24, 6, 20, 0, tzinfo=timezone.utc)
    latest_time = datetime(2026, 3, 24, 6, 26, 29, tzinfo=timezone.utc)

    fake_engine = SimpleNamespace(state_store=SimpleNamespace(get_state=lambda _execution_id: None))
    fake_cursor = _FakeCursor(
        start_time,
        latest_time,
        terminal_time=None,
        pending_count=0,
        latest_event_type="call.done",
        latest_status="COMPLETED",
    )

    monkeypatch.setattr(v2_api, "get_engine", lambda: fake_engine)
    monkeypatch.setattr(v2_api, "get_pool_connection", lambda: _ConnCtx(_FakeConn(fake_cursor)))

    result = await v2_api.get_execution_status("589375687589363999")

    assert result["current_step"] == "events.batch"
    assert result["completed"] is False
    assert result["failed"] is False
    assert result["completion_inferred"] is False
    assert result["end_time"] is None
    assert result["source"] == "event_log_fallback"


@pytest.mark.asyncio
async def test_status_marks_terminal_failure_as_failed_not_completed(monkeypatch):
    start_time = datetime(2026, 3, 24, 6, 20, 0, tzinfo=timezone.utc)
    terminal_time = datetime(2026, 3, 24, 6, 26, 29, tzinfo=timezone.utc)
    latest_time = datetime(2026, 3, 24, 6, 26, 35, tzinfo=timezone.utc)

    fake_state = SimpleNamespace(
        completed=False,
        failed=False,
        current_step="step_a",
        completed_steps={"start"},
        variables={},
    )
    fake_engine = SimpleNamespace(state_store=SimpleNamespace(get_state=lambda _execution_id: fake_state))
    fake_cursor = _FakeCursor(
        start_time,
        latest_time,
        terminal_time,
        terminal_event_type="playbook.failed",
    )

    monkeypatch.setattr(v2_api, "get_engine", lambda: fake_engine)
    monkeypatch.setattr(v2_api, "get_pool_connection", lambda: _ConnCtx(_FakeConn(fake_cursor)))

    result = await v2_api.get_execution_status("589375687589363111")

    assert result["failed"] is True
    assert result["completed"] is False
    assert result["completion_inferred"] is True
