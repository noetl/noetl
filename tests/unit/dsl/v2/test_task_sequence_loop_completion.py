from pathlib import Path

import pytest
import yaml

import noetl.core.dsl.v2.engine as engine_module
from noetl.core.dsl.v2.engine import ControlFlowEngine, ExecutionState, PlaybookRepo, StateStore
from noetl.core.dsl.v2.models import Command, Event, Playbook, ToolCall


class FakeNATSCache:
    def __init__(self):
        self.increment_calls = []
        self.get_state_calls = []
        self.set_state_calls = []

    async def increment_loop_completed(self, execution_id, step_name, event_id=None):
        self.increment_calls.append((execution_id, step_name, event_id))
        return 1

    async def get_loop_state(self, execution_id, step_name, event_id=None):
        self.get_state_calls.append((execution_id, step_name, event_id))
        return {
            "collection_size": 20,
            "completed_count": 1,
            "event_id": event_id,
        }

    async def set_loop_state(self, execution_id, step_name, state, event_id=None):
        self.set_state_calls.append((execution_id, step_name, state, event_id))
        return True


class EventAwareNATSCache(FakeNATSCache):
    def __init__(self, execution_id):
        super().__init__()
        self.exec_event_id = f"exec_{execution_id}"

    async def increment_loop_completed(self, execution_id, step_name, event_id=None):
        self.increment_calls.append((execution_id, step_name, event_id))
        if event_id == self.exec_event_id:
            return 6
        return -1

    async def get_loop_state(self, execution_id, step_name, event_id=None):
        self.get_state_calls.append((execution_id, step_name, event_id))
        if event_id == self.exec_event_id:
            return {
                "collection_size": 220,
                "completed_count": 6,
                "event_id": event_id,
            }
        return None


