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
            return FakeResponse({"execution_id": "child-exec-1", "status": "COMPLETED"})

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

    assert result["status"] == "COMPLETED"
    assert result["execution_id"] == "child-exec-1"
    assert worker._http_client.post_payload["parent_execution_id"] == "parent-exec-1"
    assert worker._http_client.get_calls == 1
