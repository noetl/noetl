import pytest

import noetl.worker.v2_worker_nats as worker_module
from noetl.worker.v2_worker_nats import V2Worker


@pytest.mark.asyncio
async def test_playbook_tool_with_return_step_uses_waiting_executor(monkeypatch):
    worker = V2Worker(worker_id="test-worker")

    captured = {}

    async def fake_execute_playbook(config, args):
        captured["config"] = config
        captured["args"] = args
        return {"completed": True, "failed": False}

    def fail_plugin_executor(*_args, **_kwargs):
        raise AssertionError("execute_playbook_task should not be used when return_step is set")

    monkeypatch.setattr(worker, "_execute_playbook", fake_execute_playbook)
    monkeypatch.setattr(worker_module, "execute_playbook_task", fail_plugin_executor)

    result = await worker._execute_tool(
        tool_kind="playbook",
        config={
            "path": "tests/fixtures/playbooks/example_child",
            "return_step": "end",
            "args": {"batch_number": 3},
        },
        args={},
        step="launch_child",
        render_context={"execution_id": "exec-1"},
    )

    assert result["completed"] is True
    assert captured["config"]["return_step"] == "end"
    assert captured["args"] == {"batch_number": 3}


@pytest.mark.asyncio
async def test_playbook_tool_passes_merged_args_to_plugin_executor(monkeypatch):
    worker = V2Worker(worker_id="test-worker")

    captured = {}

    def fake_execute_playbook_task(task_config, context, jinja_env, task_with):
        captured["task_config"] = task_config
        captured["context"] = context
        captured["task_with"] = task_with
        return {"status": "success", "data": {"status": "started"}}

    monkeypatch.setattr(worker_module, "execute_playbook_task", fake_execute_playbook_task)

    result = await worker._execute_tool(
        tool_kind="playbook",
        config={
            "path": "tests/fixtures/playbooks/example_child",
            "args": {"batch_number": 5},
        },
        args={"offset": 400},
        step="launch_child",
        render_context={"execution_id": "exec-2"},
    )

    assert result["status"] == "success"
    assert captured["task_with"] == {"batch_number": 5, "offset": 400}


@pytest.mark.asyncio
async def test_execute_playbook_return_step_detects_terminal_status_field(monkeypatch):
    worker = V2Worker(worker_id="test-worker")
    worker._current_execution_id = "parent-exec-1"

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class FakeHttpClient:
        def __init__(self):
            self.post_payload = None
            self.get_calls = 0

        async def post(self, _url, json=None, timeout=None):
            self.post_payload = json
            return FakeResponse({"execution_id": "child-exec-1"})

        async def get(self, _url, timeout=None):
            self.get_calls += 1
            return FakeResponse(
                {
                    "execution_id": "child-exec-1",
                    "current_step": "end",
                    "completed": True,
                    "failed": False,
                }
            )

    async def fast_sleep(_seconds):
        return None

    worker._http_client = FakeHttpClient()
    monkeypatch.setattr(worker_module.asyncio, "sleep", fast_sleep)

    result = await worker._execute_playbook(
        {
            "path": "tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_chunk_worker",
            "return_step": "end",
            "timeout": 2,
        },
        {"batch_number": 1},
    )

    assert result["completed"] is True
    assert result["failed"] is False
    assert result["execution_id"] == "child-exec-1"
    assert worker._http_client.post_payload["parent_execution_id"] == "parent-exec-1"
    assert worker._http_client.get_calls == 1


@pytest.mark.asyncio
async def test_execute_playbook_waits_for_status_endpoint_not_transient_execution_status(monkeypatch):
    worker = V2Worker(worker_id="test-worker")
    worker._current_execution_id = "parent-exec-2"

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class FakeHttpClient:
        def __init__(self):
            self.status_polls = 0
            self.execution_polls = 0

        async def post(self, _url, json=None, timeout=None):
            return FakeResponse({"execution_id": "child-exec-2"})

        async def get(self, url, timeout=None):
            if url.endswith("/status"):
                self.status_polls += 1
                if self.status_polls == 1:
                    return FakeResponse(
                        {
                            "execution_id": "child-exec-2",
                            "current_step": "process_batch_http",
                            "completed": False,
                            "failed": False,
                        }
                    )
                return FakeResponse(
                    {
                        "execution_id": "child-exec-2",
                        "current_step": "end",
                        "completed": True,
                        "failed": False,
                    }
                )

            # This payload mimics transient non-terminal COMPLETED status from /executions/{id}.
            self.execution_polls += 1
            return FakeResponse({"execution_id": "child-exec-2", "status": "COMPLETED"})

    async def fast_sleep(_seconds):
        return None

    worker._http_client = FakeHttpClient()
    monkeypatch.setattr(worker_module.asyncio, "sleep", fast_sleep)

    result = await worker._execute_playbook(
        {
            "path": "tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_chunk_worker",
            "return_step": "end",
            "timeout": 6,
        },
        {"batch_number": 2},
    )

    assert result["completed"] is True
    assert result["failed"] is False
    assert worker._http_client.status_polls == 2
    assert worker._http_client.execution_polls == 0


