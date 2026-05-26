import sys
import types
from typing import Any, Dict, Optional

import pytest
from jinja2 import Environment

# Avoid import-order circulars in legacy package init path.
import noetl.worker.auth_resolver  # noqa: F401
from noetl.core.storage.backends import StorageBackend, clear_registered_backends, register_backend
from noetl.tools.agent import execute_agent_task
from noetl.tools.agent import executor as agent_executor


@pytest.fixture(autouse=True)
def _clear_storage_backend_registry():
    clear_registered_backends()
    yield
    clear_registered_backends()


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


def test_agent_direct_disk_reference_resolve_uses_backend_registry():
    calls = []

    class AgentDiskBackend(StorageBackend):
        async def put(
            self,
            key: str,
            data: bytes,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> str:
            return f"disk://{key}"

        async def get(self, key: str) -> bytes:
            calls.append(key)
            return b'{"status": "ok", "source": "registry"}'

        async def delete(self, key: str) -> bool:
            return True

        async def exists(self, key: str) -> bool:
            return True

    register_backend("disk", AgentDiskBackend, replace=True)

    resolved = agent_executor._resolve_disk_result_reference_sync(
        {"kind": "result_ref", "store": "disk", "ref": "noetl://exec-1/step-a"}
    )

    assert resolved == {"status": "ok", "source": "registry"}
    assert calls == ["exec-1_step-a"]


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


def _install_successful_noetl_child(monkeypatch, calls):
    def fake_execute_playbook_task(task_config, context, jinja_env, task_with):
        calls.append(
            {
                "task_config": dict(task_config),
                "task_with": dict(task_with or {}),
            }
        )
        return {
            "status": "success",
            "execution_id": "child-exec-1",
            "duration": 0.01,
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
            "execution_id": "child-exec-1",
            "completed": True,
            "failed": False,
        },
    )
    monkeypatch.setattr(
        agent_executor,
        "_fetch_sub_execution_terminal_result",
        lambda execution_id: {"ok": True, "items": ["result"]},
    )


@pytest.mark.asyncio
async def test_noetl_inline_dry_run_off_does_not_inspect_child(monkeypatch):
    calls = []
    monkeypatch.delenv(agent_executor._INLINE_TRIVIAL_CHILDREN_ENV, raising=False)
    monkeypatch.setattr(
        agent_executor,
        "_load_inline_child_playbook_for_dry_run",
        lambda **kwargs: pytest.fail("dry-run loader should not run when flag is off"),
    )
    _install_successful_noetl_child(monkeypatch, calls)

    result = await execute_agent_task(
        task_config={
            "framework": "noetl",
            "entrypoint": "automation/agents/mcp/weather",
            "payload": {"city": "SFO"},
        },
        context={},
        jinja_env=Environment(),
        task_with={},
    )

    assert result["status"] == "ok"
    assert result["data"] == {"ok": True, "items": ["result"]}
    assert "meta" not in result
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_noetl_inline_dry_run_attaches_decision_without_changing_dispatch(monkeypatch):
    calls = []
    monkeypatch.setenv(agent_executor._INLINE_TRIVIAL_CHILDREN_ENV, "dry_run")
    monkeypatch.setattr(
        agent_executor,
        "_load_inline_child_playbook_for_dry_run",
        lambda **kwargs: {
            "metadata": {"inline_when_safe": True},
            "workflow": [
                {
                    "step": "shape",
                    "tool": {"kind": "python"},
                }
            ],
        },
    )
    _install_successful_noetl_child(monkeypatch, calls)

    result = await execute_agent_task(
        task_config={
            "framework": "noetl",
            "entrypoint": "automation/agents/mcp/weather",
            "payload": {"city": "SFO"},
        },
        context={},
        jinja_env=Environment(),
        task_with={},
    )

    assert result["status"] == "ok"
    assert len(calls) == 1
    assert calls[0]["task_config"]["path"] == "automation/agents/mcp/weather"
    decision = result["meta"]["inline_decision"]
    assert decision["inline"] is True
    assert decision["mode"] == "metadata_opt_in"


@pytest.mark.asyncio
async def test_noetl_inline_enforce_no_dispatch_when_inline_approved(monkeypatch):
    """Round B: enforce + detector approves → inline runner runs, HTTP dispatch skipped."""
    monkeypatch.setenv(agent_executor._INLINE_TRIVIAL_CHILDREN_ENV, "enforce")
    monkeypatch.setattr(
        "noetl.core.workflow.playbook.execute_playbook_task",
        lambda *args, **kwargs: pytest.fail("enforce+inline must not call execute_playbook_task"),
    )
    monkeypatch.setattr(
        agent_executor,
        "_load_inline_child_playbook_for_dry_run",
        lambda **kwargs: {
            "metadata": {"inline_when_safe": True},
            "workflow": [
                {"step": "noop_step", "tool": {"kind": "noop"}},
            ],
        },
    )
    # Stub the inline runner so we don't need the full worker stack.
    from noetl.core.workflow.playbook.inline_runner import InlineResult

    async def fake_run_inline(**kwargs):
        return InlineResult(
            status="ok",
            data={"result": "inlined"},
            execution_id="inline-child-1",
            meta={
                "inline_decision": {"inline": True},
                "inlined_in_parent": "parent-1",
                "inlined_in_command": None,
                "inline_depth": 0,
                "inline_mode": "worker",
            },
        )

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.inline_runner.run_inline",
        fake_run_inline,
    )

    result = await execute_agent_task(
        task_config={
            "framework": "noetl",
            "entrypoint": "automation/agents/mcp/weather",
        },
        context={},
        jinja_env=Environment(),
        task_with={},
    )

    assert result["status"] == "ok"
    assert result["data"] == {"result": "inlined"}
    assert result["execution_id"] == "inline-child-1"
    assert result["framework"] == "noetl"


