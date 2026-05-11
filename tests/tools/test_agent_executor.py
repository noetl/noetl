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
    assert result["data"]["ok"] is True
    assert result["data"]["items"][0]["name"] == "Full hydrated activity"
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
    assert result["status"] == "ok"
    assert result["isError"] is False
    assert result["data"]["ok"] is True
    assert result["data"]["activities_total"] == 20
    assert result["data"]["items"] == [{"id": idx} for idx in range(10)]
    assert "activities" not in result["data"]


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
    assert result["status"] == "ok"
    assert result["isError"] is False
    assert result["data"] == {"ok": True, "status_code": 200}
    assert result["_meta"] == {"tool": "search_activities"}


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
