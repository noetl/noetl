from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
import yaml

import noetl.core.dsl.v2.engine as engine_module
from noetl.core.dsl.v2.engine import ControlFlowEngine, ExecutionState, PlaybookRepo, StateStore
from noetl.core.dsl.v2.models import Event


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


class RepairingNATSCache:
    def __init__(self, initial_state):
        self.state = dict(initial_state)
        self.set_calls = []

    async def get_loop_state(self, _execution_id, _step_name, event_id=None):
        payload = dict(self.state)
        payload.setdefault("event_id", event_id)
        return payload

    async def set_loop_state(self, _execution_id, _step_name, state, event_id=None):
        payload = dict(state)
        payload.setdefault("completed_count", 0)
        payload.setdefault("scheduled_count", payload.get("completed_count", 0))
        payload.setdefault("event_id", event_id)
        self.state = payload
        self.set_calls.append(dict(payload))
        return True

    async def claim_next_loop_index(
        self,
        _execution_id,
        _step_name,
        collection_size,
        max_in_flight,
        event_id=None,
    ):
        completed_count = int(self.state.get("completed_count", 0) or 0)
        scheduled_count = int(self.state.get("scheduled_count", completed_count) or completed_count)
        effective_size = int(collection_size or 0)
        if effective_size <= 0:
            effective_size = int(self.state.get("collection_size", 0) or 0)
        if effective_size <= 0:
            return None
        if scheduled_count >= effective_size:
            return None
        in_flight = max(0, scheduled_count - completed_count)
        if in_flight >= int(max_in_flight):
            return None

        claim_index = scheduled_count
        self.state["scheduled_count"] = scheduled_count + 1
        self.state["collection_size"] = effective_size
        self.state["event_id"] = event_id
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


@pytest.mark.asyncio
async def test_transition_into_loop_step_issues_commands_without_name_error(monkeypatch):
    playbook = {
        "apiVersion": "noetl.io/v2",
        "kind": "Playbook",
        "metadata": {"name": "transition_loop_test"},
        "workflow": [
            {
                "step": "start",
                "tool": {"kind": "python", "code": "def main(**kwargs): return {'ok': True}"},
                "next": [{"step": "loop_step"}],
            },
            {
                "step": "loop_step",
                "tool": {"kind": "python", "code": "def main(**kwargs): return kwargs"},
                "loop": {
                    "in": "{{ items }}",
                    "iterator": "item",
                    "spec": {"max_in_flight": 2},
                },
                "args": {
                    "value": "{{ item.value }}",
                    "index": "{{ loop_index }}",
                },
            },
        ],
    }

    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState(
        "9303",
        parsed_playbook,
        payload={"items": [{"value": 10}, {"value": 20}, {"value": 30}]},
    )
    await state_store.save_state(state)

    fake_cache = ClaimingNATSCache()

    async def fake_get_nats_cache():
        return fake_cache

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)

    event = Event(
        execution_id="9303",
        step="start",
        name="call.done",
        payload={"response": {"ok": True}},
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert len(commands) == 1
    assert all(command.step == "loop_step" for command in commands)
    assert [command.args.get("value") for command in commands] == [10]
    assert [command.args.get("index") for command in commands] == [0]


@pytest.mark.asyncio
async def test_loop_continue_reuses_cached_collection_when_ctx_key_missing(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))

    run_batch_workers = next(
        step for step in playbook["workflow"] if step.get("step") == "run_batch_workers"
    )
    run_batch_workers["loop"]["in"] = "{{ ctx.patients_needing_demographics }}"
    run_batch_workers["args"] = {
        "claimed_patient_id": "{{ iter.batch.patient_id }}",
        "claimed_index": "{{ loop_index }}",
    }

    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9302"
    source_patients = [
        {"patient_id": 101},
        {"patient_id": 102},
    ]
    state = ExecutionState(
        execution_id,
        parsed_playbook,
        payload={
            "ctx": {
                "patients_needing_demographics": source_patients
            }
        },
    )
    state.last_event_id = 9302001

    fake_cache = ClaimingNATSCache()

    async def fake_get_nats_cache():
        return fake_cache

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)

    step_def = state.get_step("run_batch_workers")

    first = await engine._create_command_for_step(state, step_def, {})
    assert first is not None
    assert first.args.get("claimed_patient_id") == 101
    assert first.args.get("claimed_index") == 0

    # Simulate in-place mutation of original source list after loop init.
    source_patients.clear()
    source_patients.append({"patient_id": 999})

    # Also remove ctx key; continuation must still use cached snapshot.
    state.variables.pop("patients_needing_demographics", None)

    second = await engine._create_command_for_step(
        state,
        step_def,
        {"__loop_continue": True},
    )
    assert second is not None
    assert second.args.get("claimed_patient_id") == 102
    assert second.args.get("claimed_index") == 1


