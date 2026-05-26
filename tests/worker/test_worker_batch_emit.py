import httpx
import pytest

import noetl.worker.nats_worker as worker_module
from noetl.worker.nats_worker import Worker


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
    worker = Worker(worker_id="worker-test")

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
    worker = Worker(worker_id="worker-test")
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
    worker = Worker(worker_id="worker-test")
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
    worker = Worker(worker_id="worker-test")
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
    worker = Worker(worker_id="worker-test")

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
    monkeypatch.setattr(Worker, "_emit_batch_events", _fake_emit_batch_events)
    monkeypatch.setattr(Worker, "_emit_event", _fake_emit_event)
    monkeypatch.setattr(Worker, "_execute_tool", _fake_execute_tool)

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


@pytest.mark.asyncio
async def test_execute_command_task_sequence_bounds_initial_event_emit(monkeypatch):
    worker = Worker(worker_id="worker-test")
    batch_calls = []

    async def _fake_emit_batch_events(_self, _server_url, _execution_id, events, **kwargs):
        batch_calls.append({"events": events, **kwargs})
        return True

    async def _fake_execute_tool(_self, tool_kind, config, args, step, render_context, case_blocks=None):
        assert tool_kind == "task_sequence"
        return {"status": "ok", "data": {"value": 1}}

    async def _fake_process_result(_self, step_name, result, output_config=None):
        return {"_value": result.get("data")}

    from noetl.worker.result_handler import ResultHandler
    monkeypatch.setattr(ResultHandler, "process_result", _fake_process_result)


    monkeypatch.setattr(Worker, "_emit_batch_events", _fake_emit_batch_events)
    monkeypatch.setattr(Worker, "_execute_tool", _fake_execute_tool)

    await worker._execute_command(
        {
            "execution_id": 123,
            "node_name": "hot_loop",
            "action": "task_sequence",
            "context": {
                "tool_config": {"tasks": []},
                "input": {},
                "render_context": {},
                "spec": {},
            },
            "meta": {},
        },
        server_url="http://server",
        command_id="123:hot_loop:1",
    )

    assert len(batch_calls) == 2
    assert batch_calls[0]["events"][0]["name"] == "command.started"
    assert batch_calls[0]["timeout_seconds"] == pytest.approx(
        worker_module._HOT_PATH_INITIAL_EVENT_TIMEOUT_SECONDS
    )
    assert batch_calls[0]["max_retries"] == worker_module._HOT_PATH_INITIAL_EVENT_MAX_RETRIES
    assert batch_calls[0]["raise_on_failure"] is False


@pytest.mark.asyncio
async def test_execute_command_continues_when_hot_path_initial_events_timeout(monkeypatch):
    worker = Worker(worker_id="worker-test")
    seen_terminal_batch = []

    async def _fake_emit_batch_events(_self, _server_url, _execution_id, events, **kwargs):
        if events and events[0]["name"] == "command.started":
            return False
        seen_terminal_batch.extend(events)
        return True

    async def _fake_execute_tool(_self, tool_kind, config, args, step, render_context, case_blocks=None):
        return {"status": "ok", "data": {"value": 1}}

    async def _fake_process_result(_self, step_name, result, output_config=None):
        return {"_value": result.get("data")}

    from noetl.worker.result_handler import ResultHandler
    monkeypatch.setattr(ResultHandler, "process_result", _fake_process_result)


    monkeypatch.setattr(Worker, "_emit_batch_events", _fake_emit_batch_events)
    monkeypatch.setattr(Worker, "_execute_tool", _fake_execute_tool)

    await worker._execute_command(
        {
            "execution_id": 123,
            "node_name": "hot_loop",
            "action": "task_sequence",
            "context": {
                "tool_config": {"tasks": []},
                "input": {},
                "render_context": {},
                "spec": {},
            },
            "meta": {},
        },
        server_url="http://server",
        command_id="123:hot_loop:1",
    )

    assert [evt["name"] for evt in seen_terminal_batch] == [
        "call.done",
        "step.exit",
        "command.completed",
    ]


def test_case_action_handler_uses_a_single_batched_emit():
    """Regression: the case-action routing path (case rules in next.arcs
    that resolve to a `next` or `retry` action) used to fire four
    sequential `_emit_event` HTTP roundtrips for
    `case.evaluated` + `call.done|call.error` + `step.exit` +
    `command.completed`. At ~50-100 ms per roundtrip that added
    200-400 ms per case-evaluated step.

    They now fan out as a single `_emit_batch_events` call so the four
    events land in one HTTP request and one Postgres transaction via
    the existing /api/events/batch endpoint.

    This test is a code-shape assertion (not a behavior simulation
    against a fake worker) because the case-action path is buried
    inside `_execute_command` and requires significant context setup to
    reach via behavior tests. The existing initial / terminal batch
    paths are covered by the behavior tests above; this one pins the
    refactor's structural invariant: the case-action handler must NOT
    contain four `_emit_event` calls inside its branch.
    """
    import inspect
    import re

    source = inspect.getsource(worker_module)

    # Find the case-action handler. Look for the marker comment that
    # opens the branch.
    branch_start = source.find(
        "if case_action and case_action.get('type') in ['next', 'retry']"
    )
    assert branch_start != -1, "case-action branch marker not found"

    # The branch ends at the next `return` statement at the same
    # indentation level (which is the # Exit - server will handle
    # routing line). Grab everything between for inspection.
    branch_end = source.find(
        "return  # Exit - server will handle routing based on case_action",
        branch_start,
    )
    assert branch_end != -1, "case-action branch close marker not found"
    branch_body = source[branch_start:branch_end]

    # The collapsed batch path: exactly one _emit_batch_events call.
    batch_calls = re.findall(r"await\s+self\._emit_batch_events\(", branch_body)
    assert len(batch_calls) == 1, (
        f"case-action branch should issue exactly one batched emit; "
        f"found {len(batch_calls)}"
    )

    # No individual _emit_event calls inside the branch body. Allow
    # whitespace differences; the assertion is "no `await self._emit_event(`".
    individual_calls = re.findall(r"await\s+self\._emit_event\(", branch_body)
    assert individual_calls == [], (
        f"case-action branch must not issue individual _emit_event calls "
        f"(would cause 4 sequential HTTP roundtrips); "
        f"found {len(individual_calls)}"
    )

    # The batch must contain at least the four event names. Order is
    # preserved by the batch endpoint's executemany insert.
    for required_name in (
        '"case.evaluated"',
        '"step.exit"',
        '"command.completed"',
    ):
        assert required_name in branch_body, (
            f"case-action batch must include {required_name}"
        )
    # call.done OR call.error must be present (one is selected at
    # runtime by tool_error).
    assert ('"call.done"' in branch_body) and (
        '"call.error"' in branch_body
    ), "case-action batch must include both call.done and call.error event templates"
