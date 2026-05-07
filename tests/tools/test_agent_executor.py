import sys
import types

import pytest
from jinja2 import Environment

# Avoid import-order circulars in legacy package init path.
import noetl.worker.auth_resolver  # noqa: F401
from noetl.tools.agent import execute_agent_task
from noetl.tools.agent import executor as agent_executor


@pytest.mark.asyncio
async def test_agent_executor_callable_mode_custom_framework():
    module_name = "test_agent_exec_custom_mod"
    module = types.ModuleType(module_name)

    async def run_agent(payload):
        return {"echo": payload}

    module.run_agent = run_agent
    sys.modules[module_name] = module
    try:
        result = await execute_agent_task(
            task_config={
                "framework": "custom",
                "entrypoint": f"{module_name}:run_agent",
                "entrypoint_mode": "callable",
                "payload": {"goal": "{{ workload.goal }}"},
            },
            context={"workload": {"goal": "ship"}},
            jinja_env=Environment(),
            task_with={},
        )
        assert result["status"] == "ok"
        assert result["data"] == {"echo": {"goal": "ship"}}
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_agent_executor_langchain_factory_mode():
    module_name = "test_agent_exec_langchain_mod"
    module = types.ModuleType(module_name)

    class FakeChain:
        def __init__(self, prefix):
            self.prefix = prefix

        def invoke(self, input):
            return {"result": f"{self.prefix}:{input['goal']}"}

    def build_chain(prefix="default"):
        return FakeChain(prefix=prefix)

    module.build_chain = build_chain
    sys.modules[module_name] = module
    try:
        result = await execute_agent_task(
            task_config={
                "framework": "langchain",
                "entrypoint": f"{module_name}:build_chain",
                "entrypoint_mode": "factory",
                "entrypoint_args": {"prefix": "ok"},
                "payload": {"goal": "{{ workload.goal }}"},
            },
            context={"workload": {"goal": "validate"}},
            jinja_env=Environment(),
            task_with={},
        )
        assert result["status"] == "ok"
        assert result["data"] == {"result": "ok:validate"}
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_agent_executor_returns_structured_error_for_bad_entrypoint():
    result = await execute_agent_task(
        task_config={
            "framework": "adk",
            "entrypoint": "missing.module:missing_attr",
            "entrypoint_mode": "factory",
            "payload": {"goal": "test"},
        },
        context={},
        jinja_env=Environment(),
        task_with={},
    )
    assert result["status"] == "error"
    assert result["error"]["kind"] == "agent.execution"


@pytest.mark.asyncio
async def test_agent_executor_adk_keyword_payload_and_async_generator():
    module_name = "test_agent_exec_adk_mod"
    module = types.ModuleType(module_name)

    class FakeRunner:
        async def run_async(self, *, user_id, session_id, new_message):
            yield {"event": "start", "user_id": user_id}
            yield {"event": "done", "session_id": session_id, "message": new_message}

    def build_runner():
        return FakeRunner()

    module.build_runner = build_runner
    sys.modules[module_name] = module
    try:
        result = await execute_agent_task(
            task_config={
                "framework": "adk",
                "entrypoint": f"{module_name}:build_runner",
                "entrypoint_mode": "factory",
                "payload": {
                    "user_id": "u-1",
                    "session_id": "s-1",
                    "new_message": "hello",
                },
            },
            context={},
            jinja_env=Environment(),
            task_with={},
        )
        assert result["status"] == "ok"
        assert result["framework"] == "adk"
        assert result["data"] == [
            {"event": "start", "user_id": "u-1"},
            {"event": "done", "session_id": "s-1", "message": "hello"},
        ]
    finally:
        sys.modules.pop(module_name, None)


