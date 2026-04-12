from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
import yaml

import noetl.core.dsl.engine.engine as engine_module
from noetl.core.dsl.engine.engine import ControlFlowEngine, ExecutionState, PlaybookRepo, StateStore
from noetl.core.dsl.engine.models import Event


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

    async def count_observed_loop_iteration_terminals(
        self,
        _execution_id,
        _step_name,
        *,
        event_id=None,
    ):
        return int(self.state.get("observed_terminal_count", -1))

    async def find_supervisor_missing_loop_iteration_indices(
        self,
        _execution_id,
        _step_name,
        *,
        event_id=None,
        limit=10,
        min_age_seconds=0.0,
    ):
        indexes = self.state.get("supervisor_missing_indexes")
        if indexes is None:
            return None
        return list(indexes)[:limit]

    async def find_supervisor_orphaned_loop_iteration_indices(
        self,
        _execution_id,
        _step_name,
        *,
        event_id=None,
        limit=10,
    ):
        indexes = self.state.get("supervisor_orphaned_indexes")
        if indexes is None:
            return None
        return list(indexes)[:limit]


class RecordingCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.query = ""
        self.params = tuple()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, query, params):
        self.query = query
        self.params = tuple(params)

    async def fetchall(self):
        return list(self.rows)


class RecordingConn:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def cursor(self, row_factory=None):
        return self._cursor


class RecordingPoolContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


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
    run_batch_workers["input"] = {
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
    assert [cmd.input.get("claimed_batch") for cmd in commands] == [1, 2, 3]
    assert [cmd.input.get("claimed_index") for cmd in commands] == [0, 1, 2]

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
    assert [command.input.get("value") for command in commands] == [10]
    assert [command.input.get("index") for command in commands] == [0]


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
    run_batch_workers["input"] = {
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
    assert first.input.get("claimed_patient_id") == 101
    assert first.input.get("claimed_index") == 0

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
    assert second.input.get("claimed_patient_id") == 102
    assert second.input.get("claimed_index") == 1


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
    run_batch_workers["input"] = {
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
    assert command.input.get("claimed_batch") == 1
    assert command.input.get("claimed_index") == 0
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
    run_batch_workers["input"] = {
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
    assert command.input.get("claimed_batch") == 2
    assert command.input.get("claimed_index") == 1
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
    run_batch_workers["input"] = {
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
    assert command.input.get("claimed_batch") == 2
    assert command.input.get("claimed_index") == 1
    assert int(fake_cache.state.get("scheduled_count", 0)) == 4
    assert int(state.loop_state["run_batch_workers"].get("watchdog_repair_count", 0)) >= 1


@pytest.mark.asyncio
async def test_loop_watchdog_recovers_stale_inflight_saturation(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    run_batch_workers = next(
        step for step in playbook["workflow"] if step.get("step") == "run_batch_workers"
    )
    run_batch_workers["input"] = {
        "claimed_batch": "{{ iter.batch.batch_number }}",
        "claimed_index": "{{ loop_index }}",
    }

    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)
    state = ExecutionState(
        "9403b",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [
                    {"batch_number": 1},
                    {"batch_number": 2},
                    {"batch_number": 3},
                    {"batch_number": 4},
                    {"batch_number": 5},
                    {"batch_number": 6},
                ]
            }
        },
    )

    stale_progress_at = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    fake_cache = RepairingNATSCache(
        {
            "collection_size": 6,
            "completed_count": 2,
            "scheduled_count": 5,
            "last_progress_at": stale_progress_at,
        }
    )

    async def fake_get_nats_cache():
        return fake_cache

    async def fake_find_orphaned(*_args, **_kwargs):
        return [3]

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_find_orphaned_loop_iteration_indices", fake_find_orphaned)
    monkeypatch.setattr(engine_module, "_LOOP_STALL_WATCHDOG_SECONDS", 1.0)
    monkeypatch.setattr(engine_module, "_LOOP_STALL_RECOVERY_COOLDOWN_SECONDS", 0.0)

    step_def = state.get_step("run_batch_workers")
    step_def.loop.spec.max_in_flight = 3
    command = await engine._create_command_for_step(state, step_def, {})

    assert command is not None
    assert command.input.get("claimed_batch") == 4
    assert command.input.get("claimed_index") == 3
    assert int(fake_cache.state.get("scheduled_count", 0)) == 5
    assert int(state.loop_state["run_batch_workers"].get("watchdog_repair_count", 0)) >= 1


@pytest.mark.asyncio
async def test_loop_counter_reconcile_recovers_no_slot_without_watchdog(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    run_batch_workers = next(
        step for step in playbook["workflow"] if step.get("step") == "run_batch_workers"
    )
    run_batch_workers["input"] = {
        "claimed_batch": "{{ iter.batch.batch_number }}",
        "claimed_index": "{{ loop_index }}",
    }

    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)
    state = ExecutionState(
        "9403c",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [
                    {"batch_number": 1},
                    {"batch_number": 2},
                    {"batch_number": 3},
                    {"batch_number": 4},
                    {"batch_number": 5},
                    {"batch_number": 6},
                ]
            }
        },
    )

    recent_progress_at = datetime.now(timezone.utc).isoformat()
    fake_cache = RepairingNATSCache(
        {
            "collection_size": 6,
            "completed_count": 2,
            "scheduled_count": 5,
            "last_progress_at": recent_progress_at,
        }
    )

    async def fake_get_nats_cache():
        return fake_cache

    async def fake_find_missing(*_args, **_kwargs):
        return []

    async def fake_count_epoch_terminals(*_args, **_kwargs):
        return 4

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_find_missing_loop_iteration_indices", fake_find_missing)
    monkeypatch.setattr(engine, "_count_loop_terminal_iterations", fake_count_epoch_terminals)
    monkeypatch.setattr(engine_module, "_LOOP_COUNTER_RECONCILE_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(engine_module, "_LOOP_STALL_WATCHDOG_SECONDS", 300.0)

    step_def = state.get_step("run_batch_workers")
    step_def.loop.spec.max_in_flight = 3
    command = await engine._create_command_for_step(state, step_def, {})

    assert command is not None
    assert command.input.get("claimed_batch") == 6
    assert command.input.get("claimed_index") == 5
    assert int(fake_cache.state.get("completed_count", 0)) == 4
    assert int(fake_cache.state.get("scheduled_count", 0)) == 6
    assert fake_cache.state.get("last_counter_reconcile_at")


@pytest.mark.asyncio
async def test_loop_counter_reconcile_uses_epoch_terminal_count_for_ghost_inflight(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    run_batch_workers = next(
        step for step in playbook["workflow"] if step.get("step") == "run_batch_workers"
    )
    run_batch_workers["input"] = {
        "claimed_batch": "{{ iter.batch.batch_number }}",
        "claimed_index": "{{ loop_index }}",
    }

    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)
    state = ExecutionState(
        "9403d",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [{"batch_number": i} for i in range(1, 21)]
            }
        },
    )

    fake_cache = RepairingNATSCache(
        {
            "collection_size": 20,
            "completed_count": 2,
            "scheduled_count": 7,
            "event_id": "loop_9403d_epoch_2",
        }
    )

    async def fake_get_nats_cache():
        return fake_cache

    async def fake_find_missing(*_args, **_kwargs):
        return []

    async def fake_count_epoch_terminals(*_args, **_kwargs):
        return 7

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_find_missing_loop_iteration_indices", fake_find_missing)
    monkeypatch.setattr(engine, "_count_loop_terminal_iterations", fake_count_epoch_terminals)
    monkeypatch.setattr(engine_module, "_LOOP_COUNTER_RECONCILE_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(engine_module, "_LOOP_STALL_WATCHDOG_SECONDS", 300.0)

    step_def = state.get_step("run_batch_workers")
    step_def.loop.spec.max_in_flight = 5
    command = await engine._create_command_for_step(state, step_def, {})

    assert command is not None
    assert command.input.get("claimed_batch") == 8
    assert command.input.get("claimed_index") == 7
    assert int(fake_cache.state.get("completed_count", 0)) == 7
    assert int(fake_cache.state.get("scheduled_count", 0)) == 8
    assert fake_cache.state.get("last_counter_reconcile_at")


@pytest.mark.asyncio
async def test_loop_counter_reconcile_prefers_supervisor_terminal_count(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    run_batch_workers = next(
        step for step in playbook["workflow"] if step.get("step") == "run_batch_workers"
    )
    run_batch_workers["input"] = {
        "claimed_batch": "{{ iter.batch.batch_number }}",
        "claimed_index": "{{ loop_index }}",
    }

    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)
    state = ExecutionState(
        "9403e",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [{"batch_number": i} for i in range(1, 21)]
            }
        },
    )

    fake_cache = RepairingNATSCache(
        {
            "collection_size": 20,
            "completed_count": 2,
            "scheduled_count": 7,
            "event_id": "loop_9403e_epoch_2",
            "observed_terminal_count": 7,
        }
    )

    async def fake_get_nats_cache():
        return fake_cache

    async def fake_find_missing(*_args, **_kwargs):
        return []

    async def fake_count_epoch_terminals(*_args, **_kwargs):
        return -1

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_find_missing_loop_iteration_indices", fake_find_missing)
    monkeypatch.setattr(engine, "_count_loop_terminal_iterations", fake_count_epoch_terminals)
    monkeypatch.setattr(engine_module, "_LOOP_COUNTER_RECONCILE_COOLDOWN_SECONDS", 30.0)
    monkeypatch.setattr(engine_module, "_LOOP_STALL_WATCHDOG_SECONDS", 300.0)

    step_def = state.get_step("run_batch_workers")
    step_def.loop.spec.max_in_flight = 5
    command = await engine._create_command_for_step(state, step_def, {})

    assert command is not None
    assert command.input.get("claimed_batch") == 8
    assert command.input.get("claimed_index") == 7
    assert int(fake_cache.state.get("completed_count", 0)) == 7
    assert int(fake_cache.state.get("scheduled_count", 0)) == 8
    assert fake_cache.state.get("last_counter_reconcile_at")


