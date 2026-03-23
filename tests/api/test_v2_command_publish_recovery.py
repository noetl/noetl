import asyncio

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


@pytest.mark.asyncio
async def test_publish_commands_with_recovery_tracks_and_cleans_up_tasks(monkeypatch):
    published = []

    class _Publisher:
        async def publish_command(self, **kwargs):
            published.append(kwargs)

    async def _fake_get_nats_publisher():
        return _Publisher()

    async def _fake_recover_unclaimed_command_after_delay(**_kwargs):
        return None

    monkeypatch.setattr(v2, "get_nats_publisher", _fake_get_nats_publisher)
    monkeypatch.setattr(v2, "_recover_unclaimed_command_after_delay", _fake_recover_unclaimed_command_after_delay)

    v2._publish_recovery_tasks.clear()
    await v2._publish_commands_with_recovery(
        [(1, 2, "cmd-1", "start")],
        server_url="http://server",
    )
    await asyncio.gather(*list(v2._publish_recovery_tasks), return_exceptions=True)
    await asyncio.sleep(0)

    assert published == [
        {
            "execution_id": 1,
            "event_id": 2,
            "command_id": "cmd-1",
            "step": "start",
            "server_url": "http://server",
        }
    ]
    assert not v2._publish_recovery_tasks


@pytest.mark.asyncio
async def test_publish_commands_with_recovery_schedules_task_after_initial_publish_failure(monkeypatch):
    published = []
    recovery_calls = []

    class _Publisher:
        async def publish_command(self, **kwargs):
            published.append(kwargs)
            raise RuntimeError("publish failed")

    async def _fake_get_nats_publisher():
        return _Publisher()

    async def _fake_recover_unclaimed_command_after_delay(**kwargs):
        recovery_calls.append(kwargs)
        return None

    monkeypatch.setattr(v2, "get_nats_publisher", _fake_get_nats_publisher)
    monkeypatch.setattr(v2, "_recover_unclaimed_command_after_delay", _fake_recover_unclaimed_command_after_delay)

    v2._publish_recovery_tasks.clear()
    await v2._publish_commands_with_recovery(
        [(1, 2, "cmd-1", "start")],
        server_url="http://server",
    )
    await asyncio.gather(*list(v2._publish_recovery_tasks), return_exceptions=True)
    await asyncio.sleep(0)

    assert published == [
        {
            "execution_id": 1,
            "event_id": 2,
            "command_id": "cmd-1",
            "step": "start",
            "server_url": "http://server",
        }
    ]
    assert recovery_calls == [
        {
            "execution_id": 1,
            "event_id": 2,
            "command_id": "cmd-1",
            "step": "start",
            "server_url": "http://server",
            "delay_seconds": v2._COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS,
        }
    ]
    assert not v2._publish_recovery_tasks


@pytest.mark.asyncio
async def test_publish_commands_with_recovery_schedules_task_when_publisher_init_fails(monkeypatch):
    recovery_calls = []

    async def _fake_get_nats_publisher():
        raise RuntimeError("publisher unavailable")

    async def _fake_recover_unclaimed_command_after_delay(**kwargs):
        recovery_calls.append(kwargs)
        return None

    monkeypatch.setattr(v2, "get_nats_publisher", _fake_get_nats_publisher)
    monkeypatch.setattr(v2, "_recover_unclaimed_command_after_delay", _fake_recover_unclaimed_command_after_delay)

    v2._publish_recovery_tasks.clear()
    await v2._publish_commands_with_recovery(
        [(1, 2, "cmd-1", "start")],
        server_url="http://server",
    )
    await asyncio.gather(*list(v2._publish_recovery_tasks), return_exceptions=True)
    await asyncio.sleep(0)

    assert recovery_calls == [
        {
            "execution_id": 1,
            "event_id": 2,
            "command_id": "cmd-1",
            "step": "start",
            "server_url": "http://server",
            "delay_seconds": v2._COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS,
        }
    ]
    assert not v2._publish_recovery_tasks


@pytest.mark.asyncio
async def test_shutdown_publish_recovery_tasks_cancels_and_awaits_tasks():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _never_finishes():
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(_never_finishes())
    await started.wait()
    v2._publish_recovery_tasks.clear()
    v2._track_publish_recovery_task(task)

    await v2.shutdown_publish_recovery_tasks()

    assert cancelled.is_set()
    assert not v2._publish_recovery_tasks
