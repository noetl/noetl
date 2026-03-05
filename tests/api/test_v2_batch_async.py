import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import noetl.server.api.v2 as v2_api


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
