import pytest

from noetl.worker.nats_worker import Worker


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
        self.calls = []

    async def post(self, *_args, **_kwargs):
        self.calls.append(("post", _args, _kwargs))
        return self._response


async def _noop_execute(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_claim_conflict_active_claim_returns_skip_ack():
    worker = Worker(worker_id="test-worker")
    worker._http_client = _FakeHttpClient(
        _FakeResponse(
            409,
            payload={"detail": {"code": "active_claim", "message": "claimed elsewhere"}},
            headers={"Retry-After": "2"},
        )
    )

    command, decision, retry_after = await worker._claim_and_fetch_command("http://server", 1)

    assert command is None
    assert decision == "skip_ack"
    assert retry_after == 0.0


@pytest.mark.asyncio
async def test_claim_conflict_plain_message_returns_skip_ack():
    worker = Worker(worker_id="test-worker")
    worker._http_client = _FakeHttpClient(
        _FakeResponse(
            409,
            payload={"detail": "Command is being claimed by another worker"},
        )
    )

    command, decision, retry_after = await worker._claim_and_fetch_command("http://server", 2)

    assert command is None
    assert decision == "skip_ack"
    assert retry_after == 0.0


@pytest.mark.asyncio
async def test_claim_conflict_terminal_code_returns_skip_ack():
    worker = Worker(worker_id="test-worker")
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
    worker = Worker(worker_id="test-worker")
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
async def test_claim_url_normalizes_server_url_with_api_suffix():
    worker = Worker(worker_id="test-worker")
    fake_client = _FakeHttpClient(
        _FakeResponse(
            409,
            payload={"detail": {"code": "active_claim", "message": "claimed elsewhere"}},
            headers={"Retry-After": "2"},
        )
    )
    worker._http_client = fake_client

    await worker._claim_and_fetch_command("http://server/api", 42)

    assert fake_client.calls
    method, args, _kwargs = fake_client.calls[0]
    assert method == "post"
    assert args[0] == "http://server/api/commands/42/claim"


@pytest.mark.asyncio
async def test_emit_command_failed_normalizes_server_url_with_api_suffix():
    worker = Worker(worker_id="test-worker")
    fake_client = _FakeHttpClient(_FakeResponse(200, payload={"status": "ok"}))
    worker._http_client = fake_client

    await worker._emit_command_failed("http://server/api", 100, "cmd-1", "step-a", "boom")

    assert fake_client.calls
    method, args, _kwargs = fake_client.calls[0]
    assert method == "post"
    assert args[0] == "http://server/api/events"


@pytest.mark.asyncio
async def test_claim_url_normalizes_server_url_with_duplicate_api_suffix():
    worker = Worker(worker_id="test-worker")
    fake_client = _FakeHttpClient(
        _FakeResponse(
            409,
            payload={"detail": {"code": "active_claim", "message": "claimed elsewhere"}},
            headers={"Retry-After": "2"},
        )
    )
    worker._http_client = fake_client

    await worker._claim_and_fetch_command("http://server/api/api", 42)

    assert fake_client.calls
    method, args, _kwargs = fake_client.calls[0]
    assert method == "post"
    assert args[0] == "http://server/api/commands/42/claim"


@pytest.mark.asyncio
async def test_duplicate_active_claim_notification_is_short_circuited_locally():
    worker = Worker(worker_id="test-worker")
    fake_client = _FakeHttpClient(
        _FakeResponse(
            409,
            payload={"detail": {"code": "active_claim", "message": "claimed elsewhere"}},
            headers={"Retry-After": "2"},
        )
    )
    worker._http_client = fake_client
    worker._running = True
    worker._execute_command = _noop_execute
    notification = {
        "execution_id": 1,
        "event_id": 100,
        "command_id": "exec:start:1",
        "step": "start",
        "server_url": "http://server",
    }

    first = await worker._handle_command_notification(notification)
    second = await worker._handle_command_notification(notification)

    assert first == "ack"
    assert second == "ack"
    assert len(fake_client.calls) == 1


@pytest.mark.asyncio
async def test_duplicate_claimed_notification_is_short_circuited_locally():
    worker = Worker(worker_id="test-worker")
    fake_client = _FakeHttpClient(
        _FakeResponse(
            200,
            payload={
                "execution_id": 1,
                "node_id": "start",
                "node_name": "start",
                "action": "noop",
                "context": {},
                "meta": {},
            },
        )
    )
    worker._http_client = fake_client
    worker._running = True
    worker._execute_command = _noop_execute
    notification = {
        "execution_id": 1,
        "event_id": 101,
        "command_id": "exec:start:2",
        "step": "start",
        "server_url": "http://server",
    }

    first = await worker._handle_command_notification(notification)
    second = await worker._handle_command_notification(notification)

    assert first == "ack"
    assert second == "ack"
    assert len(fake_client.calls) == 1
