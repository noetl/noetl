"""
Tests for NoETL DSL Engine Control Flow
"""

import pytest
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from noetl.core.dsl.engine.executor import ControlFlowEngine, PlaybookRepo, StateStore, ExecutionState
from noetl.core.dsl.engine.models import Event, Command, Playbook
from noetl.core.dsl.engine.parser import DSLParser


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
def engine_setup(monkeypatch):
    """Set up engine components."""
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)
    return engine, playbook_repo, state_store


def _make_minimal_playbook(name: str = "test") -> Playbook:
    """Return a minimal engine playbook with a single step that has a call.error recovery arc."""
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
      spec:
        mode: exclusive
      arcs:
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


@pytest.mark.asyncio
async def test_conditional_transition_with_set_and_input(engine_setup, monkeypatch):
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
    state = ExecutionState(
        execution_id = "1000",
        playbook=playbook,
        payload={},
    )
    monkeypatch.setattr(state_store, "load_state", AsyncMock(return_value=state))
    monkeypatch.setattr(state_store, "load_state_for_update", AsyncMock(return_value=state))
    await state_store.save_state(state)
    engine._persist_event = AsyncMock(return_value=None)

    # call.done event
    event = Event(
        execution_id = "1000",
        step="start",
        name="call.done",
        payload={
            "result": {
                "data": {
                    "status": 200,
                    "data": [1, 2, 3],
                }
            }
        }
    )

    commands = await engine.handle_event(event, already_persisted=True)
    assert len(commands) == 1
    assert commands[0].step == "process"


@pytest.mark.asyncio
async def test_first_persisted_duplicate_call_done_still_orchestrates(engine_setup, monkeypatch):
    """Async batch ingestion may persist duplicates before orchestration; the earliest copy must still drive routing."""
    engine, playbook_repo, state_store = engine_setup

    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: duplicate_call_done_first_wins

workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {'ok': True}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: end
          when: "{{ event.name == 'call.done' }}"

  - step: end
    tool:
      kind: python
      code: "def main(): return {'done': True}"
