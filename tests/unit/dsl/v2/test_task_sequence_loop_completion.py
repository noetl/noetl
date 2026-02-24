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
