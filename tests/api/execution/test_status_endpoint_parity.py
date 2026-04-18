from datetime import datetime, timezone

import pytest

import noetl.server.api.core.execution as core_execution


class _CursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeCursor:
    def __init__(self, *, first_event, latest_event, terminal_event, pending_row=None, step_rows=None):
        self._first_event = first_event
        self._latest_event = latest_event
        self._terminal_event = terminal_event
        self._pending_row = pending_row or {"pending_count": 0}
        self._step_rows = step_rows or []
        self._query = ""

    async def execute(self, query, _params=None):
        self._query = query

    async def fetchone(self):
        if "ORDER BY event_id ASC LIMIT 1" in self._query:
            return self._first_event
        if "ORDER BY event_id DESC LIMIT 1" in self._query and "event_type = ANY" not in self._query:
            return self._latest_event
        if "event_type = ANY" in self._query:
            return self._terminal_event
        if "SELECT COUNT(*) AS pending_count" in self._query:
            return self._pending_row
        raise AssertionError(f"Unexpected fetchone query: {self._query}")

    async def fetchall(self):
        if "event_type IN ('step.exit', 'loop.done')" in self._query:
            return self._step_rows
        raise AssertionError(f"Unexpected fetchall query: {self._query}")


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


class _FakeStateStore:
    def __init__(self, state):
        self._state = state

    async def load_state(self, execution_id):  # noqa: ARG002
        return self._state


class _FakeEngine:
    def __init__(self, state):
        self.state_store = _FakeStateStore(state)


class _FakeState:
    def __init__(self):
        self.completed = False
        self.failed = False
        self.current_step = "claim_patients_for_medications"
        self.completed_steps = {"start", "load_next_facility"}
        self.variables = {}


@pytest.mark.asyncio
async def test_status_endpoint_marks_state_backed_execution_failed_on_command_failed(monkeypatch):
    start = datetime(2026, 4, 18, 18, 0, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 4, 18, 18, 25, 0, tzinfo=timezone.utc)
    terminal = {
        "event_type": "command.failed",
        "node_name": "claim_patients_for_medications",
        "status": "FAILED",
        "created_at": latest,
    }

    monkeypatch.setattr(core_execution, "get_engine", lambda: _FakeEngine(_FakeState()))
    monkeypatch.setattr(
        core_execution,
        "get_pool_connection",
        lambda: _ConnCtx(
            _FakeConn(
                _FakeCursor(
                    first_event={"created_at": start},
                    latest_event=terminal,
                    terminal_event=terminal,
                )
            )
        ),
    )

    result = await core_execution.get_execution_status("607458339856843442")

    assert result["failed"] is True
    assert result["completed"] is False
    assert result["end_time"] == latest.isoformat()
    assert result["duration_human"] == "25m"


@pytest.mark.asyncio
async def test_status_endpoint_fallback_marks_missing_state_execution_failed_on_command_failed(monkeypatch):
    start = datetime(2026, 4, 18, 18, 0, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 4, 18, 18, 25, 0, tzinfo=timezone.utc)
    terminal = {
        "event_type": "command.failed",
        "node_name": "claim_patients_for_medications",
        "status": "FAILED",
        "created_at": latest,
    }

    monkeypatch.setattr(core_execution, "get_engine", lambda: _FakeEngine(None))
    monkeypatch.setattr(
        core_execution,
        "get_pool_connection",
        lambda: _ConnCtx(
            _FakeConn(
                _FakeCursor(
                    first_event={"created_at": start},
                    latest_event=terminal,
                    terminal_event=terminal,
                    step_rows=[],
                )
            )
        ),
    )

    result = await core_execution.get_execution_status("607458339856843442")

    assert result["source"] == "event_log_fallback"
    assert result["failed"] is True
    assert result["completed"] is False
    assert result["end_time"] == latest.isoformat()
    assert result["duration_human"] == "25m"