@pytest.mark.asyncio
async def test_loop_watchdog_prefers_supervisor_orphaned_indexes(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    run_batch_workers = next(
        step for step in playbook["workflow"] if step.get("step") == "run_batch_workers"
    )
    run_batch_workers["input"] = {
        "claimed_batch": "{{ iter.batch.batch_number }}",
        "claimed_index": "{{ loop_index }}",
    }

    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)
    state = ExecutionState(
        "9403f",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [{"batch_number": i} for i in range(1, 7)]
            }
        },
    )

    stale_progress_at = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    fake_cache = RepairingNATSCache(
        {
            "collection_size": 6,
            "completed_count": 2,
            "scheduled_count": 5,
            "last_progress_at": stale_progress_at,
            "supervisor_orphaned_indexes": [3],
        }
    )

    async def fake_get_nats_cache():
        return fake_cache

    async def unexpected_orphaned_scan(*_args, **_kwargs):
        raise AssertionError("event-table orphaned scan should not run when supervisor state is available")

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_find_orphaned_loop_iteration_indices", unexpected_orphaned_scan)
    monkeypatch.setattr(engine_module, "_LOOP_STALL_WATCHDOG_SECONDS", 1.0)
    monkeypatch.setattr(engine_module, "_LOOP_STALL_RECOVERY_COOLDOWN_SECONDS", 0.0)

    step_def = state.get_step("run_batch_workers")
    step_def.loop.spec.max_in_flight = 3
    command = await engine._create_command_for_step(state, step_def, {})

    assert command is not None
    assert command.input.get("claimed_batch") == 4
    assert command.input.get("claimed_index") == 3