@pytest.mark.asyncio
async def test_noetl_inline_enforce_dispatches_when_detector_declines(monkeypatch):
    """Round B: enforce + detector declines → HTTP dispatch runs, runner NOT called."""
    calls = []
    monkeypatch.setenv(agent_executor._INLINE_TRIVIAL_CHILDREN_ENV, "enforce")
    monkeypatch.setattr(
        agent_executor,
        "_load_inline_child_playbook_for_dry_run",
        # Return a playbook with an agent step (detector will block it).
        lambda **kwargs: {
            "workflow": [
                {"step": "sub", "tool": {"kind": "agent"}},
            ],
        },
    )

    async def fail_if_runner_called(**kwargs):
        pytest.fail("inline runner must not be called when detector declines")

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.inline_runner.run_inline",
        fail_if_runner_called,
    )
    _install_successful_noetl_child(monkeypatch, calls)

    result = await execute_agent_task(
        task_config={
            "framework": "noetl",
            "entrypoint": "automation/agents/mcp/weather",
            "payload": {"x": 1},
        },
        context={},
        jinja_env=Environment(),
        task_with={},
    )

    assert result["status"] == "ok"
    # HTTP dispatch ran.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_noetl_inline_enforce_runner_error_is_real_failure(monkeypatch):
    """Round B: enforce + detector approves + runner raises → error with INLINE_RUNNER_FAILED."""
    monkeypatch.setenv(agent_executor._INLINE_TRIVIAL_CHILDREN_ENV, "enforce")
    monkeypatch.setattr(
        "noetl.core.workflow.playbook.execute_playbook_task",
        lambda *args, **kwargs: pytest.fail("dispatch must not run when runner is called"),
    )
    monkeypatch.setattr(
        agent_executor,
        "_load_inline_child_playbook_for_dry_run",
        lambda **kwargs: {
            "metadata": {"inline_when_safe": True},
            "workflow": [
                {"step": "noop_step", "tool": {"kind": "noop"}},
            ],
        },
    )

    async def failing_runner(**kwargs):
        raise RuntimeError("simulated runner crash")

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.inline_runner.run_inline",
        failing_runner,
    )

    result = await execute_agent_task(
        task_config={
            "framework": "noetl",
            "entrypoint": "automation/agents/mcp/weather",
        },
        context={},
        jinja_env=Environment(),
        task_with={},
    )

    assert result["status"] == "error"
    assert result["error"]["kind"] == "agent.runtime"
    assert result["error"]["code"] == "INLINE_RUNNER_FAILED"
    assert "simulated runner crash" in result["error"]["message"]


@pytest.mark.asyncio
async def test_noetl_inline_dry_run_does_not_call_runner(monkeypatch):
    """Round B: dry_run + detector approves → runner NOT called, dispatch DOES run."""
    calls = []
    monkeypatch.setenv(agent_executor._INLINE_TRIVIAL_CHILDREN_ENV, "dry_run")
    monkeypatch.setattr(
        agent_executor,
        "_load_inline_child_playbook_for_dry_run",
        lambda **kwargs: {
            "metadata": {"inline_when_safe": True},
            "workflow": [
                {"step": "noop_step", "tool": {"kind": "noop"}},
            ],
        },
    )

    async def fail_if_runner_called(**kwargs):
        pytest.fail("inline runner must not run in dry_run mode")

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.inline_runner.run_inline",
        fail_if_runner_called,
    )
    _install_successful_noetl_child(monkeypatch, calls)

    result = await execute_agent_task(
        task_config={
            "framework": "noetl",
            "entrypoint": "automation/agents/mcp/weather",
        },
        context={},
        jinja_env=Environment(),
        task_with={},
    )

    assert result["status"] == "ok"
    # Dispatch ran.
    assert len(calls) == 1
    # Decision is present.
    assert result["meta"]["inline_decision"]["inline"] is True


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


def _install_fake_clock(monkeypatch):
    fake_clock = {"now": 0.0}
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
    return fake_clock


