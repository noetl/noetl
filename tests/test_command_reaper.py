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
    assert cursor.params == (24, 90.0, command_reaper._TERMINAL_COMMAND_EVENT_TYPES, 50)

    sql = cursor.query
    assert "COALESCE(meta->>'command_id', result->'data'->>'command_id')" in sql
    assert "t.result->'data'->>'command_id' = claims.command_id" in sql
    assert "t.event_type = ANY(%s)" in sql


@pytest.mark.asyncio
async def test_find_unclaimed_pending_commands_sql_filters_claimed_and_terminal(monkeypatch):
    rows = [{"event_id": 11, "execution_id": 22, "command_id": "cmd-11", "step": "start"}]
    cursor = _FakeCursor(rows)
    conn = _FakeConn(cursor)

    def _fake_get_pool_connection(*_args, **_kwargs):
        return _FakeConnCtx(conn)

    monkeypatch.setattr(command_reaper, "get_pool_connection", _fake_get_pool_connection)

    result = await command_reaper._find_unclaimed_pending_commands(
        pending_retry_seconds=60.0,
        lookback_hours=24,
        max_commands=50,
    )

    assert result == rows
    assert cursor.params == (24, 60.0, command_reaper._TERMINAL_COMMAND_EVENT_TYPES, 50)

    sql = cursor.query
    assert "issued.event_type = 'command.issued'" in sql
    assert "claims.event_type = 'command.claimed'" in sql
    assert "terminal.event_type = ANY(%s)" in sql


@pytest.mark.asyncio
async def test_reap_orphaned_commands_once_republishes_orphaned_and_stranded(monkeypatch):
    orphaned = [{"event_id": 1, "execution_id": 2, "command_id": "cmd-orphaned", "step": "step-a"}]
    stranded = [{"event_id": 3, "execution_id": 4, "command_id": "cmd-stranded", "step": "step-b"}]
    published = []

    class _Publisher:
        async def publish_command(self, **kwargs):
            published.append(kwargs)

    async def _fake_find_orphaned_commands(**_kwargs):
        return orphaned

    async def _fake_find_unclaimed_pending_commands(**_kwargs):
        return stranded

    async def _fake_get_nats_publisher():
        return _Publisher()

    monkeypatch.setattr(command_reaper, "_find_orphaned_commands", _fake_find_orphaned_commands)
    monkeypatch.setattr(command_reaper, "_find_unclaimed_pending_commands", _fake_find_unclaimed_pending_commands)
    monkeypatch.setattr(command_reaper, "_get_nats_publisher", _fake_get_nats_publisher)

    count = await command_reaper.reap_orphaned_commands_once("http://server-noetl.noetl.svc.cluster.local:80")

    assert count == 2
    assert [item["command_id"] for item in published] == ["cmd-orphaned", "cmd-stranded"]


@pytest.mark.asyncio
async def test_reap_orphaned_commands_once_skips_stranded_query_when_capacity_is_exhausted(monkeypatch):
    orphaned = [{"event_id": i, "execution_id": i, "command_id": f"cmd-{i}", "step": "start"} for i in range(100)]
    published = []

    class _Publisher:
        async def publish_command(self, **kwargs):
            published.append(kwargs)

    async def _fake_find_orphaned_commands(**_kwargs):
        return orphaned

    async def _fake_find_unclaimed_pending_commands(**_kwargs):
        raise AssertionError("Stranded query should be skipped when no remaining capacity")

    async def _fake_get_nats_publisher():
        return _Publisher()

    monkeypatch.setattr(command_reaper, "_REAPER_MAX_PER_RUN", 100)
    monkeypatch.setattr(command_reaper, "_find_orphaned_commands", _fake_find_orphaned_commands)
    monkeypatch.setattr(command_reaper, "_find_unclaimed_pending_commands", _fake_find_unclaimed_pending_commands)
    monkeypatch.setattr(command_reaper, "_get_nats_publisher", _fake_get_nats_publisher)

    count = await command_reaper.reap_orphaned_commands_once("http://server-noetl.noetl.svc.cluster.local:80")

    assert count == 100
    assert len(published) == 100
