import httpx
import pytest

from noetl.worker.v2_worker_nats import V2Worker


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://server/api/events/batch")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)


class _SequenceHttpClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.headers_seen = []

    async def post(self, *_args, **kwargs):
        self.headers_seen.append(dict(kwargs.get("headers") or {}))
        if not self._responses:
            raise RuntimeError("no more fake responses")
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_emit_batch_events_reuses_idempotency_key_across_retries():
    worker = V2Worker(worker_id="worker-test")
    worker._http_client = _SequenceHttpClient(
        [
            _FakeResponse(
                503,
                payload={"detail": {"code": "ack_timeout", "message": "queue full"}},
                headers={"Retry-After": "0"},
            ),
            _FakeResponse(202, payload={"status": "accepted", "request_id": "req-1"}),
        ]
    )

    events = [
        {"step": "s1", "name": "command.started", "payload": {}, "actionable": False, "informative": True},
        {"step": "s1", "name": "call.done", "payload": {"ok": True}, "actionable": True, "informative": True},
    ]
    ok = await worker._emit_batch_events(
        server_url="http://server",
        execution_id=123,
        events=events,
        timeout_seconds=0.1,
        max_retries=2,
    )

    assert ok is True
    assert len(worker._http_client.headers_seen) == 2
    first_key = worker._http_client.headers_seen[0]["Idempotency-Key"]
    second_key = worker._http_client.headers_seen[1]["Idempotency-Key"]
    assert first_key
    assert first_key == second_key