def _diagnosis_after(fake_clock, threshold_seconds, fetch_times):
    def fake_fetch(execution_id, *, diagnosis_step_name):
        fetch_times.append(fake_clock["now"])
        if fake_clock["now"] >= threshold_seconds:
            return {
                "category": "infra",
                "confidence": 0.89,
                "root_cause": "cloud managed inference completed after event flush lag",
                "suggested_action": "use the adaptive diagnosis fetch backoff",
                "source": "vertex-ai",
            }
        return None

    return fake_fetch


def test_adaptive_diagnosis_fetch_warm_path(monkeypatch):
    fake_clock = _install_fake_clock(monkeypatch)
    fetch_times = []

    diagnosis, meta = agent_executor._fetch_persisted_diagnosis_with_backoff(
        "diagnosis-exec-warm",
        fetch_func=_diagnosis_after(fake_clock, 0.8, fetch_times),
    )

    assert diagnosis["source"] == "vertex-ai"
    assert meta["poll_count"] <= 3
    assert meta["elapsed_seconds"] < 2.0
    assert meta["hit_deadline"] is False


def test_adaptive_diagnosis_fetch_cold_path(monkeypatch):
    fake_clock = _install_fake_clock(monkeypatch)
    fetch_times = []

    diagnosis, meta = agent_executor._fetch_persisted_diagnosis_with_backoff(
        "diagnosis-exec-cold",
        fetch_func=_diagnosis_after(fake_clock, 25.0, fetch_times),
    )

    assert diagnosis["source"] == "vertex-ai"
    assert 10 <= meta["poll_count"] <= 14
    assert 20.0 < meta["elapsed_seconds"] < 30.0
    assert meta["hit_deadline"] is False


def test_adaptive_diagnosis_fetch_missing_hits_deadline(monkeypatch):
    fake_clock = _install_fake_clock(monkeypatch)
    fetch_times = []

    diagnosis, meta = agent_executor._fetch_persisted_diagnosis_with_backoff(
        "diagnosis-exec-missing",
        fetch_func=_diagnosis_after(fake_clock, 999.0, fetch_times),
    )

    assert diagnosis is None
    assert meta["elapsed_seconds"] >= 59.0
    assert meta["deadline_seconds"] == agent_executor._DIAGNOSIS_BACKOFF_DEADLINE
    assert meta["hit_deadline"] is True


