import pytest

import noetl.server.command_reaper as command_reaper


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.query = None
        self.params = None

    async def execute(self, query, params):
        self.query = query
        self.params = params

    async def fetchall(self):
        return self._rows


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

    def cursor(self, row_factory=None):
        return _FakeCursorCtx(self._cursor)


class _FakeConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_find_orphaned_commands_sql_handles_meta_and_result_command_ids(monkeypatch):
    rows = [{"event_id": 1, "execution_id": 2, "command_id": "cmd-1", "step": "start"}]
    cursor = _FakeCursor(rows)
    conn = _FakeConn(cursor)

    def _fake_get_pool_connection(*_args, **_kwargs):
        return _FakeConnCtx(conn)

    monkeypatch.setattr(command_reaper, "get_pool_connection", _fake_get_pool_connection)

    result = await command_reaper._find_orphaned_commands(
        stale_seconds=90.0,
        lookback_hours=24,
        max_commands=50,
    )

    assert result == rows
    assert cursor.params == (24, 90.0, 50)

    sql = cursor.query
    assert "COALESCE(meta->>'command_id', result->'data'->>'command_id')" in sql
    assert "t.result->'data'->>'command_id' = claims.command_id" in sql
