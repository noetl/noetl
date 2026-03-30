"""
Tests for NoETL DSL v2 Control Flow Engine
"""

import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from noetl.core.dsl.v2.engine import ControlFlowEngine, PlaybookRepo, StateStore, ExecutionState
from noetl.core.dsl.v2.models import Event, Command, Playbook
from noetl.core.dsl.v2.parser import DSLParser


@asynccontextmanager
async def _mock_pool_connection(pending_count: int = 0):
    """Async context manager that returns a fake DB connection/cursor yielding pending_count."""
    cur = AsyncMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    cur.fetchone = AsyncMock(return_value={"pending_count": pending_count})
    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cur)
    yield conn


@pytest.fixture
def engine_setup():
    """Set up engine components."""
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)
    return engine, playbook_repo, state_store


def _make_minimal_playbook(name: str = "test") -> Playbook:
    """Return a minimal v2 playbook with a single step that has a call.error recovery arc."""
    yaml_content = f"""
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: {name}

workflow:
  - step: fetch_data
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com/data"
    next:
      - step: recovery_step
        when: "{{{{ event.name == 'call.error' }}}}"
      - step: end

  - step: recovery_step
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com/fallback"

  - step: end
    tool:
      kind: python
      code: "def main(): return {{}}"
"""
    return DSLParser().parse(yaml_content)


def test_handle_workflow_start(engine_setup):
    """Test handling workflow.start event."""
    engine, playbook_repo, state_store = engine_setup
    
    # Create and register playbook
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test_workflow

workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-123")
    
    # Create workflow.start event
    event = Event(
        execution_id="exec-123",
        name="workflow.start",
        payload={}
    )
    
    # Handle event
    commands = engine.handle_event(event)
    
    # Should generate command for start step
    assert len(commands) == 1
    assert commands[0].step == "start"
    assert commands[0].tool.kind == "python"


def test_case_rule_matching(engine_setup):
    """Test case/when/then rule evaluation."""
    engine, playbook_repo, state_store = engine_setup
    
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: case_test

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com"
    
    case:
      - when: "{{ event.name == 'call.done' and response.status == 200 }}"
        then:
          result:
            from: response.data
          next:
            - step: end

  - step: end
    tool:
      kind: python
      code: "def main(): return {}"
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-456")
    
    # Create call.done event with successful response
    event = Event(
        execution_id="exec-456",
        step="start",
        name="call.done",
        payload={
            "response": {
                "status": 200,
                "data": {"result": "success"}
            }
        }
    )
    
    # Handle event
    commands = engine.handle_event(event)
    
    # Should generate next command to 'end' step
    assert len(commands) == 1
    assert commands[0].step == "end"


def test_retry_action(engine_setup):
    """Test retry action on error."""
    engine, playbook_repo, state_store = engine_setup
    
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: retry_test

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com"
    
    case:
      - when: "{{ event.name == 'call.done' and error is defined and error.status == 503 }}"
        then:
          retry:
            max_attempts: 3
            backoff_multiplier: 2.0
            initial_delay: 0.5
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-retry")
    
    # Create call.done event with 503 error
    event = Event(
        execution_id="exec-retry",
        step="start",
        name="call.done",
        payload={
            "error": {
                "status": 503,
                "message": "Service Unavailable"
            }
        },
        attempt=1
    )
    
    # Handle event
    commands = engine.handle_event(event)
    
    # Should generate retry command
    assert len(commands) == 1
    assert commands[0].step == "start"
    assert commands[0].attempt == 2
    assert commands[0].backoff is not None


def test_collect_action(engine_setup):
    """Test collect action for aggregation."""
    engine, playbook_repo, state_store = engine_setup
    
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: collect_test

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com"
    
    case:
      - when: "{{ event.name == 'step.enter' }}"
        then:
          set:
            ctx:
              items: []
      
      - when: "{{ event.name == 'call.done' and response is defined }}"
        then:
          collect:
            from: response.data.items
            into: items
            mode: extend
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-collect")
    
    # First event: step.enter
    event1 = Event(
        execution_id="exec-collect",
        step="start",
        name="step.enter",
        payload={}
    )
    
    engine.handle_event(event1)
    
    # Get state
    state = state_store.get("exec-collect")
    assert "items" in state.context
    assert state.context["items"] == []
    
    # Second event: call.done with data
    event2 = Event(
        execution_id="exec-collect",
        step="start",
        name="call.done",
        payload={
            "response": {
                "data": {
                    "items": [{"id": 1}, {"id": 2}]
                }
            }
        }
    )
    
    engine.handle_event(event2)
    
    # Check that items were collected
    state = state_store.get("exec-collect")
    assert len(state.context["items"]) == 2


def test_pagination_pattern(engine_setup):
    """Test complete pagination pattern."""
    engine, playbook_repo, state_store = engine_setup
    
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: pagination_test

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com/data"
      params:
        page: 1
    
    case:
      - when: "{{ event.name == 'step.enter' }}"
        then:
          set:
            ctx:
              all_items: []
      
      - when: "{{ event.name == 'call.done' and response.paging.hasMore == true }}"
        then:
          collect:
            from: response.items
            into: all_items
            mode: extend
          call:
            params:
              page: "{{ (response.paging.page | int) + 1 }}"
      
      - when: "{{ event.name == 'call.done' and response.paging.hasMore == false }}"
        then:
          collect:
            from: response.items
            into: all_items
            mode: extend
          result:
            from: ctx.all_items
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-page")
    
    # Step enter
    event1 = Event(
        execution_id="exec-page",
        step="start",
        name="step.enter",
        payload={}
    )
    engine.handle_event(event1)
    
    # First page (hasMore=true)
    event2 = Event(
        execution_id="exec-page",
        step="start",
        name="call.done",
        payload={
            "response": {
                "items": [{"id": 1}, {"id": 2}],
                "paging": {"page": 1, "hasMore": True}
            }
        }
    )
    
    commands = engine.handle_event(event2)
    
    # Should generate call command for next page
    assert len(commands) == 1
    assert commands[0].step == "start"
    
    # Final page (hasMore=false)
    event3 = Event(
        execution_id="exec-page",
        step="start",
        name="call.done",
        payload={
            "response": {
                "items": [{"id": 3}],
                "paging": {"page": 2, "hasMore": False}
            }
        }
    )
    
    commands = engine.handle_event(event3)
    
    # Should not generate more commands (final page)
    # Result should be set in state
    state = state_store.get("exec-page")
    assert len(state.context["all_items"]) == 3