def test_auto_troubleshoot_attaches_diagnosis_fetch_telemetry(monkeypatch):
    fake_clock = _install_fake_clock(monkeypatch)
    fetch_times = []

    def fake_execute_playbook_task(task_config, context, jinja_env, task_with):
        return {
            "status": "success",
            "execution_id": "diagnosis-exec-2",
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
            "execution_id": "diagnosis-exec-2",
            "completed": True,
            "failed": False,
        },
    )
    monkeypatch.setattr(
        agent_executor,
        "_fetch_persisted_diagnosis_from_doc",
        _diagnosis_after(fake_clock, 0.8, fetch_times),
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
    fetch_meta = diagnosis["_meta"]["diagnosis_fetch"]
    assert set(fetch_meta) == {
        "poll_count",
        "elapsed_seconds",
        "deadline_seconds",
        "hit_deadline",
    }
    assert fetch_meta["poll_count"] <= 3
    assert fetch_meta["elapsed_seconds"] < 2.0
    assert fetch_meta["deadline_seconds"] == agent_executor._DIAGNOSIS_BACKOFF_DEADLINE
    assert fetch_meta["hit_deadline"] is False


def test_auto_troubleshoot_adaptive_fetch_covers_legacy_11s_flush(monkeypatch):
    """Regression guard for the v2.36.1 static-budget edge case."""

    fake_clock = _install_fake_clock(monkeypatch)
    fetch_times = []

    def fake_execute_playbook_task(task_config, context, jinja_env, task_with):
        return {
            "status": "success",
            "execution_id": "diagnosis-exec-3",
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
            "execution_id": "diagnosis-exec-3",
            "completed": True,
            "failed": False,
        },
    )
    monkeypatch.setattr(
        agent_executor,
        "_fetch_persisted_diagnosis_from_doc",
        _diagnosis_after(fake_clock, 11.0, fetch_times),
    )

    diagnosis = agent_executor._dispatch_troubleshoot_diagnosis(
        failed_execution_id="failed-exec-3",
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
    assert diagnosis["_meta"]["diagnosis_fetch"]["elapsed_seconds"] > 10.0
    assert diagnosis["_meta"]["diagnosis_fetch"]["hit_deadline"] is False


# ----------------------------------------------------------------------
# Sub-execution terminal-result hydration tests.
#
# Background: `/api/executions/{id}/status` compacts state.variables (any
# value over ~_STATUS_VALUE_MAX_BYTES is replaced with a {_truncated,
# _original_size_bytes, _preview} stub). Large MCP envelopes — e.g.
# Amadeus activities returning 200 with many items — were silently
# truncated, so the parent step's Jinja access `envelope.data.ok` and
# `envelope.data.items` saw a stub instead of the real payload, routing
# successful results to the friendly-failure widget. The fix fetches the
# terminal step's `result.context` from /api/executions/{id}/events
# (uncompacted) and uses that as envelope.data.
# ----------------------------------------------------------------------


def _fake_events_response(events, *, status_ok=True):
    """Build a stub requests-like Response object for events endpoint."""
    class _Resp:
        status_code = 200 if status_ok else 500

        def raise_for_status(self):
            if not status_ok:
                raise RuntimeError("simulated 500")

        def json(self):
            return {"events": events, "pagination": {}}

    return _Resp()


def test_fetch_sub_execution_terminal_result_picks_last_terminal_step(monkeypatch):
    """Helper returns the highest-event_id command.completed result.context.

    Multiple terminal-step events are present; the helper must pick the
    one with the largest event_id (the workflow's tail step). Boundary
    nodes (start/end) must be ignored.
    """
    events = [
        # Older step.
        {
            "event_id": 100,
            "event_type": "command.completed",
            "node_name": "amadeus_oauth",
            "result": {"context": {"data": {"ok": True, "token": "xyz"}}},
        },
        # Boundary node — should be skipped even if event_id is highest.
        {
            "event_id": 250,
            "event_type": "step.exit",
            "node_name": "end",
            "result": {"context": {"data": {"ok": True}}},
        },
        # The terminal tail step — largest non-boundary event_id wins.
        {
            "event_id": 200,
            "event_type": "command.completed",
            "node_name": "shape_search_activities",
            "result": {
                "context": {
                    "data": {
                        "ok": True,
                        "items": [{"name": "Statue of Liberty Tour"}],
                        "items_total": 1,
                    },
                    "isError": False,
                }
            },
        },
    ]

    class _FakeRequests:
        def get(self, url, timeout=None):
            assert "/executions/" in url and "/events" in url
            assert "page_size=500" in url
            return _fake_events_response(events)

    monkeypatch.setitem(
        sys.modules,
        "requests",
        types.SimpleNamespace(get=_FakeRequests().get),
    )

    result = agent_executor._fetch_sub_execution_terminal_result("12345")
    assert isinstance(result, dict)
    assert result["data"]["ok"] is True
    assert result["data"]["items"][0]["name"] == "Statue of Liberty Tour"
    assert result["isError"] is False


def test_fetch_sub_execution_terminal_result_resolves_reference_before_context(monkeypatch):
    """Large results use event result.reference before compact context.

    Projection keeps summary fields in result.context for large payloads,
    while the full child output is behind result.reference. The parent
    agent envelope needs the resolved reference so templates can read
    envelope.data.ok and envelope.data.items.
    """
    events = [
        {
            "event_id": 200,
            "event_type": "command.completed",
            "node_name": "shape_search_activities",
            "result": {
                "status": "ok",
                "reference": {
                    "locator": "noetl://execution/123/result/shape_search_activities/abc",
                    "store": "disk",
                },
                "context": {
                    "status": "ok",
                    "data_ok": True,
                    "data_activities_total": 1786,
                },
            },
        },
    ]

    class _FakeRequests:
        def get(self, url, timeout=None):
            return _fake_events_response(events)

    monkeypatch.setitem(
        sys.modules,
        "requests",
        types.SimpleNamespace(get=_FakeRequests().get),
    )
    monkeypatch.setattr(
        agent_executor,
        "_resolve_result_reference_sync",
        lambda reference: {
            "status": "ok",
            "data": {
                "ok": True,
                "items": [{"name": "Full hydrated activity"}],
                "items_total": 1,
            },
            "isError": False,
        },
    )

    result = agent_executor._fetch_sub_execution_terminal_result("12345")
    assert result["ok"] is True
    assert result["items"][0]["name"] == "Full hydrated activity"
    assert "data_ok" not in result


def test_fetch_sub_execution_terminal_result_compacts_large_mcp_collections(monkeypatch):
    events = [
        {
            "event_id": 200,
            "event_type": "command.completed",
            "node_name": "amadeus_search_activities",
            "result": {
                "reference": {
                    "locator": "noetl://execution/123/result/amadeus_search_activities/abc",
                    "store": "disk",
                },
                "context": {"status": "ok", "data_ok": True},
            },
        },
    ]

    class _FakeRequests:
        def get(self, url, timeout=None):
            return _fake_events_response(events)

    monkeypatch.setitem(
        sys.modules,
        "requests",
        types.SimpleNamespace(get=_FakeRequests().get),
    )
    monkeypatch.setattr(
        agent_executor,
        "_resolve_result_reference_sync",
        lambda reference: {
            "status": "ok",
            "isError": False,
            "_meta": {"tool": "search_activities"},
            "data": {
                "ok": True,
                "status_code": 200,
                "activities": [{"id": idx} for idx in range(20)],
            },
        },
    )

    result = agent_executor._fetch_sub_execution_terminal_result("12345")
    assert result["isError"] is False
    assert result["ok"] is True
    assert result["activities_total"] == 20
    assert result["items"] == [{"id": idx} for idx in range(10)]
    assert "activities" not in result


def test_fetch_sub_execution_terminal_result_expands_flattened_context(monkeypatch):
    events = [
        {
            "event_id": 200,
            "event_type": "command.completed",
            "node_name": "amadeus_search_activities",
            "result": {
                "reference": {
                    "locator": "noetl://execution/123/result/amadeus_search_activities/abc",
                    "store": "disk",
                },
                "context": {
                    "status": "ok",
                    "isError": False,
                    "data_ok": True,
                    "data_status_code": 200,
                    "_meta_tool": "search_activities",
                },
            },
        },
    ]

    class _FakeRequests:
        def get(self, url, timeout=None):
            return _fake_events_response(events)

    monkeypatch.setitem(
        sys.modules,
        "requests",
        types.SimpleNamespace(get=_FakeRequests().get),
    )
    monkeypatch.setattr(agent_executor, "_resolve_result_reference_sync", lambda reference: None)

    result = agent_executor._fetch_sub_execution_terminal_result("12345")
    assert result["isError"] is False
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["_meta"] == {"tool": "search_activities"}


def test_fetch_sub_execution_terminal_result_prefers_control_data(monkeypatch):
    events = [
        {
            "event_id": 200,
            "event_type": "command.completed",
            "node_name": "amadeus_search_activities",
            "result": {
                "context": {
                    "status": "ok",
                    "data_ok": True,
                    "control_data": {
                        "ok": True,
                        "items": [{"name": "bounded activity"}],
                        "activities_total": 1799,
                    },
                },
            },
        },
    ]

    class _FakeRequests:
        def get(self, url, timeout=None):
            return _fake_events_response(events)

    monkeypatch.setitem(
        sys.modules,
        "requests",
        types.SimpleNamespace(get=_FakeRequests().get),
    )

    result = agent_executor._fetch_sub_execution_terminal_result("12345")
    assert result == {
        "ok": True,
        "items": [{"name": "bounded activity"}],
        "activities_total": 1799,
    }


def test_fetch_sub_execution_terminal_result_returns_none_when_no_terminal(monkeypatch):
    """No qualifying terminal event → None → caller falls back to status doc."""

    events = [
        # Only boundary events — no real terminal step.
        {"event_id": 10, "event_type": "command.completed", "node_name": "start"},
        {"event_id": 20, "event_type": "step.exit", "node_name": "end"},
        # Wrong event type.
        {"event_id": 30, "event_type": "command.issued", "node_name": "shape_step"},
    ]

    class _FakeRequests:
        def get(self, url, timeout=None):
            return _fake_events_response(events)

    monkeypatch.setitem(
        sys.modules,
        "requests",
        types.SimpleNamespace(get=_FakeRequests().get),
    )

    result = agent_executor._fetch_sub_execution_terminal_result("12345")
    assert result is None


def test_fetch_sub_execution_terminal_result_swallows_request_failure(monkeypatch):
    """Network failure → None, never raises. Best-effort hydration."""

    class _FakeRequests:
        def get(self, url, timeout=None):
            raise ConnectionError("simulated network error")

    monkeypatch.setitem(
        sys.modules,
        "requests",
        types.SimpleNamespace(get=_FakeRequests().get),
    )

    result = agent_executor._fetch_sub_execution_terminal_result("12345")
    assert result is None


# ---------------------------------------------------------------------------
# Catalog-fallback for the dry-run loader. When the on-disk lookup falls back
# to the placeholder stub (real-world case for cross-repo entrypoints like
# automation/agents/mcp/firestore where the file lives in noetl/ops, not in
# the noetl image), the loader must fetch the actual playbook from the
# noetl-server catalog so the detector can inspect the real workflow.
#
# Without this, the live GKE dry-run experiment with PR #608 + PR #609 saw
# every mcp/firestore decision come back inline=false with
# "tool:block:step[0].missing_tool_kind" + "step[1].missing_tool_kind" — even
# though the real firestore playbook has exactly one step with tool.kind=python.
# The detector was inspecting the broker-resolution placeholder, not the real
# child.
# ---------------------------------------------------------------------------


def test_placeholder_detector_matches_broker_resolution_stub():
    """The placeholder shape comes from loader.create_placeholder_playbook —
    exactly start + end with no tool. Pin the detector against that exact
    shape so a future change to the placeholder catches a test failure
    here before silently breaking the catalog-fallback trigger."""
    placeholder = {
        "apiVersion": "noetl.io/v1",
        "kind": "Playbook",
        "name": "firestore",
        "path": "automation/agents/mcp/firestore",
        "workload": {},
        "workflow": [
            {
                "step": "start",
                "desc": "Placeholder for path-referenced playbook",
                "next": [{"step": "end"}],
            },
            {"step": "end", "desc": "End"},
        ],
    }
    assert agent_executor._looks_like_placeholder_playbook(placeholder) is True


def test_placeholder_detector_does_not_match_real_one_step_playbook():
    real_playbook = {
        "apiVersion": "noetl.io/v2",
        "kind": "Playbook",
        "workload": {},
        "workflow": [
            {
                "step": "firestore_dispatch",
                "tool": {"kind": "python", "code": "..."},
            }
        ],
    }
    assert agent_executor._looks_like_placeholder_playbook(real_playbook) is False


def test_placeholder_detector_does_not_match_three_step_playbook():
    """Multi-step playbooks (start + real + end, or longer) are not stubs."""
    multi_step = {
        "workflow": [
            {"step": "start", "next": [{"step": "fetch"}]},
            {"step": "fetch", "tool": {"kind": "python"}},
            {"step": "end"},
        ]
    }
    assert agent_executor._looks_like_placeholder_playbook(multi_step) is False


def test_placeholder_detector_rejects_two_steps_with_tool_definition():
    """A two-step playbook with tool defined is not the placeholder. The
    placeholder is defined by both having exactly the (start, end) names
    AND lacking tool definitions."""
    two_step_with_tools = {
        "workflow": [
            {"step": "start", "tool": {"kind": "python"}},
            {"step": "end"},
        ]
    }
    assert agent_executor._looks_like_placeholder_playbook(two_step_with_tools) is False


def test_placeholder_detector_handles_non_dict_input():
    """Defensive: callers may pass empty dicts, None, or unexpected shapes.
    The detector should return False (not raise)."""
    assert agent_executor._looks_like_placeholder_playbook({}) is False
    assert agent_executor._looks_like_placeholder_playbook({"workflow": []}) is False
    assert agent_executor._looks_like_placeholder_playbook({"workflow": "not-a-list"}) is False


@pytest.fixture(autouse=True)
def _reset_inline_catalog_cache():
    """Per-test isolation for the catalog cache. The cache is process-
    local and persists across calls during a worker's lifetime, but
    test-to-test cross-contamination would cause false positives when
    later tests expect the loader to consult the mocked requests
    module."""
    agent_executor._clear_inline_child_catalog_cache()
    yield
    agent_executor._clear_inline_child_catalog_cache()


def test_load_inline_child_from_catalog_returns_payload_dict(monkeypatch):
    """Successful catalog fetch with `payload` dict shape."""
    captured: Dict[str, Any] = {}

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "path": "automation/agents/mcp/firestore",
                "version": 7,
                "payload": {
                    "apiVersion": "noetl.io/v2",
                    "kind": "Playbook",
                    "workflow": [
                        {"step": "firestore_dispatch", "tool": {"kind": "python"}}
                    ],
                },
            }

    class _FakeRequestsModule:
        @staticmethod
        def post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return _FakeResponse()

    monkeypatch.setitem(sys.modules, "requests", _FakeRequestsModule)
    monkeypatch.setenv("NOETL_SERVER_URL", "http://noetl.test:8082")

    result = agent_executor._load_inline_child_playbook_from_catalog(
        "automation/agents/mcp/firestore"
    )

    assert result is not None
    assert result["workflow"][0]["step"] == "firestore_dispatch"
    assert result["workflow"][0]["tool"]["kind"] == "python"
    # Correct URL (server_url + /api + /catalog/resource).
    assert captured["url"] == "http://noetl.test:8082/api/catalog/resource"
    # Version is omitted from the request body. The server treats a
    # missing version as "give me the highest version row". An earlier
    # shape sent ``{"version": "latest"}`` as a literal string and the
    # endpoint returned 404 — silently breaking detector decisions on
    # any deployment whose child playbook lived in the server-side
    # catalog rather than the worker's local filesystem.
    assert captured["json"] == {"path": "automation/agents/mcp/firestore"}


