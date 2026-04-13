import httpx
import pytest

import noetl.worker.nats_worker as worker_module
from noetl.worker.nats_worker import V2Worker


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


def test_normalize_output_config_supports_canonical_tool_output():
    worker = V2Worker(worker_id="worker-test")

    normalized = worker._normalize_output_config(
        {
            "output": {
                "store": {"kind": "kv"},
                "inline_max_bytes": 0,
                "select": [
                    {"path": "data.result.command_0.rows"},
                    "status",
                ],
            }
        }
    )

    assert normalized["store"] == {"kind": "kv"}
    assert normalized["inline_max_bytes"] == 0
    assert normalized["output_select"] == [
        "data.result.command_0.rows",
        "status",
    ]


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

    events = [
        {"step": "s1", "name": "command.started", "payload": {}, "actionable": False, "informative": True},
        {
            "step": "s1",
            "name": "call.done",
            "payload": {
                "response": {
                    "_ref": {
                        "kind": "result_ref",
                        "ref": "noetl://execution/123/result/s1/abcd1234",
                        "store": "kv",
                    },
                    "_store": "kv",
                    "_size_bytes": 8192,
                }
            },
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
    result_payload = sent["events"][1]["payload"]["result"]
    assert "response" not in sent["events"][1]["payload"]
    assert result_payload["status"] == "COMPLETED"
    assert result_payload["reference"]["locator"] == "noetl://execution/123/result/s1/abcd1234"
    assert result_payload["reference"]["type"] == "nats"


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
            "input": {"value": 1},
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


@pytest.mark.asyncio
async def test_execute_command_resolves_nested_externalized_context_fields(monkeypatch):
    worker = V2Worker(worker_id="worker-test")

    resolved_refs = {
        "noetl://execution/123/result/tool/abcd1234": {"kind": "python", "code": "return 1"},
        "noetl://execution/123/result/render/abcd1234": {"foo": "bar"},
    }

    async def _fake_resolve(ref):
        return resolved_refs[ref["ref"]]

    async def _fake_emit_batch_events(*_args, **_kwargs):
        return True

    async def _fake_emit_event(*_args, **_kwargs):
        return None

    async def _fake_execute_tool(tool_kind, config, args, step, render_context):
        assert tool_kind == "python"
        assert config["code"] == "return 1"
        assert render_context["foo"] == "bar"
        return {"status": "ok", "data": {"value": 1}}

    monkeypatch.setattr(worker_module.default_store, "resolve", _fake_resolve)
    monkeypatch.setattr(V2Worker, "_emit_batch_events", _fake_emit_batch_events)
    monkeypatch.setattr(V2Worker, "_emit_event", _fake_emit_event)
    monkeypatch.setattr(V2Worker, "_execute_tool", _fake_execute_tool)

    await worker._execute_command(
        {
            "execution_id": 123,
            "node_name": "step1",
            "action": "python",
            "context": {
                "tool_config": {
                    "kind": "temp_ref",
                    "ref": "noetl://execution/123/result/tool/abcd1234",
                },
                "render_context": {
                    "kind": "temp_ref",
                    "ref": "noetl://execution/123/result/render/abcd1234",
                },
                "input": {},
                "spec": {},
            },
            "meta": {},
        },
        server_url="http://server",
        command_id="123:step1:1",
    )
