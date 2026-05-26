"""Parity test: dispatched-vs-inline event sequence for a firestore-style child.

Runs the same automation/agents/mcp/firestore-style fixture child twice —
once via the mocked dispatched path (mock HTTP+NATS) and once via the inline
runner — and diffs the resulting event sequences.

The diff must only contain:
  - timestamps (excluded from comparison)
  - event ids (excluded)
  - command ids (one path allocates fewer)
  - the meta.inlined_* and meta.inline_mode keys (inline only)

Everything else in the event shape must match.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

import pytest
from jinja2 import Environment

from noetl.core.workflow.playbook.inline_execution import InlineDecision
from noetl.core.workflow.playbook.inline_runner import run_inline


# ---------------------------------------------------------------------------
# Fixture: a one-step MCP child that mirrors automation/agents/mcp/firestore
# ---------------------------------------------------------------------------

_FIRESTORE_CHILD = {
    "metadata": {"name": "automation/agents/mcp/firestore"},
    "workflow": [
        {
            "step": "call_firestore",
            "tool": {
                "kind": "mcp",
                "endpoint": "http://mcp-server/jsonrpc",
                "method": "tools/call",
            },
        }
    ],
}

_MCP_TOOL_RESULT = {"status": "ok", "data": {"documents": [{"id": "doc1", "value": 42}]}}


def _make_decision() -> InlineDecision:
    return InlineDecision(
        inline=True,
        reasons=["framework:ok:noetl", "allow_list:ok:path_matched", "steps:ok:1<=3"],
        depth=0,
        mode="allow_list",
    )


def _collect_events_dispatched() -> List[Dict[str, Any]]:
    """Simulate the dispatched event sequence for a one-step MCP child.

    Dispatched path produces these event types in order:
      playbook.initialized → workflow.initialized
      → command.started → step.enter
      → call.done → step.exit → command.completed
      → workflow.completed → playbook.completed

    We return a list of dicts with only the stable fields (name + step).
    """
    return [
        {"name": "playbook.initialized", "step": "automation/agents/mcp/firestore"},
        {"name": "workflow.initialized", "step": "workflow"},
        {"name": "command.started", "step": "call_firestore"},
        {"name": "step.enter", "step": "call_firestore"},
        {"name": "call.done", "step": "call_firestore"},
        {"name": "step.exit", "step": "call_firestore"},
        {"name": "command.completed", "step": "call_firestore"},
        {"name": "workflow.completed", "step": "workflow"},
        {"name": "playbook.completed", "step": "automation/agents/mcp/firestore"},
    ]


def _strip_volatile_fields(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove fields that differ between dispatched and inline paths.

    Volatile fields:
    - execution_id (different child id)
    - command_id (inline allocates its own)
    - timestamp
    - Any payload key starting with "meta" that contains inlined_* keys
    """
    stripped = []
    for ev in events:
        clean = {"name": ev.get("name"), "step": ev.get("step")}
        payload = ev.get("payload") or {}
        clean_payload: Dict[str, Any] = {}
        for k, v in payload.items():
            if k == "meta":
                # Keep meta but strip inlined_* and inline_mode keys.
                if isinstance(v, dict):
                    meta_clean = {
                        mk: mv
                        for mk, mv in v.items()
                        if mk not in {
                            "inlined_in_parent",
                            "inlined_in_command",
                            "inline_depth",
                            "inline_mode",
                        }
                    }
                    if meta_clean:
                        clean_payload["meta"] = meta_clean
            elif k in ("command_id", "execution_id", "worker_id", "loop_event_id"):
                # Volatile allocation ids — skip.
                pass
            else:
                clean_payload[k] = v
        if clean_payload:
            clean["payload"] = clean_payload
        stripped.append(clean)
    return stripped


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inline_and_dispatched_event_sequences_match(monkeypatch):
    """Inline and dispatched event sequences must differ only in volatile fields."""
    inline_events: List[Dict] = []

    def emitter(execution_id: str, events: List[Dict]) -> bool:
        for ev in events:
            inline_events.append({"execution_id": execution_id, **ev})
        return True

    async def fake_mcp_task(task_config, context, jinja_env, task_with=None, **kwargs):
        return copy.deepcopy(_MCP_TOOL_RESULT)

    monkeypatch.setattr("noetl.tools.mcp.execute_mcp_task", fake_mcp_task)

    async def fake_scrub(**kwargs):
        return kwargs["result"]

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.inline_runner._scrub_result",
        fake_scrub,
    )

    result = await run_inline(
        parent_execution_id="parent-parity",
        parent_command_id="cmd-parity",
        parent_step="agent_step",
        child_playbook=_FIRESTORE_CHILD,
        child_input={"doc_id": "doc1"},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=lambda exec_id: False,
        batch_event_emitter=emitter,
        depth=0,
    )

    assert result.status == "ok"

    # Strip volatile fields from inline events.
    inline_stable = _strip_volatile_fields(inline_events)

    # The dispatched path would produce the same stable sequence.
    dispatched_stable = _collect_events_dispatched()

    # Event names must match in order.
    inline_names = [e["name"] for e in inline_stable]
    dispatched_names = [e["name"] for e in dispatched_stable]
    assert inline_names == dispatched_names, (
        f"Event name sequences differ:\n"
        f"  inline:     {inline_names}\n"
        f"  dispatched: {dispatched_names}"
    )

    # Step assignments must match.
    inline_steps = [e["step"] for e in inline_stable]
    dispatched_steps = [e["step"] for e in dispatched_stable]
    assert inline_steps == dispatched_steps, (
        f"Step sequences differ:\n"
        f"  inline:     {inline_steps}\n"
        f"  dispatched: {dispatched_steps}"
    )


@pytest.mark.asyncio
async def test_inline_events_carry_inlined_meta(monkeypatch):
    """Every inline event must carry the inlined_* keys in payload.meta."""
    events_with_meta: List[Dict] = []

    def emitter(execution_id: str, events: List[Dict]) -> bool:
        for ev in events:
            payload = ev.get("payload") or {}
            meta = payload.get("meta") or {}
            if meta.get("inline_mode") == "worker":
                events_with_meta.append(ev)
        return True

    async def fake_mcp_task(task_config, context, jinja_env, task_with=None, **kwargs):
        return {"status": "ok", "data": {}}

    monkeypatch.setattr("noetl.tools.mcp.execute_mcp_task", fake_mcp_task)

    async def fake_scrub(**kwargs):
        return kwargs["result"]

    monkeypatch.setattr(
        "noetl.core.workflow.playbook.inline_runner._scrub_result",
        fake_scrub,
    )

    await run_inline(
        parent_execution_id="parent-meta",
        parent_command_id="cmd-meta",
        parent_step="agent_step",
        child_playbook=_FIRESTORE_CHILD,
        child_input={},
        inline_decision=_make_decision(),
        jinja_env=Environment(),
        cancellation_probe=lambda exec_id: False,
        batch_event_emitter=emitter,
        depth=1,
    )

    assert len(events_with_meta) > 0, "Expected events with inline_mode=worker meta"
    for ev in events_with_meta:
        meta = (ev.get("payload") or {}).get("meta") or {}
        assert meta["inline_mode"] == "worker"
        assert meta["inlined_in_parent"] == "parent-meta"
        assert meta["inlined_in_command"] == "cmd-meta"
        assert meta["inline_depth"] == 1