@pytest.mark.asyncio
async def test_task_sequence_loop_uses_nats_collection_size_when_local_collection_missing(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/"
        "traveler_batch_enrichment_in_step.yaml"
    )
    playbook = Playbook(**yaml.safe_load(fixture.read_text(encoding="utf-8")))

    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9001"
    parent_step = "run_batch_workers"
    state = ExecutionState(execution_id, playbook, payload={})
    state.loop_state[parent_step] = {
        "collection": [],
        "iterator": "batch",
        "index": 0,
        "mode": "sequential",
        "completed": False,
        "results": [],
        "failed_count": 0,
        "aggregation_finalized": False,
        "event_id": None,
    }
    await state_store.save_state(state)

    fake_cache = FakeNATSCache()

    async def fake_get_nats_cache():
        return fake_cache

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)

    async def fake_create_command_for_step(_state, step_def, _args):
        return Command(
            execution_id=execution_id,
            step=step_def.step,
            tool=ToolCall(kind="playbook", config={}),
            args={},
            render_context={},
        )

    loop_done_eval = {"called": False}

    async def fake_evaluate_next_transitions(*_args, **_kwargs):
        loop_done_eval["called"] = True
        return []

    monkeypatch.setattr(engine, "_create_command_for_step", fake_create_command_for_step)
    monkeypatch.setattr(engine, "_evaluate_next_transitions", fake_evaluate_next_transitions)

    event = Event(
        execution_id=execution_id,
        step=f"{parent_step}:task_sequence",
        name="call.done",
        payload={
            "response": {
                "status": "completed",
                "results": {
                    "worker_result": {
                        "status": "completed",
                    }
                },
            }
        },
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert len(commands) == 1
    assert commands[0].step == parent_step
    assert loop_done_eval["called"] is False
    assert state.loop_state[parent_step]["completed"] is False
    assert state.loop_state[parent_step]["aggregation_finalized"] is False
    assert parent_step not in state.completed_steps
    assert fake_cache.increment_calls == [
        (execution_id, parent_step, f"exec_{execution_id}")
    ]
    assert fake_cache.get_state_calls == [
        (execution_id, parent_step, f"exec_{execution_id}")
    ]
    assert fake_cache.set_state_calls == []


@pytest.mark.asyncio
async def test_task_sequence_loop_prefers_execution_loop_key_when_step_event_id_present(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/"
        "traveler_batch_enrichment_in_step.yaml"
    )
    playbook = Playbook(**yaml.safe_load(fixture.read_text(encoding="utf-8")))

    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9010"
    parent_step = "run_batch_workers"
    state = ExecutionState(execution_id, playbook, payload={})
    state.loop_state[parent_step] = {
        "collection": [],
        "iterator": "batch",
        "index": 0,
        "mode": "sequential",
        "completed": False,
        "results": [],
        "failed_count": 0,
        "aggregation_finalized": False,
        "event_id": None,
    }
    # Simulate reconstructed state that only has latest persisted event id.
    state.step_event_ids[parent_step] = 569999999999999999
    await state_store.save_state(state)

    fake_cache = EventAwareNATSCache(execution_id)

    async def fake_get_nats_cache():
        return fake_cache

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)

    async def fake_create_command_for_step(_state, step_def, _args):
        return Command(
            execution_id=execution_id,
            step=step_def.step,
            tool=ToolCall(kind="playbook", config={}),
            args={},
            render_context={},
        )

    loop_done_eval = {"called": False}

    async def fake_evaluate_next_transitions(*_args, **_kwargs):
        loop_done_eval["called"] = True
        return []

    monkeypatch.setattr(engine, "_create_command_for_step", fake_create_command_for_step)
    monkeypatch.setattr(engine, "_evaluate_next_transitions", fake_evaluate_next_transitions)

    event = Event(
        execution_id=execution_id,
        step=f"{parent_step}:task_sequence",
        name="call.done",
        payload={
            "response": {
                "status": "completed",
                "results": {
                    "worker_result": {
                        "status": "completed",
                    }
                },
            }
        },
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert len(commands) == 1
    assert commands[0].step == parent_step
    assert loop_done_eval["called"] is False
    assert state.loop_state[parent_step]["completed"] is False
    assert state.loop_state[parent_step]["aggregation_finalized"] is False
    assert state.loop_state[parent_step]["event_id"] == f"exec_{execution_id}"
    assert fake_cache.increment_calls[0] == (execution_id, parent_step, f"exec_{execution_id}")
    assert fake_cache.get_state_calls[0] == (execution_id, parent_step, f"exec_{execution_id}")


def test_normalize_loop_collection_does_not_split_unresolved_template():
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    normalized = engine._normalize_loop_collection("{{ missing.collection }}", "test_step")

    assert normalized == []


@pytest.mark.asyncio
async def test_task_sequence_step_exit_is_ignored_for_completion():
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/"
        "traveler_batch_enrichment_in_step.yaml"
    )
    playbook = Playbook(**yaml.safe_load(fixture.read_text(encoding="utf-8")))
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9012"
    state = ExecutionState(execution_id, playbook, payload={})
    await state_store.save_state(state)

    event = Event(
        execution_id=execution_id,
        step="run_batch_workers:task_sequence",
        name="step.exit",
        payload={"result": {"status": "completed"}},
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert commands == []
    assert state.completed is False
    assert "run_batch_workers:task_sequence" not in state.completed_steps


@pytest.mark.asyncio
async def test_state_replay_unwraps_step_exit_result_and_skips_task_sequence_completion(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step/"
        "heavy_payload_pipeline_in_step.yaml"
    )
    playbook = Playbook(**yaml.safe_load(fixture.read_text(encoding="utf-8")))
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)

    async def fake_load_playbook_by_id(_catalog_id):
        return playbook

    monkeypatch.setattr(playbook_repo, "load_playbook_by_id", fake_load_playbook_by_id)

    class FakeCursor:
        def __init__(self):
            self.last_query = ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, _params):
            self.last_query = query

        async def fetchone(self):
            # Initial query in load_state() for catalog/workload bootstrap.
            return {
                "catalog_id": "cat-1",
                "result": {"workload": {"seed_rows": 220, "execution_mode": "direct_stress"}},
            }

        async def fetchall(self):
            # Event replay query in load_state().
            return [
                {
                    "node_name": "load_items_for_execution",
                    "event_type": "step.exit",
                    "result": {
                        "kind": "data",
                        "data": {
                            "result": {
                                "command_0": {
                                    "rows": [{"item_id": 1, "item_key": "Item-1"}],
                                    "row_count": 1,
                                }
                            },
                            "status": "completed",
                        },
                    },
                },
                {
                    "node_name": "run_direct_stress:task_sequence",
                    "event_type": "command.issued",
                    "result": None,
                },
                {
                    "node_name": "run_direct_stress:task_sequence",
                    "event_type": "command.completed",
                    "result": None,
                },
                {
                    "node_name": "run_direct_stress:task_sequence",
                    "event_type": "step.exit",
                    "result": {
                        "kind": "data",
                        "data": {
                            "result": {
                                "_prev_item_id": 1,
                            },
                            "status": "completed",
                        },
                    },
                },
            ]

    class FakeConnection:
        def cursor(self, row_factory=None):  # noqa: ARG002
            return FakeCursor()

    class FakeConnectionContext:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(engine_module, "get_pool_connection", lambda: FakeConnectionContext())

    state = await state_store.load_state("9011")

    assert state is not None
    assert "load_items_for_execution" in state.step_results
    assert state.step_results["load_items_for_execution"]["command_0"]["rows"][0]["item_id"] == 1
    assert "run_direct_stress:task_sequence" not in state.completed_steps


