import sys
import types

import pytest
from jinja2 import Environment

# Avoid import-order circulars in legacy package init path.
import noetl.worker.auth_resolver  # noqa: F401
from noetl.tools.agent import execute_agent_task


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
