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
