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


# PostgreSQL ``bigint`` is signed 64-bit; its maximum value is
# 9223372036854775807 (~9.22e18).  Every ``execution_id`` column in the
# NoETL schema uses that type.  An id that exceeds this range cannot be
# inserted into the database and causes downstream lookups to fail with
# ``value "..." is out of range for type bigint``.
_BIGINT_MAX = 9223372036854775807


def test_allocate_child_execution_id_fits_postgres_bigint():
    """Regression test: the runner's child id allocator must produce ids
    that fit PostgreSQL ``bigint``.  An earlier shape used ``% (10 ** 20)``
    which produced 20-digit ids up to ~9.99e19 — about 11x the bigint
    ceiling.  Phase D on GKE observed
    ``value "69474466565741823165" is out of range for type bigint``
    when the runner emitted child events under that id."""
    # Sample enough times that any single overflow would surface; UUID4 is
    # uniform, so every draw should satisfy the bound.
    for _ in range(500):
        as_str = _allocate_child_execution_id()
        assert isinstance(as_str, str)
        # 18-digit zero-padded shape — never longer.
        assert len(as_str) == 18, f"expected 18-char id, got {as_str!r}"
        as_int = int(as_str)
        assert as_int <= _BIGINT_MAX, (
            f"id {as_str} overflows PostgreSQL bigint "
            f"({as_int} > {_BIGINT_MAX})"
        )


def test_allocate_child_execution_id_returns_unique_ids():
    """UUID4 has 122 bits of entropy; even after ``% (10 ** 18)`` the
    18-digit space holds ~1.15e18 distinct values.  Across 1000 samples
    we should observe zero collisions."""
    ids = {_allocate_child_execution_id() for _ in range(1000)}
    assert len(ids) == 1000, "expected 1000 distinct ids; got collisions"


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


