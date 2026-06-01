"""Regression tests for noetl/ai-meta#37.

Two bugs, fixed together:

  A. The engine did not emit ``workflow.completed`` when the terminal step
     was named anything other than ``"end"``.  Root cause: the durable
     pending-command count queried ``noetl.command`` without excluding the
     current step's command, which is still RUNNING when ``call.done``
     fires (the worker posts ``command.completed`` after ``call.done``).
     The false positive caused ``has_pending_commands = True``, blocking
     the completion gate.

  B. The status endpoint inference hardcoded ``node_name == "end"`` in
     two places.  Any terminal step with a different name would never be
     inferred as complete.

Both tests use a 3-step playbook whose terminal step is named ``"done"``
(not ``"end"``), mirroring the ``rust-worker-r2-validation.yaml`` fixture.
"""

import pytest
from unittest.mock import AsyncMock
from noetl.core.dsl.engine.executor import ControlFlowEngine, PlaybookRepo, StateStore, ExecutionState
from noetl.core.dsl.engine.models import Event
from noetl.core.dsl.engine.parser import DSLParser


_PLAYBOOK_YAML = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: done_terminal_regression
  path: tests/fixtures/done_terminal_regression

workflow:
  - step: step_a
    tool:
      kind: shell
      command: 'echo step_a'
    next:
      arcs:
        - step: step_b

  - step: step_b
    tool:
      kind: shell
      command: 'echo step_b'
    next:
      arcs:
        - step: done

  - step: done
    tool:
      kind: shell
      command: 'echo done'
"""


@pytest.fixture
def _engine_and_state(monkeypatch):
    """Return a (engine, state) pair wired against a no-op DB/NATS."""
    playbook = DSLParser().parse(_PLAYBOOK_YAML)
    state = ExecutionState(
        execution_id="9000000000000001",
        playbook=playbook,
        payload={},
    )
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    monkeypatch.setattr(state_store, "load_state", AsyncMock(return_value=state))
    monkeypatch.setattr(state_store, "load_state_for_update", AsyncMock(return_value=state))
    monkeypatch.setattr(state_store, "_save_state_inner", AsyncMock(return_value=None))
    engine._persist_event = AsyncMock(return_value=None)

    # Simulate that step_a and step_b completed prior to this test round.
    state.completed_steps.add("step_a")
    state.completed_steps.add("step_b")
    # "done" was issued — it is in issued_steps but NOT yet in completed_steps.
    state.issued_steps.add("done")

    return engine, state


@pytest.mark.asyncio
async def test_engine_emits_workflow_completed_for_non_end_terminal_step(
    _engine_and_state, monkeypatch
):
    """Engine must emit workflow.completed when the terminal step is named 'done'.

    Regression for noetl/ai-meta#37 Fix A.

    The durable pending-count query in ``_count_durable_pending_commands``
    used to count the triggering command as still-pending (RUNNING status in
    noetl.command), blocking the completion gate.  The fix excludes the
    current command_id from the count.
    """
    engine, state = _engine_and_state

    # Capture events persisted by the cascade.
    persisted_events: list[Event] = []

    async def _capture_persist(event, st, conn=None):
        persisted_events.append(event)
        # Advance last_event_id so chaining works.
        st.last_event_id = (st.last_event_id or 0) + 1

    engine._persist_event = _capture_persist

    # Simulate call.done for the "done" terminal step.
    # Include a command_id so the exclude path is exercised.
    event = Event(
        execution_id="9000000000000001",
        step="done",
        name="call.done",
        payload={
            "command_id": "1234567890",
            "result": {"status": "COMPLETED"},
        },
    )

    commands = await engine.handle_event(event, already_persisted=True)

    # No further commands should be issued — the workflow is done.
    assert commands == [], f"Expected no commands after terminal step, got {commands}"

    # state.completed must be set.
    assert state.completed is True, "state.completed should be True after terminal step"

    # The cascade must have emitted workflow.completed and playbook.completed.
    emitted_names = [e.name for e in persisted_events]
    assert "workflow.completed" in emitted_names, (
        f"workflow.completed not found in emitted events: {emitted_names}"
    )
    assert "playbook.completed" in emitted_names, (
        f"playbook.completed not found in emitted events: {emitted_names}"
    )


@pytest.mark.asyncio
async def test_engine_terminal_step_debug_log_is_emitted(
    _engine_and_state, monkeypatch, caplog
):
    """DEBUG log must fire when the is_terminal_step branch triggers.

    Observability hook per agents/rules/observability.md Principle 1.
    """
    import logging

    engine, state = _engine_and_state

    async def _noop_persist(event, st, conn=None):
        st.last_event_id = (st.last_event_id or 0) + 1

    engine._persist_event = _noop_persist

    event = Event(
        execution_id="9000000000000001",
        step="done",
        name="call.done",
        payload={
            "command_id": "1234567891",
            "result": {"status": "COMPLETED"},
        },
    )

    with caplog.at_level(logging.DEBUG, logger="noetl"):
        await engine.handle_event(event, already_persisted=True)

    terminal_logs = [r for r in caplog.records if "Terminal step reached" in r.message]
    assert terminal_logs, (
        "Expected a DEBUG log containing 'Terminal step reached' when is_terminal_step fires"
    )
    # Confirm execution_id and step are present in the log message.
    log_msg = terminal_logs[0].message
    assert "done" in log_msg, f"Expected step='done' in log: {log_msg}"
    assert "9000000000000001" in log_msg, f"Expected execution_id in log: {log_msg}"
