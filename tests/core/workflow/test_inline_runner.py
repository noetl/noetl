"""Tests for the Round B inline runner.

Covers:
- Single-step python child: terminal envelope matches dispatched fixture.
- Single-step mcp child: same as above.
- Parent cancellation mid-child: execution.cancelled emitted, error envelope.
- Child step failure: terminal envelope status error.
- Recursion depth = 3 then 4: depth 3 runs; depth 4 is refused.
- noetl.command projection rows exist (emitted) for inline child.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jinja2 import Environment

from noetl.core.workflow.playbook.inline_execution import InlineDecision
from noetl.core.workflow.playbook.inline_runner import (
    DEFAULT_MAX_DEPTH,
    InlineResult,
    _allocate_child_execution_id,
    run_inline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision(*, inline: bool = True, depth: int = 0) -> InlineDecision:
    return InlineDecision(
        inline=inline,
        reasons=["framework:ok:noetl", "allow_list:ok:path_matched"],
        depth=depth,
        mode="allow_list",
    )


def _noop_playbook() -> Dict[str, Any]:
    return {
        "metadata": {"name": "test/noop"},
        "workflow": [
            {"step": "noop_step", "tool": {"kind": "noop"}},
        ],
    }


def _python_playbook() -> Dict[str, Any]:
    return {
        "metadata": {"name": "test/python_child"},
        "workflow": [
            {"step": "run_python", "tool": {"kind": "python", "code": "result = {'x': 1}"}},
        ],
    }


def _mcp_playbook() -> Dict[str, Any]:
    return {
        "metadata": {"name": "test/mcp_child"},
        "workflow": [
            {"step": "call_mcp", "tool": {"kind": "mcp", "endpoint": "http://mcp/jsonrpc"}},
        ],
    }


def _cancellation_probe_returning(value: bool):
    """Return a callable that always returns `value`."""
    def probe(execution_id: str) -> bool:
        return value
    return probe


def _make_emitter() -> tuple[List[Dict], Any]:
    """Return (collected_events, emitter_callable)."""
    collected: List[Dict] = []

    def emitter(execution_id: str, events: List[Dict]) -> bool:
        for ev in events:
            collected.append({"execution_id": execution_id, **ev})
        return True

    return collected, emitter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inline_runner_noop_step_ok():
    """Single noop step produces ok envelope with child execution_id."""
    events, emitter = _make_emitter()

    result = await run_inline(
        parent_execution_id="parent-1",
        parent_command_id="cmd-1",
        parent_step="agent_step",
        child_playbook=_noop_playbook(),
        child_input={"x": 1},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
    )

    assert result.status == "ok"
    assert result.execution_id is not None
    assert result.error is None
    # meta carries inline_decision and inlined_* keys
    assert "inline_decision" in result.meta
    assert result.meta["inline_mode"] == "worker"
    assert result.meta["inlined_in_parent"] == "parent-1"
    assert result.meta["inline_depth"] == 0

    # Events must have been emitted.
    event_names = [e["name"] for e in events]
    assert "playbook.initialized" in event_names
    assert "workflow.initialized" in event_names
    assert "command.started" in event_names
    assert "step.enter" in event_names
    assert "call.done" in event_names
    assert "step.exit" in event_names
    assert "command.completed" in event_names
    assert "workflow.completed" in event_names
    assert "playbook.completed" in event_names


@pytest.mark.asyncio
async def test_inline_runner_python_step_ok(monkeypatch):
    """Single python step: tool is called, result flows through scrub."""
    events, emitter = _make_emitter()

    async def fake_python_task(task_config, context, jinja_env, args=None, **kwargs):
        return {"status": "ok", "data": {"computed": 42}}

    monkeypatch.setattr(
        "noetl.tools.python.execute_python_task_async",
        fake_python_task,
    )
    # Stub scrub so we don't need the full ResultHandler stack.
    async def fake_scrub(**kwargs):
        return kwargs["result"]

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.inline_runner._scrub_result",
        fake_scrub,
    )

    result = await run_inline(
        parent_execution_id="parent-py",
        parent_command_id="cmd-py",
        parent_step="agent_step",
        child_playbook=_python_playbook(),
        child_input={"input": "hello"},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
    )

    assert result.status == "ok"
    assert result.data == {"status": "ok", "data": {"computed": 42}}
    event_names = [e["name"] for e in events]
    assert "workflow.completed" in event_names


@pytest.mark.asyncio
async def test_inline_runner_mcp_step_ok(monkeypatch):
    """Single mcp step: tool is called, result flows through scrub."""
    events, emitter = _make_emitter()

    async def fake_mcp_task(task_config, context, jinja_env, task_with=None, **kwargs):
        return {"status": "ok", "data": {"mcp_result": "firestore_doc"}}

    monkeypatch.setattr(
        "noetl.tools.mcp.execute_mcp_task",
        fake_mcp_task,
    )

    async def fake_scrub(**kwargs):
        return kwargs["result"]

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.inline_runner._scrub_result",
        fake_scrub,
    )

    result = await run_inline(
        parent_execution_id="parent-mcp",
        parent_command_id="cmd-mcp",
        parent_step="agent_step",
        child_playbook=_mcp_playbook(),
        child_input={"doc_id": "abc"},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
    )

    assert result.status == "ok"
    assert result.data == {"status": "ok", "data": {"mcp_result": "firestore_doc"}}


@pytest.mark.asyncio
async def test_inline_runner_parent_cancellation():
    """Parent cancel mid-child: execution.cancelled emitted, error with PLAYBOOK_CANCELLED."""
    events, emitter = _make_emitter()

    result = await run_inline(
        parent_execution_id="parent-cancel",
        parent_command_id="cmd-cancel",
        parent_step="agent_step",
        child_playbook=_noop_playbook(),
        child_input={},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(True),  # Always cancelled.
        batch_event_emitter=emitter,
        depth=0,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error["code"] == "PLAYBOOK_CANCELLED"
    event_names = [e["name"] for e in events]
    assert "execution.cancelled" in event_names


@pytest.mark.asyncio
async def test_inline_runner_step_failure(monkeypatch):
    """Step exception: terminal envelope has status error, failure events emitted."""
    events, emitter = _make_emitter()

    async def exploding_python(task_config, context, jinja_env, args=None, **kwargs):
        raise ValueError("simulated tool crash")

    monkeypatch.setattr(
        "noetl.tools.python.execute_python_task_async",
        exploding_python,
    )

    result = await run_inline(
        parent_execution_id="parent-fail",
        parent_command_id="cmd-fail",
        parent_step="agent_step",
        child_playbook=_python_playbook(),
        child_input={},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
    )

    assert result.status == "error"
    assert result.error["code"] == "INLINE_STEP_FAILED"
    assert "simulated tool crash" in result.error["message"]

    event_names = [e["name"] for e in events]
    assert "call.error" in event_names
    assert "command.failed" in event_names
    assert "workflow.failed" in event_names


@pytest.mark.asyncio
async def test_inline_runner_depth_within_limit():
    """depth=DEFAULT_MAX_DEPTH (3) runs inline successfully."""
    events, emitter = _make_emitter()

    result = await run_inline(
        parent_execution_id="parent-deep",
        parent_command_id=None,
        parent_step="agent_step",
        child_playbook=_noop_playbook(),
        child_input={},
        inline_decision=_make_decision(depth=DEFAULT_MAX_DEPTH),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=DEFAULT_MAX_DEPTH,
    )

    assert result.status == "ok"


@pytest.mark.asyncio
async def test_inline_runner_depth_beyond_limit():
    """depth=DEFAULT_MAX_DEPTH + 1 is refused with INLINE_DEPTH_EXCEEDED."""
    events, emitter = _make_emitter()

    result = await run_inline(
        parent_execution_id="parent-tooDeep",
        parent_command_id=None,
        parent_step="agent_step",
        child_playbook=_noop_playbook(),
        child_input={},
        inline_decision=_make_decision(depth=DEFAULT_MAX_DEPTH + 1),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=DEFAULT_MAX_DEPTH + 1,
    )

    assert result.status == "error"
    assert result.error["code"] == "INLINE_DEPTH_EXCEEDED"
    # No lifecycle events should have been emitted — runner returned before init.
    assert len(events) == 0


@pytest.mark.asyncio
async def test_inline_runner_emits_command_projection_events():
    """Every step must emit command.started and command.completed events."""
    events, emitter = _make_emitter()

    playbook = {
        "metadata": {"name": "test/multi"},
        "workflow": [
            {"step": "step_a", "tool": {"kind": "noop"}},
            {"step": "step_b", "tool": {"kind": "noop"}},
        ],
    }

    result = await run_inline(
        parent_execution_id="parent-proj",
        parent_command_id="cmd-proj",
        parent_step="agent_step",
        child_playbook=playbook,
        child_input={},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
    )

    assert result.status == "ok"
    # Two steps → two command.started + two command.completed
    started = [e for e in events if e["name"] == "command.started"]
    completed = [e for e in events if e["name"] == "command.completed"]
    assert len(started) == 2
    assert len(completed) == 2

    # Each event must carry inline metadata.
    for ev in started + completed:
        payload = ev.get("payload") or {}
        assert "meta" in payload
        assert payload["meta"]["inline_mode"] == "worker"
        assert payload["meta"]["inlined_in_parent"] == "parent-proj"


@pytest.mark.asyncio
async def test_inline_runner_inline_result_envelope_shape():
    """InlineResult.to_envelope returns agent-envelope-compatible dict."""
    events, emitter = _make_emitter()

    result = await run_inline(
        parent_execution_id="parent-env",
        parent_command_id="cmd-env",
        parent_step="agent_step",
        child_playbook=_noop_playbook(),
        child_input={"key": "value"},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
    )

    envelope = result.to_envelope(entrypoint="test/noop")
    assert envelope["framework"] == "noetl"
    assert envelope["entrypoint"] == "test/noop"
    assert envelope["status"] == "ok"
    assert "execution_id" in envelope
    assert "meta" in envelope
    assert envelope["meta"]["inline_mode"] == "worker"