def test_load_inline_child_from_catalog_omits_version_field(monkeypatch):
    """Regression test for the version="latest" → 404 bug. The catalog
    HTTP request body must NOT carry a ``version`` field; the server
    treats a missing field as "give me the highest version row" for
    the path. An earlier shape sent the literal string ``"latest"`` and
    the server returned 404 ``Catalog entry not found``, silently
    forcing every detector decision on GKE to ``inline=False`` with
    placeholder-cascade ``missing_tool_kind`` reasons."""
    captured: Dict[str, Any] = {}

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "path": "automation/agents/mcp/firestore",
                "version": 4,
                "payload": {"workflow": [{"step": "s", "tool": {"kind": "python"}}]},
            }

    class _FakeRequestsModule:
        @staticmethod
        def post(url, json=None, timeout=None):
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setitem(sys.modules, "requests", _FakeRequestsModule)
    monkeypatch.setenv("NOETL_SERVER_URL", "http://noetl.test:8082")

    agent_executor._load_inline_child_playbook_from_catalog(
        "automation/agents/mcp/firestore"
    )

    body = captured["json"]
    assert "version" not in body, (
        f"request body must omit `version`; got {body!r}. "
        "Sending version=\"latest\" returns 404 from /api/catalog/resource."
    )
    assert body == {"path": "automation/agents/mcp/firestore"}


