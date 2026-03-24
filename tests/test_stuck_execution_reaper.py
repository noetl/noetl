import pytest

import noetl.server.stuck_execution_reaper as stuck_execution_reaper


class _FakeCursor:
    def __init__(self, fetchall_rows=None, rowcounts=None):
        self.fetchall_rows = list(fetchall_rows or [])
        self.rowcounts = list(rowcounts or [])
        self.queries = []
        self.params = []
        self.rowcount = 0

    async def execute(self, query, params=None):
        self.queries.append(query)
        self.params.append(params)
        if self.rowcounts:
            self.rowcount = self.rowcounts.pop(0)
        else:
            self.rowcount = 1 if query.lstrip().upper().startswith("INSERT") else 0

    async def fetchall(self):
        return list(self.fetchall_rows)


class _FakeCursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, row_factory=None):
        return _FakeCursorCtx(self._cursor)

    async def commit(self):
        self.committed = True


class _FakeConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_find_inactive_executions_uses_inactivity_window_and_terminal_filter(monkeypatch):
    rows = [
        {
            "execution_id": 101,
            "catalog_id": 202,
            "first_event_at": "2026-03-23T00:00:00Z",
            "last_event_at": "2026-03-23T01:00:00Z",
        }
    ]
    cursor = _FakeCursor(rows)
    conn = _FakeConn(cursor)

    def _fake_get_pool_connection(*_args, **_kwargs):
        return _FakeConnCtx(conn)

    monkeypatch.setattr(stuck_execution_reaper, "get_pool_connection", _fake_get_pool_connection)

    result = await stuck_execution_reaper._find_inactive_executions(
        inactivity_minutes=120,
        max_executions=10,
    )

    assert result == rows
    assert cursor.params == [
        (
            120,
            100,
            120,
            stuck_execution_reaper._TERMINAL_EXECUTION_EVENT_TYPES,
            10,
        )
    ]
    sql = cursor.queries[0]
    assert "WITH candidate_exec AS (" in sql
    assert "e.event_type = 'playbook.initialized'" in sql
    assert "JOIN LATERAL (" in sql
    assert "ORDER BY e.event_id DESC" in sql
    assert "LIMIT %s" in sql
    assert "ORDER BY MIN(e.created_at) ASC" in sql
    assert "latest.last_event_at < NOW() - (%s * INTERVAL '1 minute')" in sql
    assert "terminal.event_type = ANY(%s)" in sql


@pytest.mark.asyncio
async def test_cleanup_inactive_executions_once_cancels_candidates(monkeypatch):
    rows = [
        {
            "execution_id": 101,
            "catalog_id": 202,
            "first_event_at": "2026-03-23T00:00:00Z",
            "last_event_at": "2026-03-23T01:00:00Z",
        },
        {
            "execution_id": 303,
            "catalog_id": 404,
            "first_event_at": "2026-03-23T02:00:00Z",
            "last_event_at": "2026-03-23T03:00:00Z",
        },
    ]
    cursor = _FakeCursor(rowcounts=[1, 1])
    conn = _FakeConn(cursor)

    async def _fake_find_inactive_executions(*, inactivity_minutes, max_executions):
        assert inactivity_minutes == 120
        assert max_executions == 10
        return rows

    def _fake_get_pool_connection(*_args, **_kwargs):
        return _FakeConnCtx(conn)

    monkeypatch.setattr(
        stuck_execution_reaper,
        "_find_inactive_executions",
        _fake_find_inactive_executions,
    )
    monkeypatch.setattr(stuck_execution_reaper, "get_pool_connection", _fake_get_pool_connection)

    result = await stuck_execution_reaper.cleanup_inactive_executions_once(
        inactivity_minutes=120,
        max_executions=10,
    )

    assert result == {
        "cancelled_count": 2,
        "candidate_count": 2,
        "execution_ids": ["101", "303"],
        "dry_run": False,
    }
    assert conn.committed is True
    assert len(cursor.queries) == 2
    assert all("INSERT INTO noetl.event" in q for q in cursor.queries)
    assert all("SELECT noetl.snowflake_id() AS event_id" in q for q in cursor.queries)


@pytest.mark.asyncio
async def test_cleanup_inactive_executions_once_dry_run_skips_inserts(monkeypatch):
    rows = [{"execution_id": 101, "catalog_id": 202}]

    async def _fake_find_inactive_executions(*, inactivity_minutes, max_executions):
        return rows

    monkeypatch.setattr(
        stuck_execution_reaper,
        "_find_inactive_executions",
        _fake_find_inactive_executions,
    )

    result = await stuck_execution_reaper.cleanup_inactive_executions_once(
        inactivity_minutes=120,
        max_executions=10,
        dry_run=True,
    )

    assert result == {
        "cancelled_count": 0,
        "candidate_count": 1,
        "execution_ids": ["101"],
        "dry_run": True,
    }


@pytest.mark.asyncio
async def test_cleanup_inactive_executions_once_returns_disabled_when_feature_off(monkeypatch):
    monkeypatch.setattr(
        stuck_execution_reaper,
        "_STUCK_EXECUTION_REAPER_ENABLED",
        False,
    )

    result = await stuck_execution_reaper.cleanup_inactive_executions_once(
        inactivity_minutes=120,
        max_executions=10,
    )

    assert result == {
        "cancelled_count": 0,
        "execution_ids": [],
        "dry_run": False,
        "candidate_count": 0,
        "disabled": True,
    }


@pytest.mark.asyncio
async def test_cleanup_inactive_executions_once_preserves_explicit_zero(monkeypatch):
    result = await stuck_execution_reaper.cleanup_inactive_executions_once(
        inactivity_minutes=0,
        max_executions=0,
    )

    assert result == {
        "cancelled_count": 0,
        "candidate_count": 0,
        "execution_ids": [],
        "dry_run": False,
        "invalid_params": True,
    }
