import pytest

from noetl.server.runtime_leases import RuntimeLease
import noetl.server.runtime_leases as runtime_leases


class _CursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self, row_factory=None):
        return _CursorCtx(self._cursor)

    async def commit(self):
        self.commits += 1


class _AcquireCursor:
    def __init__(self, row):
        self._row = row
        self.statements = []

    async def execute(self, sql, params):
        self.statements.append((sql, params))

    async def fetchone(self):
        return self._row


@pytest.mark.asyncio
async def test_runtime_lease_try_acquire_returns_true(monkeypatch):
    cursor = _AcquireCursor({"runtime": {"owner_instance": "api-1"}})
    conn = _FakeConn(cursor)

    monkeypatch.setattr(runtime_leases, "get_pool_connection", lambda timeout=3.0: _ConnCtx(conn))
    monkeypatch.setattr(runtime_leases, "get_snowflake_id", lambda: 123)

    lease = RuntimeLease(
        task_name="command_reaper",
        instance_name="api-1",
        server_url="http://server/api",
        hostname="pod-1",
        logical_name="server",
        lease_seconds=30,
    )

    state = await lease.try_acquire_or_renew()

    assert state.acquired is True
    assert state.owner_instance == "api-1"
    assert conn.commits == 1
    assert cursor.statements


@pytest.mark.asyncio
async def test_runtime_lease_try_acquire_reports_current_owner(monkeypatch):
    acquire_cursor = _AcquireCursor(None)
    owner_cursor = _AcquireCursor({"runtime": {"owner_instance": "api-2"}})
    calls = {"count": 0}

    def _fake_get_pool_connection(timeout=3.0):
        calls["count"] += 1
        if calls["count"] == 1:
            return _ConnCtx(_FakeConn(acquire_cursor))
        return _ConnCtx(_FakeConn(owner_cursor))

    monkeypatch.setattr(runtime_leases, "get_pool_connection", _fake_get_pool_connection)
    monkeypatch.setattr(runtime_leases, "get_snowflake_id", lambda: 123)

    lease = RuntimeLease(
        task_name="command_reaper",
        instance_name="api-1",
        server_url="http://server/api",
        hostname="pod-1",
        logical_name="server",
        lease_seconds=30,
    )

    state = await lease.try_acquire_or_renew()

    assert state.acquired is False
    assert state.owner_instance == "api-2"