def test_load_inline_child_from_catalog_parses_yaml_string_content(monkeypatch):
    """Catalog entry may carry the playbook as a YAML string under
    `content` instead of a parsed dict. The loader must parse it."""
    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "content": (
                    "apiVersion: noetl.io/v2\n"
                    "kind: Playbook\n"
                    "workflow:\n"
                    "  - step: firestore_dispatch\n"
                    "    tool:\n"
                    "      kind: python\n"
                ),
            }

    class _FakeRequestsModule:
        @staticmethod
        def post(url, json=None, timeout=None):
            return _FakeResponse()

    monkeypatch.setitem(sys.modules, "requests", _FakeRequestsModule)
    monkeypatch.setenv("NOETL_SERVER_URL", "http://noetl.test:8082")

    result = agent_executor._load_inline_child_playbook_from_catalog(
        "automation/agents/mcp/firestore"
    )

    assert result is not None
    assert result["workflow"][0]["step"] == "firestore_dispatch"
    assert result["workflow"][0]["tool"]["kind"] == "python"


def test_load_inline_child_from_catalog_returns_none_on_404(monkeypatch):
    """A 404 from the catalog endpoint is a clean "not found" signal,
    not an error to bubble up. Caller falls back to leaving the
    placeholder in place."""
    class _FakeResponse:
        status_code = 404

        def raise_for_status(self):
            raise RuntimeError("must not be called on 404 short-circuit")

        def json(self):
            raise RuntimeError("must not be called on 404 short-circuit")

    class _FakeRequestsModule:
        @staticmethod
        def post(url, json=None, timeout=None):
            return _FakeResponse()

    monkeypatch.setitem(sys.modules, "requests", _FakeRequestsModule)
    monkeypatch.setenv("NOETL_SERVER_URL", "http://noetl.test:8082")

    result = agent_executor._load_inline_child_playbook_from_catalog(
        "missing/playbook"
    )

    assert result is None


