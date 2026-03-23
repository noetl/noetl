import httpx
import pytest

import noetl.worker.v2_worker_nats as worker_module
from noetl.worker.v2_worker_nats import V2Worker
from noetl.core.storage.models import ResultRef, ResultRefMeta, Scope, StoreTier


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
        self.json_seen = []

    async def post(self, *_args, **kwargs):
        self.headers_seen.append(dict(kwargs.get("headers") or {}))
        self.json_seen.append(kwargs.get("json"))
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


@pytest.mark.asyncio
async def test_emit_batch_events_externalizes_large_response_payload(monkeypatch):
    worker = V2Worker(worker_id="worker-test")
    worker._http_client = _SequenceHttpClient(
        [_FakeResponse(202, payload={"status": "accepted", "request_id": "req-2"})]
    )

    async def _fake_put(**kwargs):
        return ResultRef.create(
            execution_id=str(kwargs["execution_id"]),
            name=str(kwargs["name"]),
            store=StoreTier.KV,
            scope=Scope.EXECUTION,
            meta=ResultRefMeta(bytes=4096),
        )

    monkeypatch.setenv("NOETL_EVENT_INLINE_MAX_BYTES", "128")
    monkeypatch.setattr(worker_module.default_store, "put", _fake_put)

    events = [
        {"step": "s1", "name": "command.started", "payload": {}, "actionable": False, "informative": True},
        {
            "step": "s1",
            "name": "call.done",
            "payload": {"response": {"rows": ["x" * 8192]}},
            "actionable": True,
            "informative": True,
        },
    ]

    ok = await worker._emit_batch_events(
        server_url="http://server",
        execution_id=123,
        events=events,
        timeout_seconds=0.1,
        max_retries=1,
    )

    assert ok is True
    sent = worker._http_client.json_seen[0]
    response_payload = sent["events"][1]["payload"]["response"]
    assert "_ref" in response_payload
    assert response_payload["_ref"]["kind"] == "result_ref"
    assert response_payload["_store"] == "kv"


@pytest.mark.asyncio
async def test_claim_and_fetch_command_resolves_externalized_context(monkeypatch):
    worker = V2Worker(worker_id="worker-test")
    worker._http_client = _SequenceHttpClient(
        [
            _FakeResponse(
                200,
                payload={
                    "execution_id": 123,
                    "node_id": "step1",
                    "node_name": "step1",
                    "action": "python",
                    "context": {
                        "kind": "temp_ref",
                        "ref": "noetl://execution/123/result/step1_context/abcd1234",
                    },
                    "meta": {"command_id": "123:step1:1"},
                },
            )
        ]
    )

    async def _fake_resolve(_ref):
        return {
            "tool_config": {"kind": "python"},
            "args": {"value": 1},
            "render_context": {"foo": "bar"},
        }

    monkeypatch.setattr(worker_module.default_store, "resolve", _fake_resolve)

    command, decision, retry_after = await worker._claim_and_fetch_command(
        server_url="http://server",
        event_id=99,
    )

    assert decision == "claimed"
    assert retry_after == 0.0
    assert command is not None
    assert command["context"]["render_context"]["foo"] == "bar"