@pytest.mark.asyncio
async def test_inline_runner_data_skips_noop_end_boundary_step():
    """Regression test for Bug B from Round B Phase D: when a playbook ends
    with an ``end: {tool: {kind: noop}}`` terminator, the runner's
    ``InlineResult.data`` must surface the last MEANINGFUL step's result,
    not the noop's ``{"status": "ok"}``.  This mirrors the dispatched
    agent path's ``_fetch_sub_execution_terminal_result`` which filters
    out boundary node names (``start`` / ``end`` / "" / None) when
    walking events for the playbook's externally-visible terminal
    result.

    Phase D evidence on GKE
    (``automation/agents/mcp/vertex-ai-stub``, child execution id
    ``465179147430762901``): worker log
    ``[RESULT] Step canned_chat_completion: inline result (1799b)``
    followed by ``[RESULT] Step end: inline result (15b)``.  Pre-fix the
    runner returned the 15-byte ``{"status": "ok"}`` and masked the
    1799-byte diagnosis payload.
    """
    _events, emitter = _make_emitter()

    playbook = {
        "metadata": {"name": "test/python_then_end_noop"},
        "workflow": [
            {
                "step": "produce_payload",
                "tool": {
                    "kind": "python",
                    "code": "result = {'category': 'unknown', 'confidence': 0.63}",
                },
            },
            {"step": "end", "tool": {"kind": "noop"}},
        ],
    }

    result = await run_inline(
        parent_execution_id="parent-bugb",
        parent_command_id="cmd-bugb",
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
    # The data must be ``produce_payload``'s result, NOT ``end``'s
    # ``{"status": "ok"}``.  The exact wrapper shape comes from
    # ResultHandler scrub; we only assert the meaningful payload is
    # reachable.
    data_str = repr(result.data)
    assert "category" in data_str or "confidence" in data_str, (
        f"InlineResult.data lost the meaningful step's payload. "
        f"Got: {result.data!r}"
    )
    # Sanity: the noop end's degenerate sentinel must NOT be the whole
    # data envelope.
    assert result.data != {"status": "ok"}, (
        "InlineResult.data is the noop terminator's sentinel; the "
        "boundary-step filter regressed."
    )


@pytest.mark.asyncio
async def test_inline_runner_data_falls_back_when_only_boundary_steps():
    """Degenerate corner case: a workflow that contains only an ``end``
    step has no meaningful results.  Fall back to ``last_result``
    (the noop's payload) rather than ``None`` so callers don't have to
    special-case ``data is None``."""
    _events, emitter = _make_emitter()

    playbook = {
        "metadata": {"name": "test/only_end_step"},
        "workflow": [
            {"step": "end", "tool": {"kind": "noop"}},
        ],
    }

    result = await run_inline(
        parent_execution_id="parent-only-end",
        parent_command_id="cmd-only-end",
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
    # No meaningful steps ran; the runner falls back to the noop's
    # result rather than emitting ``data=None``.
    assert result.data is not None


@pytest.mark.asyncio
async def test_inline_runner_data_skips_start_boundary_step():
    """``start`` is also a boundary node name in the dispatched path's
    filter.  A workflow that opens with a ``start`` step (rare but
    declarable) must not mask a real intermediate result either."""
    _events, emitter = _make_emitter()

    playbook = {
        "metadata": {"name": "test/start_then_python"},
        "workflow": [
            {"step": "start", "tool": {"kind": "noop"}},
            {
                "step": "do_work",
                "tool": {
                    "kind": "python",
                    "code": "result = {'value': 42}",
                },
            },
            {"step": "end", "tool": {"kind": "noop"}},
        ],
    }

    result = await run_inline(
        parent_execution_id="parent-start",
        parent_command_id="cmd-start",
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
    data_str = repr(result.data)
    assert "value" in data_str or "42" in data_str, (
        f"InlineResult.data lost do_work's payload. Got: {result.data!r}"
    )


# ---------------------------------------------------------------------------
# Event payload schema regression tests
#
# Round B Phase D on the noetl-demo GKE cluster failed because the runner's
# emitted events did not comply with ``_STRICT_RESULT_ALLOWED_KEYS = {"status",
# "reference", "context", "command_id"}``.  The server's
# ``_validate_reference_only_payload`` rejected every batch with
# ``payload.result includes unsupported keys: ...`` and the runner's
# ``_safe_emit`` swallowed the 500.  Symptom: SPA hung on "Muno is planning..."
# with no visible diagnostic.  These tests guard the event payload shapes.
# ---------------------------------------------------------------------------


_STRICT_RESULT_ALLOWED_KEYS = {"status", "reference", "context", "command_id"}


def _assert_payload_result_keys_allowed(payload, *, event_name: str) -> None:
    """Helper mirroring the server's ``_validate_reference_only_payload``
    rule for the ``payload.result`` key set."""
    if not isinstance(payload, dict):
        return
    result_obj = payload.get("result")
    if result_obj is None:
        return
    assert isinstance(result_obj, dict), (
        f"{event_name}: payload.result must be a dict; got {type(result_obj).__name__}"
    )
    unknown = {k for k in result_obj.keys() if k not in _STRICT_RESULT_ALLOWED_KEYS}
    assert not unknown, (
        f"{event_name}: payload.result includes unsupported keys: "
        f"{sorted(unknown)} (allowed: {sorted(_STRICT_RESULT_ALLOWED_KEYS)})"
    )


@pytest.mark.asyncio
async def test_inline_runner_emitted_events_comply_with_strict_payload_schema():
    """Every event the inline runner emits must keep ``payload.result``
    within ``_STRICT_RESULT_ALLOWED_KEYS``.  Pre-fix ``playbook.initialized``
    and ``workflow.initialized`` smuggled ``workload``/``playbook_path``
    into ``result``, and ``workflow.completed`` spread the tool result
    dict (``{"id": "...", "data": {...}, "status": "ok"}``) directly into
    ``result``, both of which the server's
    ``_validate_reference_only_payload`` rejected with HTTP 500."""
    events, emitter = _make_emitter()

    playbook = {
        "metadata": {"name": "test/firestore_dispatch_style"},
        "workflow": [
            {
                "step": "firestore_dispatch",
                "tool": {
                    "kind": "python",
                    # Mirror the real firestore mcp playbook's terminal
                    # result envelope: ``{"id": "...", "data": {...},
                    # "status": "ok"}``.  Pre-fix this was the exact shape
                    # that broke workflow.completed.
                    "code": (
                        "result = {"
                        "    'id': '8d3da932-dcde-4274-8a47-firestore',"
                        "    'data': {'rows': [{'value': 'ok'}]},"
                        "    'status': 'ok',"
                        "}"
                    ),
                },
            },
            {"step": "end", "tool": {"kind": "noop"}},
        ],
    }

    result = await run_inline(
        parent_execution_id="parent-schema",
        parent_command_id="cmd-schema",
        parent_step="agent_step",
        child_playbook=playbook,
        child_input={"firestore_database": "(default)"},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
    )

    assert result.status == "ok"
    # The runner must have emitted at least the playbook.initialized +
    # workflow.completed events.
    event_names = {ev.get("name") for ev in events}
    assert "playbook.initialized" in event_names
    assert "workflow.initialized" in event_names
    assert "workflow.completed" in event_names
    assert "playbook.completed" in event_names

    for ev in events:
        _assert_payload_result_keys_allowed(
            ev.get("payload"), event_name=ev.get("name", "<unknown>")
        )


@pytest.mark.asyncio
async def test_inline_runner_workflow_completed_wraps_tool_result_in_context():
    """``workflow.completed`` historically dropped the last step's result
    dict directly into ``payload.result``, which violated the
    strict-allowed-keys rule (``id``, ``data`` are not allowed at that
    layer).  The fix wraps the tool result inside ``payload.result.context``
    so downstream readers can still reach it at ``result.context.*`` and
    the strict-keys check passes.

    Note: the runner emits ``workflow.completed`` with ``last_result``
    (the literal last step's result), not ``last_meaningful_result`` —
    mirroring the dispatched path's ``LifecycleEventPayload(result=
    event.payload.get('result'))`` shape where ``event`` is the
    terminating step.exit event.  Data preservation for the agent
    envelope (which uses ``last_meaningful_result``) is covered by
    ``test_inline_runner_data_skips_noop_end_boundary_step``."""
    events, emitter = _make_emitter()

    # Single-step playbook so ``last_result`` is the tool's dict
    # directly (the very shape that pre-fix violated the schema).
    playbook = {
        "metadata": {"name": "test/python_with_id_data_status"},
        "workflow": [
            {
                "step": "produce",
                "tool": {
                    "kind": "python",
                    "code": "result = {'id': 'x', 'data': {'category': 'unknown'}, 'status': 'ok'}",
                },
            },
        ],
    }

    await run_inline(
        parent_execution_id="parent-ctx",
        parent_command_id="cmd-ctx",
        parent_step="agent_step",
        child_playbook=playbook,
        child_input={},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
    )

    completed = [e for e in events if e.get("name") == "workflow.completed"]
    assert completed, "workflow.completed must be emitted"
    payload = completed[0].get("payload") or {}
    result_obj = payload.get("result") or {}
    # Strict-keys rule
    assert set(result_obj.keys()).issubset(_STRICT_RESULT_ALLOWED_KEYS), (
        f"workflow.completed payload.result has forbidden keys: "
        f"{sorted(result_obj.keys())}"
    )
    # The actual tool payload is reachable through context
    ctx = result_obj.get("context") or {}
    assert isinstance(ctx, dict), f"result.context must be a dict; got {ctx!r}"
    assert "id" in ctx or "data" in ctx or "category" in repr(ctx), (
        f"workflow.completed lost the tool result payload. "
        f"Got result.context={ctx!r}"
    )


@pytest.mark.asyncio
async def test_inline_runner_init_events_move_workload_into_meta():
    """``playbook.initialized`` and ``workflow.initialized`` historically
    placed ``workload`` and ``playbook_path`` directly inside
    ``payload.result``, which the server rejected.  The fix moves both
    into ``payload.meta`` so the information is preserved without
    violating the strict-allowed-keys rule."""
    events, emitter = _make_emitter()

    playbook = {
        "metadata": {"name": "test/init_event_meta"},
        "workflow": [
            {"step": "noop", "tool": {"kind": "noop"}},
        ],
    }

    await run_inline(
        parent_execution_id="parent-init",
        parent_command_id="cmd-init",
        parent_step="agent_step",
        child_playbook=playbook,
        child_input={"db_credential": "pg_auth", "tenant": "demo"},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
    )

    for evt_name in ("playbook.initialized", "workflow.initialized"):
        matching = [e for e in events if e.get("name") == evt_name]
        assert matching, f"expected {evt_name!r} event in emitted stream"
        payload = matching[0].get("payload") or {}
        # Strict keys must hold
        _assert_payload_result_keys_allowed(payload, event_name=evt_name)
        # ``workload`` and ``playbook_path`` must NOT appear under result
        result_obj = payload.get("result") or {}
        assert "workload" not in result_obj
        assert "playbook_path" not in result_obj
        # ...but should be reachable via payload.meta
        meta = payload.get("meta") or {}
        assert meta.get("playbook_path") == "test/init_event_meta"
        # ``inline_workload`` carries the child_input dict (renamed to
        # avoid colliding with the generic ``workload`` field downstream
        # readers may project from event meta).
        assert isinstance(meta.get("inline_workload"), dict)
        assert meta["inline_workload"].get("db_credential") == "pg_auth"


# ---------------------------------------------------------------------------
# parent_catalog_id wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inline_runner_passes_parent_catalog_id_to_emitter():
    """The runner must forward ``parent_catalog_id`` to the batch emitter
    via the emitter's ``set_catalog_id`` mutator.  Without it the server
    cannot populate ``noetl.event.catalog_id`` for child events (the
    column is NOT NULL and the per-execution DB lookup returns None for
    inline children with no prior event rows)."""

    set_catalog_id_calls: list = []

    class _ProbeEmitter:
        def __init__(self) -> None:
            self.emit_calls: list = []

        def set_catalog_id(self, catalog_id):
            set_catalog_id_calls.append(catalog_id)

        def __call__(self, execution_id, events):
            self.emit_calls.append((execution_id, events))
            return True

    emitter = _ProbeEmitter()

    await run_inline(
        parent_execution_id="parent-cat",
        parent_command_id="cmd-cat",
        parent_step="agent_step",
        child_playbook={"workflow": [{"step": "noop", "tool": {"kind": "noop"}}]},
        child_input={},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
        parent_catalog_id=635123456789012345,
    )

    assert set_catalog_id_calls == [635123456789012345], (
        f"runner did not wire parent_catalog_id through; got calls: "
        f"{set_catalog_id_calls!r}"
    )


@pytest.mark.asyncio
async def test_inline_runner_legacy_emitter_without_set_catalog_id_still_works():
    """Tests in the suite construct simple 2-arg lambdas as emitters.
    Those must keep working — the runner only calls ``set_catalog_id``
    if the emitter exposes it, and a missing method must not abort
    the run."""
    events, emitter = _make_emitter()

    result = await run_inline(
        parent_execution_id="parent-legacy",
        parent_command_id="cmd-legacy",
        parent_step="agent_step",
        child_playbook={"workflow": [{"step": "noop", "tool": {"kind": "noop"}}]},
        child_input={},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=_cancellation_probe_returning(False),
        batch_event_emitter=emitter,
        depth=0,
        parent_catalog_id=635999999999999999,
    )

    assert result.status == "ok"
    # The legacy callable still received emissions.
    assert events, "legacy emitter must still receive events"
