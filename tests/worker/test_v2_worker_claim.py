import pytest

import noetl.worker.v2_worker_nats as worker_module
from noetl.worker.v2_worker_nats import V2Worker


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


class _FakeHttpClient:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def post(self, *_args, **_kwargs):
        return self._response


@pytest.mark.asyncio
async def test_claim_conflict_active_claim_returns_retry_later():
    worker = V2Worker(worker_id="test-worker")
    worker._http_client = _FakeHttpClient(
        _FakeResponse(
            409,
            payload={"detail": {"code": "active_claim", "message": "claimed elsewhere"}},
            headers={"Retry-After": "2"},
        )
    )

    command, decision, retry_after = await worker._claim_and_fetch_command("http://server", 1)

    assert command is None
    assert decision == "retry_later"
    assert retry_after >= worker._active_claim_retry_floor_seconds


@pytest.mark.asyncio
async def test_claim_conflict_plain_message_returns_retry_later():
    worker = V2Worker(worker_id="test-worker")
    worker._http_client = _FakeHttpClient(
        _FakeResponse(
            409,
            payload={"detail": "Command is being claimed by another worker"},
        )
    )

    command, decision, retry_after = await worker._claim_and_fetch_command("http://server", 2)

    assert command is None
    assert decision == "retry_later"
    assert retry_after >= 1.0


@pytest.mark.asyncio
async def test_claim_conflict_terminal_code_returns_skip_ack():
    worker = V2Worker(worker_id="test-worker")
    worker._http_client = _FakeHttpClient(
        _FakeResponse(
            409,
            payload={"detail": {"code": "already_terminal", "message": "terminal"}},
        )
    )

    command, decision, retry_after = await worker._claim_and_fetch_command("http://server", 3)

    assert command is None
    assert decision == "skip_ack"
    assert retry_after == 0.0


@pytest.mark.asyncio
async def test_claim_conflict_unknown_code_defaults_retry_later():
    worker = V2Worker(worker_id="test-worker")
    worker._http_client = _FakeHttpClient(
        _FakeResponse(
            409,
            payload={"detail": {"code": "lock_conflict_unknown", "message": "conflict"}},
        )
    )

    command, decision, retry_after = await worker._claim_and_fetch_command("http://server", 4)

    assert command is None
    assert decision == "retry_later"
    assert retry_after >= 1.0


@pytest.mark.asyncio
async def test_claim_conflict_active_claim_uses_jittered_delay_above_floor(monkeypatch):
    worker = V2Worker(worker_id="test-worker")
    worker._http_client = _FakeHttpClient(
        _FakeResponse(
            409,
            payload={"detail": {"code": "active_claim", "message": "claimed elsewhere"}},
            headers={"Retry-After": "2"},
        )
    )
    monkeypatch.setattr(worker_module.random, "uniform", lambda _a, _b: 0.30)

    command, decision, retry_after = await worker._claim_and_fetch_command("http://server", 5)

    assert command is None
    assert decision == "retry_later"
    assert retry_after > worker._active_claim_retry_floor_seconds
    assert retry_after <= (worker._active_claim_retry_floor_seconds * 1.5) + 1e-6