@pytest.mark.asyncio
async def test_execute_command_error_events_use_externalized_response(monkeypatch):
    worker = V2Worker(worker_id="test-worker")
    emitted = []

    async def fake_execute_tool(*_args, **_kwargs):
        # Simulate large failed task_sequence output (contains bulky payload).
        return {
            "status": "failed",
            "failed_task": "fetch_detail",
            "error": {"kind": "tool_error", "message": "boom"},
            "_prev": {"blob": "x" * 200_000},
            "results": {"build_large_request": {"request_blob": "y" * 200_000}},
        }

    class FakeResultHandler:
        def __init__(self, execution_id):
            self.execution_id = execution_id

        async def process_result(self, step_name, result, output_config):
            return {
                "_ref": {
                    "kind": "result_ref",
                    "ref": f"noetl://execution/{self.execution_id}/result/{step_name}/abc123",
                    "store": "kv",
                    "scope": "execution",
                    "meta": {"bytes": 1234},
                },
                "_size_bytes": 1234,
                "_store": "kv",
            }

    async def fake_emit_event(_server_url, _execution_id, _step, event_name, payload, **_kwargs):
        emitted.append((event_name, payload))

    monkeypatch.setattr(worker, "_execute_tool", fake_execute_tool)
    monkeypatch.setattr(worker, "_emit_event", fake_emit_event)
    monkeypatch.setattr(worker_module, "ResultHandler", FakeResultHandler)
    monkeypatch.setattr(worker_module, "is_result_ref", lambda value: isinstance(value, dict) and "_ref" in value)

    command = {
        "execution_id": "exec-1",
        "step": "run_direct_stress:task_sequence",
        "tool_kind": "task_sequence",
        "context": {
            "tool_config": {},
            "args": {},
            "render_context": {},
        },
    }

    await worker._execute_command(command, server_url="http://noetl.test", command_id="cmd-1")

    call_error = next(payload for name, payload in emitted if name == "call.error")
    step_exit = next(payload for name, payload in emitted if name == "step.exit")
    command_failed = next(payload for name, payload in emitted if name == "command.failed")

    # Error events should carry the compact externalized response, not raw large payload.
    assert "_ref" in call_error["response"]
    assert "_ref" in step_exit["result"]
    assert "_ref" in command_failed["result"]


@pytest.mark.asyncio
async def test_wait_for_postgres_capacity_retries_until_headroom(monkeypatch):
    worker = V2Worker(worker_id="test-worker")
    worker._running = True
    worker._throttle_poll_interval = 0.01

    states = [True, True, False]

    def fake_is_saturated():
        return states.pop(0) if states else False

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(worker, "_is_postgres_pool_saturated", fake_is_saturated)
    monkeypatch.setattr(worker_module.asyncio, "sleep", fake_sleep)

    await worker._wait_for_postgres_capacity(step="store_rows", command_id="cmd-1")

    assert len(sleeps) == 2


@pytest.mark.asyncio
async def test_handle_command_notification_applies_db_semaphore_for_postgres(monkeypatch):
    worker = V2Worker(worker_id="test-worker")
    worker._running = True

    calls = {"acquire": 0, "release": 0, "wait_capacity": 0, "execute": 0}

    class DummySemaphore:
        async def acquire(self):
            calls["acquire"] += 1

        def release(self):
            calls["release"] += 1

    async def fake_claim(_server_url, _event_id):
        return {
            "execution_id": 1,
            "node_id": "store_rows",
            "node_name": "store_rows",
            "action": "postgres",
            "context": {},
            "meta": {},
        }

    async def fake_wait(*_args, **_kwargs):
        calls["wait_capacity"] += 1

    async def fake_execute(*_args, **_kwargs):
        calls["execute"] += 1

    worker._db_command_semaphore = DummySemaphore()
    monkeypatch.setattr(worker, "_claim_and_fetch_command", fake_claim)
    monkeypatch.setattr(worker, "_wait_for_postgres_capacity", fake_wait)
    monkeypatch.setattr(worker, "_execute_command", fake_execute)

    await worker._handle_command_notification(
        {
            "execution_id": 1,
            "event_id": 10,
            "command_id": "1:store_rows:10",
            "step": "store_rows",
            "server_url": "http://noetl.test",
        }
    )

    assert calls["acquire"] == 1
    assert calls["wait_capacity"] == 1
    assert calls["execute"] == 1
    assert calls["release"] == 1


@pytest.mark.asyncio
async def test_handle_command_notification_skips_db_semaphore_for_non_db_tool(monkeypatch):
    worker = V2Worker(worker_id="test-worker")
    worker._running = True

    calls = {"acquire": 0, "release": 0, "execute": 0}

    class DummySemaphore:
        async def acquire(self):
            calls["acquire"] += 1

        def release(self):
            calls["release"] += 1

    async def fake_claim(_server_url, _event_id):
        return {
            "execution_id": 1,
            "node_id": "process_batch_http",
            "node_name": "process_batch_http",
            "action": "http",
            "context": {},
            "meta": {},
        }

    async def fake_execute(*_args, **_kwargs):
        calls["execute"] += 1

    worker._db_command_semaphore = DummySemaphore()
    monkeypatch.setattr(worker, "_claim_and_fetch_command", fake_claim)
    monkeypatch.setattr(worker, "_execute_command", fake_execute)

    await worker._handle_command_notification(
        {
            "execution_id": 1,
            "event_id": 11,
            "command_id": "1:process_batch_http:11",
            "step": "process_batch_http",
            "server_url": "http://noetl.test",
        }
    )

    assert calls["execute"] == 1
    assert calls["acquire"] == 0
    assert calls["release"] == 0