def test_auto_troubleshoot_forwards_triage_workload_keys(monkeypatch):
    calls = []

    def fake_execute_playbook_task(task_config, context, jinja_env, task_with):
        calls.append(
            {
                "task_config": dict(task_config),
                "task_with": dict(task_with or {}),
            }
        )
        return {
            "status": "success",
            "execution_id": "diagnosis-exec-1",
        }

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.execute_playbook_task",
        fake_execute_playbook_task,
    )
    monkeypatch.setattr(
        agent_executor,
        "_wait_for_sub_execution_terminal",
        lambda *args, **kwargs: {
            "status": "COMPLETED",
            "execution_id": "diagnosis-exec-1",
            "completed": True,
            "failed": False,
        },
    )
    monkeypatch.setattr(
        agent_executor,
        "_fetch_persisted_diagnosis_from_doc",
        lambda *args, **kwargs: {
            "category": "auth",
            "confidence": 0.91,
            "root_cause": "missing credentials",
            "suggested_action": "configure Workload Identity",
            "source": "vertex-ai",
        },
    )

    diagnosis = agent_executor._dispatch_troubleshoot_diagnosis(
        failed_execution_id="failed-exec-1",
        failed_entrypoint="tests/spike/spike_failing_subflow",
        troubleshoot_path="automation/agents/troubleshoot/diagnose_execution",
        task_config={
            "on_failure": {
                "troubleshoot": True,
                "triage_model": "gemini-2.5-flash",
                "triage_mcp_server": "mcp/vertex-ai",
                "triage_mcp_endpoint": "https://vertex.example/jsonrpc",
                "triage_mcp_tool": "chat_completion",
                "confidence_threshold": 0.2,
                "escalate_to": "none",
                "noetl_url": "http://noetl.noetl.svc.cluster.local:8082",
                "secret_token": "do-not-forward",
            },
        },
        context={},
        jinja_env=Environment(),
    )

    assert diagnosis["source"] == "vertex-ai"
    assert len(calls) == 1
    diagnose_input = calls[0]["task_config"]["input"]
    assert diagnose_input["execution_id"] == "failed-exec-1"
    assert diagnose_input["triage_model"] == "gemini-2.5-flash"
    assert diagnose_input["triage_mcp_server"] == "mcp/vertex-ai"
    assert diagnose_input["triage_mcp_endpoint"] == "https://vertex.example/jsonrpc"
    assert diagnose_input["triage_mcp_tool"] == "chat_completion"
    assert diagnose_input["confidence_threshold"] == 0.2
    assert diagnose_input["escalate_to"] == "none"
    assert "secret_token" not in diagnose_input


def test_auto_troubleshoot_fetch_budget_covers_cloud_event_flush(monkeypatch):
    """Persisted diagnosis arriving after the old 10s window is still attached."""

    fake_clock = {"now": 0.0}
    fetch_times = []

    def fake_execute_playbook_task(task_config, context, jinja_env, task_with):
        return {
            "status": "success",
            "execution_id": "diagnosis-exec-2",
        }

    def fake_fetch(execution_id, *, diagnosis_step_name):
        fetch_times.append(fake_clock["now"])
        if fake_clock["now"] >= 11.0:
            return {
                "category": "infra",
                "confidence": 0.89,
                "root_cause": "cloud managed inference completed after event flush lag",
                "suggested_action": "use the longer diagnosis fetch budget",
                "source": "vertex-ai",
            }
        return None

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.execute_playbook_task",
        fake_execute_playbook_task,
    )
    monkeypatch.setattr(
        agent_executor,
        "_wait_for_sub_execution_terminal",
        lambda *args, **kwargs: {
            "status": "COMPLETED",
            "execution_id": "diagnosis-exec-2",
            "completed": True,
            "failed": False,
        },
    )
    monkeypatch.setattr(
        agent_executor,
        "_fetch_persisted_diagnosis_from_doc",
        fake_fetch,
    )
    monkeypatch.setattr(
        agent_executor.time,
        "monotonic",
        lambda: fake_clock["now"],
    )
    monkeypatch.setattr(
        agent_executor.time,
        "sleep",
        lambda seconds: fake_clock.__setitem__("now", fake_clock["now"] + seconds),
    )

    diagnosis = agent_executor._dispatch_troubleshoot_diagnosis(
        failed_execution_id="failed-exec-2",
        failed_entrypoint="tests/spike/spike_failing_subflow",
        troubleshoot_path="automation/agents/troubleshoot/diagnose_execution",
        task_config={
            "on_failure": {
                "troubleshoot": True,
                "triage_model": "gemini-2.5-flash",
                "triage_mcp_server": "mcp/vertex-ai",
                "escalate_to": "none",
            },
        },
        context={},
        jinja_env=Environment(),
    )

    assert diagnosis["source"] == "vertex-ai"
    assert diagnosis["category"] == "infra"
    assert max(fetch_times) >= 11.0
    assert max(fetch_times) <= agent_executor._DIAGNOSIS_FETCH_TIMEOUT_SECONDS