def test_load_inline_child_from_catalog_returns_none_on_network_failure(monkeypatch):
    """Network failure / connection error → None, never raises. The
    detector then keeps the placeholder and emits a clear reason chain
    rather than crashing the agent path."""

    class _FakeRequestsModule:
        @staticmethod
        def post(url, json=None, timeout=None):
            raise ConnectionError("simulated network failure")

    monkeypatch.setitem(sys.modules, "requests", _FakeRequestsModule)
    monkeypatch.setenv("NOETL_SERVER_URL", "http://noetl.test:8082")

    result = agent_executor._load_inline_child_playbook_from_catalog(
        "automation/agents/mcp/firestore"
    )

    assert result is None


# ---------------------------------------------------------------------------
# Catalog lookup cache. PR #610 added the HTTP fallback so the detector sees
# the real child playbook for cross-repo entrypoints; uncached, that fallback
# hits noetl-server on every `tool: agent` step. Measured impact on the live
# GKE cluster: per-turn duration moved from 10s (placeholder-only path) to
# 39s (uncached catalog path) for an itinerary-planner turn that fires ~8
# agent calls. This cache keeps the dry-run hot path near zero overhead.
# ---------------------------------------------------------------------------


class _CountingFakeRequests:
    """Records every POST so tests can assert the cache fired (1 call,
    not N) or was bypassed (>1 call) without inspecting cache internals."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def post(self, url, json=None, timeout=None):
        self.calls += 1
        if not self._responses:
            raise RuntimeError("no more fake responses")
        return self._responses.pop(0)


class _FakeOkResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_catalog_cache_hits_on_second_call_for_same_entrypoint(monkeypatch):
    payload = {
        "apiVersion": "noetl.io/v2",
        "kind": "Playbook",
        "workflow": [{"step": "do_thing", "tool": {"kind": "python"}}],
    }
    fake = _CountingFakeRequests([_FakeOkResponse({"payload": payload})])
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setenv("NOETL_SERVER_URL", "http://noetl.test:8082")
    # Default TTL applies; the test doesn't need to wait.

    first = agent_executor._load_inline_child_playbook_from_catalog(
        "automation/agents/mcp/firestore"
    )
    second = agent_executor._load_inline_child_playbook_from_catalog(
        "automation/agents/mcp/firestore"
    )

    assert first is not None and second is not None
    assert first == second
    # The cache must have served the second call without a second HTTP
    # roundtrip. The fake only had one response queued.
    assert fake.calls == 1


def test_catalog_cache_caches_none_results_too(monkeypatch):
    """A 404 / network failure / missing entry must be cached so a
    catalog miss does not retry on every subsequent agent step in
    the same turn — the worst case of the uncached path."""
    class _Fake404Response:
        status_code = 404

        def raise_for_status(self):
            raise RuntimeError("must not be called on 404 short-circuit")

        def json(self):
            raise RuntimeError("must not be called on 404 short-circuit")

    fake = _CountingFakeRequests([_Fake404Response()])
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setenv("NOETL_SERVER_URL", "http://noetl.test:8082")

    first = agent_executor._load_inline_child_playbook_from_catalog("missing/playbook")
    second = agent_executor._load_inline_child_playbook_from_catalog("missing/playbook")

    assert first is None
    assert second is None
    assert fake.calls == 1


def test_catalog_cache_different_entrypoints_do_not_collide(monkeypatch):
    payload_a = {"workflow": [{"step": "a", "tool": {"kind": "python"}}]}
    payload_b = {"workflow": [{"step": "b", "tool": {"kind": "python"}}]}
    fake = _CountingFakeRequests([
        _FakeOkResponse({"payload": payload_a}),
        _FakeOkResponse({"payload": payload_b}),
    ])
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setenv("NOETL_SERVER_URL", "http://noetl.test:8082")

    got_a = agent_executor._load_inline_child_playbook_from_catalog("path/a")
    got_b = agent_executor._load_inline_child_playbook_from_catalog("path/b")
    got_a_again = agent_executor._load_inline_child_playbook_from_catalog("path/a")

    assert got_a == payload_a
    assert got_b == payload_b
    # Third call to path/a is a cache hit; total HTTP calls = 2.
    assert got_a_again == payload_a
    assert fake.calls == 2


def test_catalog_cache_zero_ttl_disables_cache(monkeypatch):
    """Setting TTL <= 0 forces every call through HTTP. This matches
    the test contract elsewhere in the file that monkeypatches
    `requests` and expects the loader to actually invoke it."""
    payload = {"workflow": [{"step": "do_thing", "tool": {"kind": "python"}}]}
    fake = _CountingFakeRequests([
        _FakeOkResponse({"payload": payload}),
        _FakeOkResponse({"payload": payload}),
    ])
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setenv("NOETL_SERVER_URL", "http://noetl.test:8082")
    monkeypatch.setenv(
        agent_executor._INLINE_CATALOG_CACHE_TTL_ENV, "0"
    )

    agent_executor._load_inline_child_playbook_from_catalog("automation/agents/mcp/foo")
    agent_executor._load_inline_child_playbook_from_catalog("automation/agents/mcp/foo")

    assert fake.calls == 2


def test_catalog_cache_expires_after_ttl(monkeypatch):
    """After the TTL elapses the loader re-fetches. Simulate elapsed
    time by monkeypatching time.time() rather than actually sleeping."""
    payload_v1 = {"workflow": [{"step": "v1", "tool": {"kind": "python"}}]}
    payload_v2 = {"workflow": [{"step": "v2", "tool": {"kind": "python"}}]}
    fake = _CountingFakeRequests([
        _FakeOkResponse({"payload": payload_v1}),
        _FakeOkResponse({"payload": payload_v2}),
    ])
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setenv("NOETL_SERVER_URL", "http://noetl.test:8082")
    # Short TTL so the test is fast and obvious.
    monkeypatch.setenv(
        agent_executor._INLINE_CATALOG_CACHE_TTL_ENV, "10"
    )

    # Pin the time the loader sees so we control TTL boundary
    # behavior without sleeping.
    fake_time = [1000.0]

    def _fake_time_time():
        return fake_time[0]

    monkeypatch.setattr(agent_executor.time, "time", _fake_time_time)

    first = agent_executor._load_inline_child_playbook_from_catalog("path/cached")
    # Advance past the TTL.
    fake_time[0] += 15.0
    second = agent_executor._load_inline_child_playbook_from_catalog("path/cached")

    assert first == payload_v1
    assert second == payload_v2
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_noetl_inline_enforce_depth_limit_falls_back_to_dispatch(monkeypatch):
    """Enforce: detector blocks at depth DEFAULT_MAX_DEPTH+1 → dispatch runs instead."""
    from noetl.core.workflow.playbook.inline_execution import DEFAULT_MAX_DEPTH

    dispatch_calls = []
    monkeypatch.setenv(agent_executor._INLINE_TRIVIAL_CHILDREN_ENV, "enforce")
    # Simulate a context already at max depth.
    ctx = {"meta": {"inline_depth": DEFAULT_MAX_DEPTH + 1}}
    monkeypatch.setattr(
        agent_executor,
        "_load_inline_child_playbook_for_dry_run",
        lambda **kwargs: {
            "metadata": {"inline_when_safe": True},
            "workflow": [{"step": "noop_step", "tool": {"kind": "noop"}}],
        },
    )

    async def fail_if_runner_called(**kwargs):
        pytest.fail("runner must not be called when depth exceeds limit")

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.inline_runner.run_inline",
        fail_if_runner_called,
    )
    _install_successful_noetl_child(monkeypatch, dispatch_calls)

    result = await execute_agent_task(
        task_config={
            "framework": "noetl",
            "entrypoint": "automation/agents/mcp/weather",
        },
        context=ctx,
        jinja_env=Environment(),
        task_with={},
    )

    # Detector blocked inline (depth too deep) → dispatch ran.
    assert result["status"] == "ok"
    assert len(dispatch_calls) == 1