@pytest.mark.asyncio
async def test_find_missing_loop_iteration_indices_applies_age_gating(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    cursor = RecordingCursor(rows=[{"loop_iteration_index": 1}, {"loop_iteration_index": 4}])
    conn = RecordingConn(cursor)
    monkeypatch.setattr(engine_module, "get_pool_connection", lambda: RecordingPoolContext(conn))

    missing = await engine._find_missing_loop_iteration_indices(
        execution_id="9701",
        node_name="run_batch_workers",
        loop_event_id="loop_9701",
        limit=3,
        min_age_seconds=7.25,
    )

    assert missing == [1, 4]
    assert "event_type = 'command.started'" in cursor.query
    assert "result->'context'->>'command_id'" in cursor.query
    assert "'call.done'" in cursor.query
    assert "meta->>'loop_event_id' = %s" in cursor.query
    assert "s.command_id IS NULL" in cursor.query
    # issued(execution_id,node_name,loop_event_id) + started(execution_id,node_name)
    # + terminal(execution_id,node_name) + min_age + limit
    assert len(cursor.params) == 9
    assert cursor.params[2] == "loop_9701"
    assert cursor.params[3] == 9701
    assert cursor.params[5] == 9701
    assert cursor.params[-2] == 7.25
    assert cursor.params[-1] == 3


@pytest.mark.asyncio
async def test_find_missing_loop_iteration_indices_clamps_negative_age(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    cursor = RecordingCursor(rows=[])
    conn = RecordingConn(cursor)
    monkeypatch.setattr(engine_module, "get_pool_connection", lambda: RecordingPoolContext(conn))

    missing = await engine._find_missing_loop_iteration_indices(
        execution_id="9702",
        node_name="run_batch_workers",
        loop_event_id=None,
        limit=5,
        min_age_seconds=-10.0,
    )

    assert missing == []
    assert "result->'context'->>'command_id'" in cursor.query
    assert "'call.done'" in cursor.query
    # issued(execution_id,node_name) + started(execution_id,node_name)
    # + terminal(execution_id,node_name) + min_age + limit
    assert len(cursor.params) == 8
    assert cursor.params[2] == 9702
    assert cursor.params[4] == 9702
    assert cursor.params[-2] == 0.0
    assert cursor.params[-1] == 5


def test_extract_command_id_from_event_payload_supports_reference_only_shapes():
    assert (
        engine_module._extract_command_id_from_event_payload(
            {"command_id": "cmd-top-level"}
        )
        == "cmd-top-level"
    )
    assert (
        engine_module._extract_command_id_from_event_payload(
            {"response": {"context": {"command_id": "cmd-response-context"}}}
        )
        == "cmd-response-context"
    )
    assert (
        engine_module._extract_command_id_from_event_payload(
            {"result": {"context": {"command_id": "cmd-result-context"}}}
        )
        == "cmd-result-context"
    )
    assert engine_module._extract_command_id_from_event_payload({"response": {"status": "ok"}}) is None


@pytest.mark.asyncio
async def test_handle_event_skips_duplicate_persisted_call_done(monkeypatch):
    playbook = {
        "apiVersion": "noetl.io/v2",
        "kind": "Playbook",
        "metadata": {"name": "duplicate_call_done_guard"},
        "workflow": [
            {
                "step": "reset_http_probe_stats",
                "tool": {"kind": "python", "code": "def main(**kwargs): return {'ok': True}"},
                "next": [{"step": "end"}],
            },
            {
                "step": "end",
                "tool": {"kind": "python", "code": "def main(**kwargs): return {'ok': True}"},
            },
        ],
    }

    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState("9703", parsed_playbook, payload={})
    state.last_event_id = 1

    async def fake_load_state(_execution_id):
        return state

    async def fake_should_refresh(*_args, **_kwargs):
        return False

    async def fake_duplicate_count(*_args, **_kwargs):
        return 2

    async def should_not_route(*_args, **_kwargs):
        raise AssertionError("duplicate call.done should not trigger routing")

    monkeypatch.setattr(state_store, "load_state", fake_load_state)
    monkeypatch.setattr(state_store, "get_state", lambda _execution_id: state)
    monkeypatch.setattr(state_store, "should_refresh_cached_state", fake_should_refresh)
    monkeypatch.setattr(engine, "_count_persisted_command_events", fake_duplicate_count)
    monkeypatch.setattr(engine, "_evaluate_next_transitions", should_not_route)

    event = Event(
        execution_id="9703",
        step="reset_http_probe_stats:task_sequence",
        name="call.done",
        payload={
            "command_id": "9703:reset_http_probe_stats:task_sequence:cmd-1",
            "response": {"status": "COMPLETED"},
        },
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert commands == []


def test_restore_loop_collection_snapshot_when_replay_shrinks_collection():
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState(
        "9501",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [{"batch_number": i} for i in range(1, 21)]
            }
        },
    )
    state.loop_state["run_batch_workers"] = {
        "collection": [{"batch_number": 1}],
        "iterator": "batch",
        "index": 5,
        "mode": "parallel",
        "completed": False,
        "results": [{}, {}, {}],
        "failed_count": 0,
        "scheduled_count": 5,
        "aggregation_finalized": False,
        "event_id": "exec_9501",
        "omitted_results_count": 0,
    }

    snapshots = {
        "run_batch_workers": {
            "collection": [{"batch_number": i} for i in range(1, 21)],
            "event_id": "exec_9501",
            "iterator": "batch",
            "mode": "parallel",
        }
    }

    restored = engine._restore_loop_collection_snapshots(state, snapshots)

    assert restored == 1
    assert len(state.loop_state["run_batch_workers"]["collection"]) == 20


def test_restore_loop_collection_snapshot_skips_incompatible_event_ids():
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState(
        "9502",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [{"batch_number": i} for i in range(1, 6)]
            }
        },
    )
    state.loop_state["run_batch_workers"] = {
        "collection": [{"batch_number": 1}],
        "iterator": "batch",
        "index": 2,
        "mode": "parallel",
        "completed": False,
        "results": [{}],
        "failed_count": 0,
        "scheduled_count": 2,
        "aggregation_finalized": False,
        "event_id": "loop_new",
        "omitted_results_count": 0,
    }

    snapshots = {
        "run_batch_workers": {
            "collection": [{"batch_number": i} for i in range(1, 6)],
            "event_id": "loop_old",
            "iterator": "batch",
            "mode": "parallel",
        }
    }

    restored = engine._restore_loop_collection_snapshots(state, snapshots)

    assert restored == 0
    assert len(state.loop_state["run_batch_workers"]["collection"]) == 1


