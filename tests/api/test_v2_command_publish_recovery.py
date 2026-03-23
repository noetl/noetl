import pytest

from noetl.server.api import v2


class _FakeCursor:
    def __init__(self, row):
        self._row = row
        self.query = None
        self.params = None

    async def execute(self, query, params):
        self.query = query
        self.params = params

    async def fetchone(self):
        return self._row


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
async def test_publish_recovery_republishes_unclaimed_command(monkeypatch):
    published = []
    cursor = _FakeCursor({"has_claim_or_terminal": False})
    conn = _FakeConn(cursor)

    class _Publisher:
        async def publish_command(self, **kwargs):
            published.append(kwargs)

    async def _fake_sleep(_seconds):
        return None

    def _fake_get_pool_connection(*_args, **_kwargs):
        return _FakeConnCtx(conn)

    async def _fake_get_nats_publisher():
        return _Publisher()

    monkeypatch.setattr(v2.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(v2, "get_pool_connection", _fake_get_pool_connection)
    monkeypatch.setattr(v2, "get_nats_publisher", _fake_get_nats_publisher)

    await v2._recover_unclaimed_command_after_delay(
        execution_id=1,
        event_id=2,
        command_id="cmd-1",
        step="start",
        server_url="http://server",
        delay_seconds=0,
    )

    assert cursor.params == (
        1,
        "cmd-1",
        "cmd-1",
        v2._COMMAND_TERMINAL_EVENT_TYPES,
        "cmd-1",
        "cmd-1",
    )
    assert published == [
        {
            "execution_id": 1,
            "event_id": 2,
            "command_id": "cmd-1",
            "step": "start",
            "server_url": "http://server",
        }
    ]


@pytest.mark.asyncio
async def test_publish_recovery_skips_claimed_command(monkeypatch):
    published = []
    cursor = _FakeCursor({"has_claim_or_terminal": True})
    conn = _FakeConn(cursor)

    class _Publisher:
        async def publish_command(self, **kwargs):
            published.append(kwargs)

    async def _fake_sleep(_seconds):
        return None

    def _fake_get_pool_connection(*_args, **_kwargs):
        return _FakeConnCtx(conn)

    async def _fake_get_nats_publisher():
        return _Publisher()

    monkeypatch.setattr(v2.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(v2, "get_pool_connection", _fake_get_pool_connection)
    monkeypatch.setattr(v2, "get_nats_publisher", _fake_get_nats_publisher)

    await v2._recover_unclaimed_command_after_delay(
        execution_id=1,
        event_id=2,
        command_id="cmd-1",
        step="start",
        server_url="http://server",
        delay_seconds=0,
    )

    assert published == []