"""

    playbook = DSLParser().parse(yaml_content)
    state = ExecutionState(
        execution_id = "200000000000009991",
        playbook=playbook,
        payload={},
    )
    monkeypatch.setattr(state_store, "load_state", AsyncMock(return_value=state))
    monkeypatch.setattr(state_store, "load_state_for_update", AsyncMock(return_value=state))
    monkeypatch.setattr(state_store, "save_state", AsyncMock(return_value=None))
    engine._persist_event = AsyncMock(return_value=None)
    monkeypatch.setattr(engine, "_count_persisted_command_events", AsyncMock(return_value=2))
    monkeypatch.setattr(engine, "_is_first_persisted_command_event", AsyncMock(return_value=True))

    event = Event(
        execution_id = "200000000000009991",
        step="start",
        name="call.done",
        payload={"result": {"data": {"ok": True}}},
        meta={
            "command_id": "200000000000009991:start:cmd-1",
            "persisted_event_id": "1001",
        },
    )

    commands = await engine.handle_event(event, already_persisted=True)
    assert len(commands) == 1
    assert commands[0].step == "end"


@pytest.mark.asyncio
async def test_command_failed_with_pending_recovery_does_not_terminate(engine_setup, monkeypatch):
    """
    When command.failed arrives while recovery commands are in-flight (issued via a
    call.error arc), the engine must NOT emit workflow.failed/playbook.failed and must
    NOT mark the execution as completed.
    """
    engine, playbook_repo, state_store = engine_setup
    playbook = _make_minimal_playbook("recovery_test")

    state = ExecutionState(
        execution_id = "1001",
        playbook=playbook,
        payload={},
    )
    state.issued_steps.add("recovery_step")
    state.failed = True

    monkeypatch.setattr(state_store, "load_state", AsyncMock(return_value=state))
    monkeypatch.setattr(state_store, "load_state_for_update", AsyncMock(return_value=state))
    await state_store.save_state(state)
    engine._persist_event = AsyncMock(return_value=None)

    event = Event(
        execution_id = "1001",
        step="fetch_data",
        name="command.failed",
        payload={"error": {"message": "infra retry exhausted"}},
    )

    commands = await engine.handle_event(event, already_persisted=True)
    reloaded = await state_store.load_state("1001")
    assert reloaded.completed is False


@pytest.mark.asyncio
async def test_command_failed_without_pending_commands_terminates(engine_setup, monkeypatch):
    """
    When command.failed arrives and there are NO pending recovery commands, the
    engine must emit terminal failure events and stop the execution.
    """
    engine, playbook_repo, state_store = engine_setup
    playbook = _make_minimal_playbook("no_recovery_test")

    state = ExecutionState(
        execution_id = "200000000000000001",
        playbook=playbook,
        payload={},
    )
    assert not state.issued_steps

    monkeypatch.setattr(state_store, "load_state", AsyncMock(return_value=state))
    monkeypatch.setattr(state_store, "load_state_for_update", AsyncMock(return_value=state))
    await state_store.save_state(state)
    engine._persist_event = AsyncMock(return_value=None)

    event = Event(
        execution_id = "200000000000000001",
        step="fetch_data",
        name="command.failed",
        payload={"error": {"message": "infra retry exhausted"}},
    )

    # Patch DB check for pending count
    @asynccontextmanager
    async def _mock_zero_pending():
        cur = AsyncMock()
        cur.fetchone = AsyncMock(return_value={"pending_count": 0})
        conn = AsyncMock()
        conn.cursor = MagicMock(return_value=cur)
        yield conn

    monkeypatch.setattr("noetl.core.dsl.engine.executor.events.get_pool_connection", _mock_zero_pending)

    commands = await engine.handle_event(event, already_persisted=True)
    emitted = {call.args[0].name for call in engine._persist_event.call_args_list if call.args}
    assert "workflow.failed" in emitted or "playbook.failed" in emitted
    assert commands == []


@pytest.mark.asyncio
async def test_step_exit_structural_next_does_not_duplicate_pending_step(engine_setup, monkeypatch):
    """A later step.exit must not re-issue an exclusive next step already launched by call.done."""
    engine, playbook_repo, state_store = engine_setup

    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: no_duplicate_structural_next

workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: next_step

  - step: next_step
    tool:
      kind: python
      code: "def main(): return {}"
"""

    playbook = DSLParser().parse(yaml_content)
    state = ExecutionState(
        execution_id = "1002",
        playbook=playbook,
        payload={},
    )
    monkeypatch.setattr(state_store, "load_state", AsyncMock(return_value=state))
    monkeypatch.setattr(state_store, "load_state_for_update", AsyncMock(return_value=state))
    await state_store.save_state(state)
    engine._persist_event = AsyncMock(return_value=None)

    call_done = Event(
        execution_id = "1002",
        step="start",
        name="call.done",
        payload={"result": {"ok": True}},
    )
    first_commands = await engine.handle_event(call_done, already_persisted=True)
    assert [cmd.step for cmd in first_commands] == ["next_step"]

    step_exit = Event(
        execution_id = "1002",
        step="start",
        name="step.exit",
        payload={"status": "COMPLETED", "result": {"ok": True}},
    )
    second_commands = await engine.handle_event(step_exit, already_persisted=True)
    assert second_commands == []


@pytest.mark.asyncio
async def test_state_load_from_jsonb(engine_setup, monkeypatch):
    """Execution state must be successfully loaded from Postgres JSONB state column."""
    engine, playbook_repo, state_store = engine_setup

    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: jsonb_load_test

workflow:
  - step: claim_rows
    tool:
      kind: python
      code: "def main(): return {}"
"""

    playbook = DSLParser().parse(yaml_content)
    async def _load_playbook_by_id(_catalog_id, *args, **kwargs): return playbook
    playbook_repo.load_playbook_by_id = _load_playbook_by_id

    # Create a state and serialize it
    original_state = ExecutionState(
        execution_id = "200000000000000777",
        playbook=playbook,
        payload={},
        catalog_id=101
    )
    original_state.step_results["claim_rows"] = {"rows": [{"id": 7}]}
    state_dict = original_state.to_dict()

    class _ReplayCursor:
        def __init__(self): self.query = ""
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def execute(self, query, params=None): self.query = query
        async def fetchone(self):
            if "noetl.execution" in self.query: 
                return {"state": state_dict, "catalog_id": 101}
            return None

    class _ReplayConn:
        def cursor(self, *args, **kwargs): return _ReplayCursor()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False

    @asynccontextmanager
    async def _mock_replay_connection(): yield _ReplayConn()

    monkeypatch.setattr("noetl.core.dsl.engine.executor.store.get_pool_connection", _mock_replay_connection)

    execution_id = "200000000000000777"
    state = await state_store.load_state(execution_id)

    assert state is not None
    assert state.step_results["claim_rows"]["rows"] == [{"id": 7}]
    
    context = state.get_render_context(Event(execution_id=execution_id, step="process_rows", name="loop_init"))
    assert context["claim_rows"]["rows"] == [{"id": 7}]