def test_loop_event_ids_compatible_does_not_treat_exec_as_wildcard():
    assert (
        ControlFlowEngine._loop_event_ids_compatible("exec_123", "exec_123")
        is True
    )
    assert (
        ControlFlowEngine._loop_event_ids_compatible("exec_123", "exec_456")
        is False
    )
    assert (
        ControlFlowEngine._loop_event_ids_compatible("exec_123", "loop_123")
        is False
    )
    assert (
        ControlFlowEngine._loop_event_ids_compatible("exec_123", "987654")
        is False
    )


def test_node_name_candidates_include_task_sequence_alias():
    assert engine_module._node_name_candidates("load_data") == (
        "load_data",
        "load_data:task_sequence",
    )
    assert engine_module._node_name_candidates("load_data:task_sequence") == (
        "load_data:task_sequence",
        "load_data",
    )


def test_restore_loop_collection_snapshot_skips_when_cached_smaller_than_required():
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState(
        "9503",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [{"batch_number": i} for i in range(1, 30)]
            }
        },
    )
    # completed_count = len(results) + omitted_results_count = 6
    state.loop_state["run_batch_workers"] = {
        "collection": [],
        "iterator": "batch",
        "index": 6,
        "mode": "parallel",
        "completed": False,
        "results": [{}, {}, {}],
        "failed_count": 0,
        "scheduled_count": 6,
        "aggregation_finalized": False,
        "event_id": "exec_9503",
        "omitted_results_count": 3,
    }

    snapshots = {
        "run_batch_workers": {
            "collection": [{"batch_number": i} for i in range(1, 4)],  # too small
            "event_id": "exec_9503",
            "iterator": "batch",
            "mode": "parallel",
        }
    }

    restored = engine._restore_loop_collection_snapshots(state, snapshots)

    assert restored == 0
    assert len(state.loop_state["run_batch_workers"]["collection"]) == 0