@pytest.mark.asyncio
async def test_terminal_events_emit_when_pending_key_is_task_sequence_suffix(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step/"
        "heavy_payload_pipeline_in_step.yaml"
    )
    playbook = Playbook(**yaml.safe_load(fixture.read_text(encoding="utf-8")))
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9013"
    state = ExecutionState(execution_id, playbook, payload={})
    # Simulate legacy/stale pending tracking where issued task_sequence key
    # survives after parent loop step completion.
    state.issued_steps.add("run_direct_stress:task_sequence")
    state.completed_steps.add("run_direct_stress")
    await state_store.save_state(state)

    persisted_events = []

    async def fake_persist_event(event, state_obj):
        persisted_events.append(event.name)
        state_obj.last_event_id = (state_obj.last_event_id or 0) + 1

    monkeypatch.setattr(engine, "_persist_event", fake_persist_event)

    event = Event(
        execution_id=execution_id,
        step="end",
        name="step.exit",
        payload={"status": "COMPLETED", "result": {"status": "completed"}},
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert commands == []
    assert state.completed is True
    assert persisted_events == ["workflow.completed", "playbook.completed"]


@pytest.mark.asyncio
async def test_command_failed_emits_terminal_failure_events(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step/"
        "heavy_payload_pipeline_in_step.yaml"
    )
    playbook = Playbook(**yaml.safe_load(fixture.read_text(encoding="utf-8")))
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9014"
    state = ExecutionState(execution_id, playbook, payload={})
    # Keep pending-check in-memory to avoid DB fallback in unit test.
    state.issued_steps.add("run_direct_stress")
    state.completed_steps.add("run_direct_stress")
    await state_store.save_state(state)

    persisted_events = []

    async def fake_persist_event(event, state_obj):
        persisted_events.append(event.name)
        state_obj.last_event_id = (state_obj.last_event_id or 0) + 1

    monkeypatch.setattr(engine, "_persist_event", fake_persist_event)

    event = Event(
        execution_id=execution_id,
        step="run_direct_stress:task_sequence",
        name="command.failed",
        payload={"status": "FAILED", "error": {"message": "forced failure"}},
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert commands == []
    assert state.failed is True
    assert state.completed is True
    assert persisted_events == ["workflow.failed", "playbook.failed"]
