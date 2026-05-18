from types import SimpleNamespace

import pytest


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

    def cursor(self, **_kwargs):
        return _CursorCtx(self._cursor)

    async def commit(self):
        self.commits += 1


class _ExecuteCursor:
    def __init__(self):
        self.query = ""
        self.params = None
        self.executed = []

    async def execute(self, query, params=None):
        self.query = query
        self.params = params
        self.executed.append((query, params))

    async def fetchone(self):
        if "FROM noetl.catalog" in self.query:
            return {"catalog_id": 5, "path": "playbook/test"}
        if "event_type = 'playbook.initialized'" in self.query:
            return {"event_id": 77}
        return None


class _CancelCursor:
    def __init__(self):
        self.query = ""
        self.params = None
        self.executed = []

    async def execute(self, query, params=None):
        self.query = query
        self.params = params
        self.executed.append((query, params))

    async def fetchone(self):
        if "ORDER BY e.event_id DESC" in self.query:
            return {
                "execution_id": 7,
                "status": "RUNNING",
                "event_type": "command.started",
                "catalog_id": 5,
            }
        if "catalog_id FROM noetl.event" in self.query:
            return {"catalog_id": 5}
        return None

    async def fetchall(self):
        if "WITH RECURSIVE children" in self.query:
            return []
        return []


@pytest.mark.asyncio
async def test_execute_mirrors_initial_command_issued_after_commit(monkeypatch):
    import noetl.server.api.core.commands as commands_module
    import noetl.server.api.core.execution as execution_module
    from noetl.server.api.core.models import ExecuteRequest

    cursor = _ExecuteCursor()
    conn = _FakeConn(cursor)
    mirrored = []
    published = []
    supervised = []
    snowflakes = iter([100, 101])

    class FakeEngine:
        async def start_execution(self, path, payload, catalog_id, parent_execution_id):
            assert path == "playbook/test"
            assert payload == {"facility": "A"}
            assert catalog_id == 5
            assert parent_execution_id is None
            command = SimpleNamespace(
                execution_id=7,
                step="fetch",
                tool=SimpleNamespace(kind="http"),
                max_attempts=3,
                metadata={"stage_id": "stage-1", "frame_id": "frame-1"},
            )
            return "7", [command]

    async def fake_next_snowflake_id(_cur):
        return next(snowflakes)

    async def fake_store_context_if_needed(**kwargs):
        return kwargs["context"]

    async def fake_mirror(events):
        assert conn.commits == 1
        mirrored.extend(events)

    async def fake_publish(items, *, server_url):
        published.extend(items)

    async def fake_supervise(execution_id, command_id, step, *, event_id, meta):
        supervised.append((execution_id, command_id, step, event_id, meta))

    monkeypatch.setattr(execution_module, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(execution_module, "get_pool_connection", lambda: _ConnCtx(conn))
    monkeypatch.setattr(execution_module, "_next_snowflake_id", fake_next_snowflake_id)
    monkeypatch.setattr(execution_module, "_mirror_execution_events", fake_mirror)
    monkeypatch.setattr(execution_module, "_publish_commands_with_recovery", fake_publish)
    monkeypatch.setattr(execution_module, "supervise_command_issued", fake_supervise)
    monkeypatch.setattr(commands_module, "_build_command_context", lambda _cmd: {"url": "https://example.test"})
    monkeypatch.setattr(commands_module, "_validate_postgres_command_context_or_422", lambda **_kwargs: None)
    monkeypatch.setattr(commands_module, "_store_command_context_if_needed", fake_store_context_if_needed)

    result = await execution_module.execute(
        ExecuteRequest(path="playbook/test", workload={"facility": "A"})
    )

    assert result.commands_generated == 1
    assert mirrored[0]["event_type"] == "command.issued"
    assert mirrored[0]["event_id"] == 101
    assert mirrored[0]["command_id"] == 100
    assert mirrored[0]["parent_event_id"] == 77
    assert mirrored[0]["stage_id"] == "stage-1"
    assert mirrored[0]["frame_id"] == "frame-1"
    assert published == [(7, 101, 100, "fetch")]
    assert supervised[0][:4] == ("7", 100, "fetch", 101)


@pytest.mark.asyncio
async def test_cancel_execution_mirrors_cancelled_event_after_commit(monkeypatch):
    import noetl.server.api.execution.endpoint as endpoint
    from noetl.server.api.execution.schema import CancelExecutionRequest

    cursor = _CancelCursor()
    conn = _FakeConn(cursor)
    mirrored = []

    async def fake_mirror(events):
        assert conn.commits == 1
        mirrored.extend(events)

    monkeypatch.setattr(endpoint, "get_pool_connection", lambda: _ConnCtx(conn))
    async def fake_snowflake_id():
        return 9001

    monkeypatch.setattr(endpoint, "get_snowflake_id", fake_snowflake_id)
    monkeypatch.setattr(endpoint, "_mirror_execution_route_events", fake_mirror)

    result = await endpoint.cancel_execution(
        "7",
        CancelExecutionRequest(reason="operator requested", cascade=False),
    )

    assert result.status == "cancelled"
    assert mirrored[0]["event_id"] == 9001
    assert mirrored[0]["event_type"] == "execution.cancelled"
    assert mirrored[0]["execution_id"] == 7
    assert mirrored[0]["status"] == "CANCELLED"
    assert mirrored[0]["meta"]["reason"] == "operator requested"
