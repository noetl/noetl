from pathlib import Path

import pytest
import yaml

import noetl.core.dsl.v2.engine as engine_module
from noetl.core.dsl.v2.engine import ControlFlowEngine, ExecutionState, PlaybookRepo, StateStore


class ClaimingNATSCache:
    def __init__(self):
        self._state = {}

    def _key(self, execution_id, step_name, event_id):
        return (str(execution_id), str(step_name), str(event_id) if event_id is not None else None)

    async def get_loop_state(self, execution_id, step_name, event_id=None):
        return self._state.get(self._key(execution_id, step_name, event_id))

    async def set_loop_state(self, execution_id, step_name, state, event_id=None):
        payload = dict(state)
        payload.setdefault("completed_count", 0)
        payload.setdefault("scheduled_count", payload.get("completed_count", 0))
        self._state[self._key(execution_id, step_name, event_id)] = payload
        return True

    async def claim_next_loop_index(
        self,
        execution_id,
        step_name,
        collection_size,
        max_in_flight,
        event_id=None,
    ):
        key = self._key(execution_id, step_name, event_id)
        state = self._state.get(key)
        if not state:
            return None

        completed_count = int(state.get("completed_count", 0) or 0)
        scheduled_count = int(state.get("scheduled_count", completed_count) or completed_count)

        if scheduled_count >= int(collection_size):
            return None

        in_flight = max(0, scheduled_count - completed_count)
        if in_flight >= int(max_in_flight):
            return None

        claim_index = scheduled_count
        state["scheduled_count"] = scheduled_count + 1
        state["collection_size"] = int(collection_size)
        self._state[key] = state
        return claim_index


@pytest.mark.asyncio
async def test_parallel_loop_issues_up_to_max_in_flight(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))

    # Keep this test focused on loop scheduling behavior.
    run_batch_workers = next(
        step for step in playbook["workflow"] if step.get("step") == "run_batch_workers"
    )
    run_batch_workers["args"] = {
        "claimed_batch": "{{ iter.batch.batch_number }}",
        "claimed_index": "{{ loop_index }}",
    }

    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9301"
    payload = {
        "build_batch_plan": {
            "batches": [
                {"batch_number": 1, "offset": 0, "limit": 40},
                {"batch_number": 2, "offset": 40, "limit": 40},
                {"batch_number": 3, "offset": 80, "limit": 40},
                {"batch_number": 4, "offset": 120, "limit": 40},
            ]
        }
    }
    state = ExecutionState(execution_id, parsed_playbook, payload=payload)

    fake_cache = ClaimingNATSCache()

    async def fake_get_nats_cache():
        return fake_cache

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)

    step_def = state.get_step("run_batch_workers")
    commands = await engine._issue_loop_commands(state, step_def, {})

    assert len(commands) == 3  # loop.spec.max_in_flight
    assert [cmd.args.get("claimed_batch") for cmd in commands] == [1, 2, 3]
    assert [cmd.args.get("claimed_index") for cmd in commands] == [0, 1, 2]

    # The 4th command should not be claimable until one in-flight iteration completes.
    no_slot_command = await engine._create_command_for_step(state, step_def, {})
    assert no_slot_command is None