@pytest.mark.asyncio
async def test_loop_claim_repairs_zero_collection_size_metadata(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
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
    state = ExecutionState(
        "9402",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [
                    {"batch_number": 1},
                    {"batch_number": 2},
                    {"batch_number": 3},
                ]
            }
        },
    )

    fake_cache = RepairingNATSCache(
        {
            "collection_size": 0,
            "completed_count": 0,
            "scheduled_count": 0,
        }
    )

    async def fake_get_nats_cache():
        return fake_cache

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)

    step_def = state.get_step("run_batch_workers")
    command = await engine._create_command_for_step(state, step_def, {})

    assert command is not None
    assert command.args.get("claimed_batch") == 1
    assert command.args.get("claimed_index") == 0
    assert int(fake_cache.state.get("collection_size", 0)) == 3


@pytest.mark.asyncio
async def test_loop_continue_rerenders_when_replayed_cached_collection_is_empty(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
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
    state = ExecutionState(
        "94025",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [
                    {"batch_number": 1},
                    {"batch_number": 2},
                    {"batch_number": 3},
                ]
            }
        },
    )
    state.loop_state["run_batch_workers"] = {
        "collection": [],
        "iterator": "batch",
        "index": 1,
        "mode": "parallel",
        "completed": False,
        "results": [],
        "failed_count": 0,
        "scheduled_count": 1,
        "aggregation_finalized": False,
        "event_id": "exec_94025",
    }

    fake_cache = RepairingNATSCache(
        {
            "collection_size": 3,
            "completed_count": 1,
            "scheduled_count": 1,
            "event_id": "exec_94025",
        }
    )

    async def fake_get_nats_cache():
        return fake_cache

    render_calls = {"count": 0}
    original_render = engine._render_template

    def tracked_render(template, context):
        render_calls["count"] += 1
        return original_render(template, context)

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_render_template", tracked_render)

    step_def = state.get_step("run_batch_workers")
    command = await engine._create_command_for_step(
        state,
        step_def,
        {"__loop_continue": True},
    )

    assert command is not None
    assert render_calls["count"] >= 1
    assert command.args.get("claimed_batch") == 2
    assert command.args.get("claimed_index") == 1
    assert len(state.loop_state["run_batch_workers"]["collection"]) == 3


@pytest.mark.asyncio
async def test_loop_watchdog_recovers_stalled_scheduled_counts(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
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
    state = ExecutionState(
        "9403",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [
                    {"batch_number": 1},
                    {"batch_number": 2},
                    {"batch_number": 3},
                    {"batch_number": 4},
                ]
            }
        },
    )

    stale_progress_at = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    fake_cache = RepairingNATSCache(
        {
            "collection_size": 4,
            "completed_count": 1,
            "scheduled_count": 4,
            "last_progress_at": stale_progress_at,
        }
    )

    async def fake_get_nats_cache():
        return fake_cache

    async def fake_find_orphaned(*_args, **_kwargs):
        return [1]

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_find_orphaned_loop_iteration_indices", fake_find_orphaned)
    monkeypatch.setattr(engine_module, "_LOOP_STALL_WATCHDOG_SECONDS", 1.0)
    monkeypatch.setattr(engine_module, "_LOOP_STALL_RECOVERY_COOLDOWN_SECONDS", 0.0)

    step_def = state.get_step("run_batch_workers")
    command = await engine._create_command_for_step(state, step_def, {})

    assert command is not None
    assert command.args.get("claimed_batch") == 2
    assert command.args.get("claimed_index") == 1
    assert int(fake_cache.state.get("scheduled_count", 0)) == 4
    assert int(state.loop_state["run_batch_workers"].get("watchdog_repair_count", 0)) >= 1