def test_conditional_transition_with_set_and_input(engine_setup):
    """Test conditional transition using arc set + step input."""
    engine, playbook_repo, state_store = engine_setup
    
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: transition_test

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com/data"
    
    next:
      spec:
        mode: exclusive
      arcs:
        - step: process
          when: "{{ event.name == 'call.done' and output.data.status == 200 }}"
          set:
            ctx.process_data: "{{ output.data.data }}"
            ctx.process_count: "{{ output.data.data | length }}"

  - step: process
    input:
      data: "{{ ctx.process_data }}"
      count: "{{ ctx.process_count }}"
    tool:
      kind: python
      code: "def main(data, count): return {'processed': count}"
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-trans")
    
    # call.done event
    event = Event(
        execution_id="exec-trans",
        step="start",
        name="call.done",
        payload={
            "response": {
                "status": 200,
                "data": [1, 2, 3]
            }
        }
    )
    
    commands = engine.handle_event(event)

    # Should generate command for process step with canonical input.
    assert len(commands) == 1
    assert commands[0].step == "process"
    assert commands[0].input is not None


@pytest.mark.asyncio
async def test_command_failed_with_pending_recovery_does_not_terminate(engine_setup):
    """
    When command.failed arrives while recovery commands are in-flight (issued via a
    call.error arc), the engine must NOT emit workflow.failed/playbook.failed and must
    NOT mark the execution as completed.

    Regression: prior to the fix, command.failed unconditionally emitted terminal events,
    cutting executions short even when call.error had already issued recovery steps.
    """
    engine, playbook_repo, state_store = engine_setup
    playbook = _make_minimal_playbook("recovery_test")

    # Pre-build execution state that mirrors what the engine would have after
    # call.error fired and issued recovery_step (recovery command is in-flight).
    state = ExecutionState(
        execution_id="exec-recovery",
        playbook=playbook,
        payload={},
    )
    # recovery_step was issued by the call.error arc but has not yet completed.
    state.issued_steps.add("recovery_step")
    state.failed = True  # command.failed also sets this; pre-set to mimic real sequence

    # Wire the state into the store's in-memory cache so load_state returns it
    # without hitting the database.
    await state_store.save_state(state)

    # Patch _persist_event so the test doesn't need a live DB connection.
    engine._persist_event = AsyncMock(return_value=None)

    event = Event(
        execution_id="exec-recovery",
        step="fetch_data",
        name="command.failed",
        payload={"error": {"message": "infra retry exhausted"}},
    )

    commands = await engine.handle_event(event, already_persisted=True)

    # Execution must NOT be terminated: state.completed remains False.
    reloaded = await state_store.load_state("exec-recovery")
    assert reloaded is not None
    assert reloaded.completed is False, (
        "Execution should not be completed — recovery commands are still in-flight"
    )

    # No terminal events should have been emitted via _persist_event.
    terminal_event_names = {
        call.args[0].name
        for call in engine._persist_event.call_args_list
        if call.args
    }
    assert "workflow.failed" not in terminal_event_names, (
        "workflow.failed must not be emitted while recovery commands are pending"
    )
    assert "playbook.failed" not in terminal_event_names, (
        "playbook.failed must not be emitted while recovery commands are pending"
    )


@pytest.mark.asyncio
async def test_command_failed_without_pending_commands_terminates(engine_setup):
    """
    When command.failed arrives and there are NO pending recovery commands, the
    engine must emit terminal failure events and stop the execution.
    """
    engine, playbook_repo, state_store = engine_setup
    playbook = _make_minimal_playbook("no_recovery_test")

    state = ExecutionState(
        execution_id="200000000000000001",
        playbook=playbook,
        payload={},
    )
    # No recovery commands in-flight — issued_steps is empty.
    assert not state.issued_steps

    await state_store.save_state(state)
    engine._persist_event = AsyncMock(return_value=None)

    event = Event(
        execution_id="200000000000000001",
        step="fetch_data",
        name="command.failed",
        payload={"error": {"message": "infra retry exhausted"}},
    )

    # Patch the DB pool: issued_steps is empty so the engine falls back to a DB
    # pending-count query. Return 0 to confirm no recovery commands are in-flight.
    with patch("noetl.core.dsl.v2.engine.get_pool_connection", lambda: _mock_pool_connection(0)):
        commands = await engine.handle_event(event, already_persisted=True)

    # Terminal events must have been emitted.
    emitted = {
        call.args[0].name
        for call in engine._persist_event.call_args_list
        if call.args
    }
    assert "workflow.failed" in emitted or "playbook.failed" in emitted, (
        "Terminal failure events must be emitted when no recovery is in-flight"
    )

    # Engine returns empty commands list to stop further orchestration.
    assert commands == [], "Engine must return [] to halt orchestration on unrecovered failure"
