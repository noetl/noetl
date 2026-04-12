import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import noetl.server.api.core as v2_api


def _make_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("utf-8"), value.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/events/batch",
        "headers": raw_headers,
        "query_string": b"",
    }
    return Request(scope)


def _build_acceptance_result(
    request_id: str = "req-123",
    event_ids: list[int] | None = None,
    duplicate: bool = False,
) -> v2_api._BatchAcceptanceResult:
    job = v2_api._BatchAcceptJob(
        request_id=request_id,
        execution_id=1,
        catalog_id=10,
        worker_id="worker-1",
        idempotency_key="idem-key-1",
        events=[],
        last_actionable_event=None,
        last_actionable_evt_id=None,
        accepted_event_id=99,
        accepted_at_monotonic=0.0,
    )
    return v2_api._BatchAcceptanceResult(job=job, event_ids=event_ids or [1, 2], duplicate=duplicate)


def test_extract_command_id_from_payload_supports_nested_result_context():
    payload = {
        "result": {
            "context": {
                "command_id": "cmd-nested",
            }
        }
    }
    assert v2_api._extract_command_id_from_payload(payload, None) == "cmd-nested"


@pytest.mark.asyncio
async def test_batch_enqueue_ack_timeout_under_queue_pressure(monkeypatch):
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait(object())  # Simulate high load / full queue.

    async def _ready_workers() -> bool:
        return True

    async def _acceptance(_req, _idempotency):
        return _build_acceptance_result()

    captured = {}

    async def _capture_failed(job, code, message):
        captured["request_id"] = job.request_id
        captured["code"] = code
        captured["message"] = message

    monkeypatch.setattr(v2_api, "_batch_accept_queue", queue)
    monkeypatch.setattr(v2_api, "_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(v2_api, "ensure_batch_acceptor_started", _ready_workers)
    monkeypatch.setattr(v2_api, "_persist_batch_acceptance", _acceptance)
    monkeypatch.setattr(v2_api, "_persist_batch_failed_event", _capture_failed)

    req = v2_api.BatchEventRequest(execution_id="1", worker_id="worker-1", events=[])
    with pytest.raises(HTTPException) as exc:
        await v2_api.handle_batch_events(req, _make_request({"Idempotency-Key": "idem-key-1"}))

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == v2_api._BATCH_FAILURE_ENQUEUE_TIMEOUT
    assert captured["code"] == v2_api._BATCH_FAILURE_ENQUEUE_TIMEOUT
    assert captured["request_id"] == "req-123"


@pytest.mark.asyncio
async def test_batch_duplicate_idempotency_returns_accepted_without_enqueue(monkeypatch):
    queue = asyncio.Queue(maxsize=2)

    async def _ready_workers() -> bool:
        return True

    async def _acceptance(_req, _idempotency):
        return _build_acceptance_result(request_id="req-dup-1", duplicate=True, event_ids=[7, 8])

    monkeypatch.setattr(v2_api, "_batch_accept_queue", queue)
    monkeypatch.setattr(v2_api, "ensure_batch_acceptor_started", _ready_workers)
    monkeypatch.setattr(v2_api, "_persist_batch_acceptance", _acceptance)

    req = v2_api.BatchEventRequest(execution_id="1", worker_id="worker-1", events=[])
    res = await v2_api.handle_batch_events(req, _make_request({"Idempotency-Key": "idem-key-1"}))

    assert res.status == "accepted"
    assert res.duplicate is True
    assert res.request_id == "req-dup-1"
    assert res.event_ids == [7, 8]
    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_batch_worker_unavailable_error_code(monkeypatch):
    async def _no_workers() -> bool:
        return False

    monkeypatch.setattr(v2_api, "ensure_batch_acceptor_started", _no_workers)
    monkeypatch.setattr(v2_api, "_batch_accept_queue", asyncio.Queue(maxsize=1))

    req = v2_api.BatchEventRequest(execution_id="1", worker_id="worker-1", events=[])
    with pytest.raises(HTTPException) as exc:
        await v2_api.handle_batch_events(req, _make_request())

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == v2_api._BATCH_FAILURE_WORKER_UNAVAILABLE


@pytest.mark.asyncio
async def test_persist_batch_acceptance_stores_command_id_in_meta(monkeypatch):
    class _CursorCtx:
        def __init__(self, cursor):
            self._cursor = cursor

        async def __aenter__(self):
            return self._cursor

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _PersistCursor:
        def __init__(self):
            self.insert_params = []
            self._fetch_calls = 0

        async def execute(self, query, params=None):
            if "INSERT INTO noetl.event" in query:
                self.insert_params.append(params)

        async def fetchone(self):
            self._fetch_calls += 1
            if self._fetch_calls == 1:
                return {"catalog_id": 10}
            return None

    class _PersistConn:
        def __init__(self, cursor):
            self._cursor = cursor

        def cursor(self, row_factory=None):
            return _CursorCtx(self._cursor)

        async def commit(self):
            return None

    class _ConnCtx:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_cursor = _PersistCursor()
    fake_conn = _PersistConn(fake_cursor)

    def _fake_get_pool_connection(*_args, **_kwargs):
        return _ConnCtx(fake_conn)

    next_ids = iter(range(1000, 1200))

    async def _fake_next_snowflake_id(_cur):
        return next(next_ids)

    monkeypatch.setattr(v2_api, "get_pool_connection", _fake_get_pool_connection)
    monkeypatch.setattr(v2_api, "_next_snowflake_id", _fake_next_snowflake_id)

    req = v2_api.BatchEventRequest(
        execution_id="42",
        worker_id="worker-1",
        events=[
            v2_api.BatchEventItem(
                step="tool_step",
                name="command.completed",
                payload={
                    "result": {"status": "COMPLETED"},
                    "command_id": "cmd-42",
                },
                actionable=False,
                informative=True,
            )
        ],
    )

    acceptance = await v2_api._persist_batch_acceptance(req, idempotency_key=None)
    assert acceptance.duplicate is False
    inserted_command_completed = [
        params
        for params in fake_cursor.insert_params
        if isinstance(params, tuple) and len(params) > 8 and params[3] == "command.completed"
    ]
    assert inserted_command_completed
    meta_obj = inserted_command_completed[0][8].obj
    assert meta_obj["command_id"] == "cmd-42"


@pytest.mark.asyncio
async def test_process_accepted_batch_invalidates_state_cache_when_command_issue_fails(monkeypatch):
    invalidations = []

    class FakeStateStore:
        async def invalidate_state(self, execution_id, reason="manual"):
            invalidations.append((execution_id, reason))
            return True

    class FakeEngine:
        def __init__(self):
            self.state_store = FakeStateStore()

        async def handle_event(self, _event, already_persisted=False):
            assert already_persisted is True
            return [SimpleNamespace(step="next")]

    async def _fail_issue(_job, _commands):
        raise RuntimeError("command insert failed")

    fake_engine = FakeEngine()
    monkeypatch.setattr(v2_api, "get_engine", lambda: fake_engine)
    monkeypatch.setattr(v2_api, "_issue_commands_for_batch", _fail_issue)

    job = _build_acceptance_result().job
    job.last_actionable_event = SimpleNamespace(name="call.done")

    with pytest.raises(RuntimeError, match="command insert failed"):
        await v2_api._process_accepted_batch(job)

    assert invalidations
    assert invalidations[0][0] == "1"
    assert invalidations[0][1].startswith("batch_command_issue_failed:")


@pytest.mark.asyncio
async def test_handle_event_invalidates_state_cache_when_command_persist_fails(monkeypatch):
    invalidations = []

    class FakeStateStore:
        async def invalidate_state(self, execution_id, reason="manual"):
            invalidations.append((execution_id, reason))
            return True

    class FakeEngine:
        def __init__(self):
            self.state_store = FakeStateStore()

        async def handle_event(self, _event, already_persisted=False):
            assert already_persisted is True
            return [SimpleNamespace(step="next")]

    class _CursorCtx:
        def __init__(self, cursor):
            self._cursor = cursor

        async def __aenter__(self):
            return self._cursor

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _PersistCursor:
        async def execute(self, *_args, **_kwargs):
            return None

        async def fetchone(self):
            return {"catalog_id": 10}

    class _PersistConn:
        def cursor(self, row_factory=None):
            return _CursorCtx(_PersistCursor())

        async def commit(self):
            return None

    class _ConnCtx:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FailConnCtx:
        async def __aenter__(self):
            raise RuntimeError("command persist failed")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    calls = {"count": 0}

    def _fake_get_pool_connection():
        calls["count"] += 1
        if calls["count"] == 1:
            return _ConnCtx(_PersistConn())
        return _FailConnCtx()

    async def _fake_get_nats_publisher():
        return SimpleNamespace()

    async def _fake_next_snowflake_id(_cur):
        return 12345

    fake_engine = FakeEngine()
    monkeypatch.setattr(v2_api, "get_engine", lambda: fake_engine)
    monkeypatch.setattr(v2_api, "get_pool_connection", _fake_get_pool_connection)
    monkeypatch.setattr(v2_api, "_next_snowflake_id", _fake_next_snowflake_id)
    monkeypatch.setattr(v2_api, "get_nats_publisher", _fake_get_nats_publisher)

    req = v2_api.EventRequest(
        execution_id="42",
        step="step1",
        name="call.done",
        payload={"status": "completed"},
    )

    with pytest.raises(HTTPException) as exc:
        await v2_api.handle_event(req)

    assert exc.value.status_code == 500
    assert invalidations
    assert invalidations[0][0] == "42"
    assert invalidations[0][1].startswith("command_issue_failed:")