def test_snapshot_loop_collections_captures_progress_counts():
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState(
        "9504",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [{"batch_number": i} for i in range(1, 20)]
            }
        },
    )
    state.loop_state["run_batch_workers"] = {
        "collection": [{"batch_number": i} for i in range(1, 20)],
        "iterator": "batch",
        "index": 7,
        "mode": "parallel",
        "completed": False,
        "results": [{}, {}, {}, {}],
        "failed_count": 0,
        "scheduled_count": 9,
        "aggregation_finalized": False,
        "event_id": "exec_9504",
        "omitted_results_count": 3,
    }

    snapshots = engine._snapshot_loop_collections(state)
    snapshot = snapshots.get("run_batch_workers")

    assert snapshot is not None
    assert snapshot.get("completed_count") == 7
    assert snapshot.get("scheduled_count") == 9


def test_restore_loop_collection_snapshot_honors_snapshot_progress_counts():
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState(
        "9505",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [{"batch_number": i} for i in range(1, 30)]
            }
        },
    )
    state.loop_state["run_batch_workers"] = {
        "collection": [],
        "iterator": "batch",
        "index": 0,
        "mode": "parallel",
        "completed": False,
        "results": [],
        "failed_count": 0,
        "scheduled_count": 0,
        "aggregation_finalized": False,
        "event_id": "exec_9505",
        "omitted_results_count": 0,
    }

    snapshots = {
        "run_batch_workers": {
            "collection": [{"batch_number": i} for i in range(1, 5)],  # too small for progress floor
            "event_id": "exec_9505",
            "iterator": "batch",
            "mode": "parallel",
            "completed_count": 6,
            "scheduled_count": 8,
        }
    }

    restored = engine._restore_loop_collection_snapshots(state, snapshots)

    assert restored == 0
    assert len(state.loop_state["run_batch_workers"]["collection"]) == 0
    assert int(state.loop_state["run_batch_workers"].get("scheduled_count", 0)) == 0


def test_restore_loop_collection_snapshot_allows_valid_single_item_parallel_loop():
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState(
        "9506",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [{"batch_number": 1}]
            }
        },
    )
    state.loop_state["run_batch_workers"] = {
        "collection": [],
        "iterator": "batch",
        "index": 1,
        "mode": "parallel",
        "completed": False,
        "results": [{}],
        "failed_count": 0,
        "scheduled_count": 1,
        "aggregation_finalized": False,
        "event_id": "exec_9506",
        "omitted_results_count": 0,
    }

    snapshots = {
        "run_batch_workers": {
            "collection": [{"batch_number": 1}],
            "event_id": "exec_9506",
            "iterator": "batch",
            "mode": "parallel",
            "completed_count": 1,
            "scheduled_count": 1,
        }
    }

    restored = engine._restore_loop_collection_snapshots(state, snapshots)

    assert restored == 1
    assert len(state.loop_state["run_batch_workers"]["collection"]) == 1
    assert int(state.loop_state["run_batch_workers"].get("scheduled_count", 0)) == 1


def test_restore_loop_collection_snapshot_clamps_cross_epoch_scheduled_count():
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/"
        "heavy_payload_pipeline_in_step_parallel.yaml"
    )
    playbook = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    parsed_playbook = engine_module.Playbook(**playbook)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState(
        "9507",
        parsed_playbook,
        payload={
            "build_batch_plan": {
                "batches": [{"batch_number": i} for i in range(1, 101)]
            }
        },
    )
    state.loop_state["run_batch_workers"] = {
        "collection": [],
        "iterator": "batch",
        "index": 0,
        "mode": "parallel",
        "completed": False,
        "results": [],
        "failed_count": 0,
        "scheduled_count": 381,
        "aggregation_finalized": False,
        "event_id": "loop_epoch_9507",
        "omitted_results_count": 0,
    }

    snapshots = {
        "run_batch_workers": {
            "collection": [{"batch_number": i} for i in range(1, 101)],
            "epoch_size": 100,
            "event_id": "loop_epoch_9507",
            "iterator": "batch",
            "mode": "parallel",
            "completed_count": 84,
            "scheduled_count": 84,
        }
    }

    restored = engine._restore_loop_collection_snapshots(state, snapshots)

    assert restored == 1
    assert len(state.loop_state["run_batch_workers"]["collection"]) == 100
    assert int(state.loop_state["run_batch_workers"].get("scheduled_count", 0)) == 84
