from pathlib import Path

import pytest
import yaml

import noetl.core.dsl.engine.engine as engine_module
from noetl.core.dsl.render import TaskResultProxy
from noetl.core.dsl.engine.engine import ControlFlowEngine, ExecutionState, PlaybookRepo, StateStore
from noetl.core.dsl.engine.models import Command, Event, Playbook, ToolCall


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

    async def try_claim_loop_done(self, execution_id, step_name, event_id=None):
        return True  # always grants by default in existing tests


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


class ClaimAwareNATSCache(FakeNATSCache):
    """Simulates two concurrent handlers: first claim wins, second loses."""

    def __init__(self, terminal_count: int):
        super().__init__()
        self._terminal_count = terminal_count
        self._claim_count = 0
        self.loop_done_dispatch_count = 0

    async def increment_loop_completed(self, execution_id, step_name, event_id=None):
        return self._terminal_count  # both handlers see terminal count

    async def get_loop_state(self, execution_id, step_name, event_id=None):
        return {"collection_size": self._terminal_count, "completed_count": self._terminal_count}

    async def try_claim_loop_done(self, execution_id, step_name, event_id=None):
        self._claim_count += 1
        return self._claim_count == 1  # first caller wins, rest lose


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
            input={},
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
            input={},
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


@pytest.mark.asyncio
async def test_task_sequence_loop_persists_issued_steps_before_return(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/"
        "traveler_batch_enrichment_in_step.yaml"
    )
    playbook = Playbook(**yaml.safe_load(fixture.read_text(encoding="utf-8")))

    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9011"
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

    saved_issued_steps: list[set[str]] = []
    real_save_state = state_store.save_state

    async def tracking_save_state(state_obj):
        saved_issued_steps.append(set(state_obj.issued_steps))
        await real_save_state(state_obj)

    async def fake_create_command_for_step(_state, step_def, _args):
        return Command(
            execution_id=execution_id,
            step=step_def.step,
            tool=ToolCall(kind="playbook", config={}),
            input={},
            render_context={},
        )

    async def fake_evaluate_next_transitions(*_args, **_kwargs):
        return []

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_create_command_for_step", fake_create_command_for_step)
    monkeypatch.setattr(engine, "_evaluate_next_transitions", fake_evaluate_next_transitions)
    monkeypatch.setattr(state_store, "save_state", tracking_save_state)

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
    assert parent_step in state.issued_steps
    assert saved_issued_steps
    assert parent_step in saved_issued_steps[-1]


@pytest.mark.asyncio
async def test_task_sequence_loop_persists_event_before_early_return_when_needed(monkeypatch):
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/"
        "traveler_batch_enrichment_in_step.yaml"
    )
    playbook = Playbook(**yaml.safe_load(fixture.read_text(encoding="utf-8")))

    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9011b"
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

    call_order: list[str] = []
    real_save_state = state_store.save_state

    async def tracking_save_state(state_obj):
        call_order.append("save_state")
        await real_save_state(state_obj)

    async def fake_persist_event(event_obj, state_obj):  # noqa: ARG001
        call_order.append(f"persist:{event_obj.name}")
        state_obj.last_event_id = "persisted-call-done"

    async def fake_create_command_for_step(_state, step_def, _args):
        return Command(
            execution_id=execution_id,
            step=step_def.step,
            tool=ToolCall(kind="playbook", config={}),
            input={},
            render_context={},
        )

    async def fake_evaluate_next_transitions(*_args, **_kwargs):
        return []

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_persist_event", fake_persist_event)
    monkeypatch.setattr(engine, "_create_command_for_step", fake_create_command_for_step)
    monkeypatch.setattr(engine, "_evaluate_next_transitions", fake_evaluate_next_transitions)
    monkeypatch.setattr(state_store, "save_state", tracking_save_state)

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

    commands = await engine.handle_event(event, already_persisted=False)

    assert len(commands) == 1
    assert commands[0].step == parent_step
    assert call_order[-2:] == ["save_state", "persist:call.done"]


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
async def test_state_replay_restores_set_ctx_variables_for_later_steps(monkeypatch):
    playbook = Playbook(**yaml.safe_load(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: replay_set_ctx
  path: tests/replay_set_ctx
workload:
  pg_auth: pg_k8s
workflow:
  - step: load_next_facility
    tool:
      kind: postgres
      auth: pg_k8s
      query: SELECT 1;
    set:
      ctx.facility_mapping_id: "{{ load_next_facility.command_0.rows[0].facility_mapping_id }}"
      ctx.facility_id: "{{ load_next_facility.command_0.rows[0].facility_id }}"
  - step: load_patient_ids_context
    tool:
      kind: postgres
      auth: pg_k8s
      query: SELECT 1;
    set:
      ctx.patient_count: "{{ load_patient_ids_context.command_0.rows[0].patient_count | int }}"
      ctx.facility_mapping_id: "{{ load_next_facility.command_0.rows[0].facility_mapping_id }}"
  - step: load_patients_for_assessments
    tool:
      kind: postgres
      auth: pg_k8s
      query: |
        SELECT w.patient_id
        FROM public.patient_ids_work w
        WHERE w.facility_mapping_id = {{ facility_mapping_id }}
          AND {{ patient_count }} > 0;
        """
    ))
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)

    async def fake_load_playbook_by_id(_catalog_id):
        return playbook

    monkeypatch.setattr(playbook_repo, "load_playbook_by_id", fake_load_playbook_by_id)

    class FakeCursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, _params):
            self.last_query = query

        async def fetchone(self):
            return {
                "catalog_id": "cat-ctx",
                "result": {"workload": {"pg_auth": "pg_k8s"}},
            }

        async def fetchall(self):
            return [
                {
                    "node_name": "load_next_facility",
                    "event_type": "step.exit",
                    "result": {
                        "kind": "data",
                        "data": {
                            "result": {
                                "command_0": {
                                    "rows": [
                                        {
                                            "facility_mapping_id": 53,
                                            "facility_id": 777,
                                        }
                                    ],
                                    "row_count": 1,
                                }
                            },
                            "status": "completed",
                        },
                    },
                    "meta": None,
                },
                {
                    "node_name": "load_patient_ids_context",
                    "event_type": "step.exit",
                    "result": {
                        "kind": "data",
                        "data": {
                            "result": {
                                "command_0": {
                                    "rows": [{"patient_count": 3}],
                                    "row_count": 1,
                                }
                            },
                            "status": "completed",
                        },
                    },
                    "meta": None,
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

    state = await state_store.load_state("9021")

    assert state is not None
    assert state.variables["facility_mapping_id"] == 53
    assert state.variables["facility_id"] == 777
    assert state.variables["patient_count"] == 3

    context = state.get_render_context(Event(execution_id="9021", step="load_patients_for_assessments", name="call.done", payload={}))
    assert context["facility_mapping_id"] == 53
    assert context["ctx"]["facility_mapping_id"] == 53
    assert context["patient_count"] == 3


@pytest.mark.asyncio
async def test_state_replay_restores_set_ctx_from_reference_only_context_shape(monkeypatch):
    playbook = Playbook(**yaml.safe_load(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: replay_set_ctx_reference_only
  path: tests/replay_set_ctx_reference_only
workload:
  pg_auth: pg_k8s
workflow:
  - step: load_next_facility
    tool:
      kind: postgres
      auth: pg_k8s
      query: SELECT 1;
    set:
      ctx.facility_mapping_id: "{{ load_next_facility.command_0.rows[0].facility_mapping_id }}"
      ctx.facility_id: "{{ load_next_facility.command_0.rows[0].facility_id }}"
  - step: load_patient_ids_context
    tool:
      kind: postgres
      auth: pg_k8s
      query: SELECT 1;
    set:
      ctx.patient_count: "{{ load_patient_ids_context.command_0.rows[0].patient_count | int }}"
      ctx.facility_mapping_id: "{{ load_next_facility.command_0.rows[0].facility_mapping_id }}"
  - step: load_patients_for_assessments
    tool:
      kind: postgres
      auth: pg_k8s
      query: |
        SELECT w.patient_id
        FROM public.patient_ids_work w
        WHERE w.facility_mapping_id = {{ facility_mapping_id }}
          AND {{ patient_count }} > 0;
        """
    ))
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)

    async def fake_load_playbook_by_id(_catalog_id):
        return playbook

    monkeypatch.setattr(playbook_repo, "load_playbook_by_id", fake_load_playbook_by_id)

    class FakeCursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, _params):
            self.last_query = query

        async def fetchone(self):
            return {
                "catalog_id": "cat-ctx-ref",
                "context": {"workload": {"pg_auth": "pg_k8s"}},
                "result": {"status": "COMPLETED"},
            }

        async def fetchall(self):
            return [
                {
                    "node_name": "load_next_facility",
                    "event_type": "step.exit",
                    "result": {
                        "status": "COMPLETED",
                        "context": {
                            "command_0": {
                                "rows": [
                                    {
                                        "facility_mapping_id": 91,
                                        "facility_id": 7001,
                                    }
                                ],
                                "row_count": 1,
                            }
                        },
                    },
                    "meta": None,
                },
                {
                    "node_name": "load_patient_ids_context",
                    "event_type": "step.exit",
                    "result": {
                        "status": "COMPLETED",
                        "context": {
                            "command_0": {
                                "rows": [{"patient_count": 17}],
                                "row_count": 1,
                            }
                        },
                    },
                    "meta": None,
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

    state = await state_store.load_state("9022")

    assert state is not None
    assert state.variables["facility_mapping_id"] == 91
    assert state.variables["facility_id"] == 7001
    assert state.variables["patient_count"] == 17

    context = state.get_render_context(Event(execution_id="9022", step="load_patients_for_assessments", name="call.done", payload={}))
    assert context["facility_mapping_id"] == 91
    assert context["ctx"]["facility_mapping_id"] == 91
    assert context["patient_count"] == 17


@pytest.mark.asyncio
async def test_state_replay_restores_set_ctx_from_reference_only_result_ref(monkeypatch):
    playbook = Playbook(**yaml.safe_load(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: replay_set_ctx_reference_only_ref
  path: tests/replay_set_ctx_reference_only_ref
workload:
  pg_auth: pg_k8s
workflow:
  - step: load_next_facility
    tool:
      kind: postgres
      auth: pg_k8s
      query: SELECT 1;
    set:
      ctx.facility_mapping_id: "{{ load_next_facility.data.result.command_0.rows[0].facility_mapping_id }}"
      ctx.facility_id: "{{ load_next_facility.data.result.command_0.rows[0].facility_id }}"
  - step: load_patients_for_assessments
    tool:
      kind: postgres
      auth: pg_k8s
      query: |
        SELECT w.patient_id
        FROM public.patient_ids_work w
        WHERE w.facility_mapping_id = {{ facility_mapping_id }};
        """
    ))
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)

    async def fake_load_playbook_by_id(_catalog_id):
        return playbook

    async def fake_resolve(ref):
        assert ref["ref"] == "noetl://execution/9025/result/load_next_facility/abcd1234"
        return {
            "data": {
                "result": {
                    "command_0": {
                        "rows": [
                            {
                                "facility_mapping_id": 119,
                                "facility_id": 8123,
                            }
                        ],
                        "row_count": 1,
                    }
                }
            }
        }

    monkeypatch.setattr(playbook_repo, "load_playbook_by_id", fake_load_playbook_by_id)
    monkeypatch.setattr(engine_module.default_store, "resolve", fake_resolve)

    class FakeCursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, _params):
            self.last_query = query

        async def fetchone(self):
            return {
                "catalog_id": "cat-ctx-ref-hydrated",
                "context": {"workload": {"pg_auth": "pg_k8s"}},
                "result": {"status": "COMPLETED"},
            }

        async def fetchall(self):
            return [
                {
                    "node_name": "load_next_facility",
                    "event_type": "step.exit",
                    "result": {
                        "status": "COMPLETED",
                        "reference": {
                            "type": "nats",
                            "store": "kv",
                            "locator": "noetl://execution/9025/result/load_next_facility/abcd1234",
                        },
                    },
                    "meta": None,
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

    state = await state_store.load_state("9025")

    assert state is not None
    assert state.variables["facility_mapping_id"] == 119
    assert state.variables["facility_id"] == 8123


def test_mark_step_completed_adds_context_alias_for_plain_dict_results():
    playbook = Playbook(**yaml.safe_load(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: context_alias_test
  path: tests/context_alias_test
workflow:
  - step: compute_report_window
    tool:
      kind: python
      code: |
        def main():
          return {}
        """
    ))
    state = ExecutionState("9023", playbook, payload={})
    state.mark_step_completed(
        "compute_report_window",
        {
            "report_start_date": "2026-03-01",
            "report_end_date": "2026-03-31",
        },
    )

    step_result = state.step_results["compute_report_window"]
    assert "context" in step_result
    assert step_result["context"]["report_start_date"] == "2026-03-01"
    assert step_result["context"]["report_end_date"] == "2026-03-31"


def test_mark_step_completed_does_not_flatten_non_reference_context_payload():
    playbook = Playbook(**yaml.safe_load(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: context_flatten_guard_test
  path: tests/context_flatten_guard_test
workflow:
  - step: end
    tool:
      kind: python
      code: |
        def main():
          return {}
        """
    ))
    state = ExecutionState("9024", playbook, payload={})
    state.mark_step_completed(
        "end",
        {
            "status": "COMPLETED",
            "context": {"ctx_vars": {"foo": "bar"}},
        },
    )

    step_result = state.step_results["end"]
    assert "ctx_vars" not in step_result
    assert step_result["context"]["ctx_vars"]["foo"] == "bar"


def test_task_result_proxy_keeps_context_scoped_access_only():
    proxy = TaskResultProxy(
        {
            "status": "COMPLETED",
            "context": {
                "facility_mapping_id": 42,
            },
        }
    )
    with pytest.raises(KeyError):
        _ = proxy["facility_mapping_id"]

    assert proxy.context.facility_mapping_id == 42


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


@pytest.mark.asyncio
async def test_finalize_abandoned_execution_emits_terminal_failure_events(monkeypatch):
    playbook = Playbook(
        **{
            "apiVersion": "noetl.io/v2",
            "kind": "Playbook",
            "metadata": {"name": "finalize-test", "path": "tests/finalize-test"},
            "workflow": [
                {
                    "step": "events.batch",
                    "tool": {"kind": "noop"},
                }
            ],
        }
    )
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9015"
    state = ExecutionState(execution_id, playbook, payload={})
    state.current_step = "events.batch"
    await state_store.save_state(state)

    persisted_events = []

    async def fake_persist_event(event, state_obj):
        persisted_events.append(event.name)
        state_obj.last_event_id = (state_obj.last_event_id or 0) + 1

    monkeypatch.setattr(engine, "_persist_event", fake_persist_event)

    await engine.finalize_abandoned_execution(execution_id, reason="stuck in production")

    assert state.completed is True
    assert state.failed is True
    assert persisted_events == ["workflow.failed", "playbook.failed"]


@pytest.mark.asyncio
async def test_call_done_with_unmatched_next_arcs_emits_terminal_completion(monkeypatch):
    playbook = Playbook(
        **{
            "apiVersion": "noetl.io/v2",
            "kind": "Playbook",
            "metadata": {"name": "dead-end-next", "path": "tests/dead-end-next"},
            "workflow": [
                {
                    "step": "events.batch",
                    "tool": {"kind": "noop"},
                    "next": {
                        "spec": {"mode": "exclusive"},
                        "arcs": [
                            {"step": "follow_up", "when": "{{ ctx.route == 'follow_up' }}"},
                        ],
                    },
                },
                {
                    "step": "follow_up",
                    "tool": {"kind": "noop"},
                },
            ],
        }
    )
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9016"
    state = ExecutionState(execution_id, playbook, payload={})
    state.variables["route"] = "not_follow_up"
    # Keep completion check purely in-memory (skip DB pending fallback query).
    state.issued_steps.add("events.batch")
    state.completed_steps.add("events.batch")
    await state_store.save_state(state)

    persisted_events = []

    async def fake_persist_event(event, state_obj):
        persisted_events.append(event.name)
        state_obj.last_event_id = (state_obj.last_event_id or 0) + 1

    monkeypatch.setattr(engine, "_persist_event", fake_persist_event)

    event = Event(
        execution_id=execution_id,
        step="events.batch",
        name="call.done",
        payload={"status": "completed", "result": {"row_count": 1}},
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert commands == []
    assert state.completed is True
    assert persisted_events == ["workflow.completed", "playbook.completed"]


@pytest.mark.asyncio
async def test_call_error_with_explicit_end_step_without_tool_completes_failure(monkeypatch):
    playbook = Playbook(
        **{
            "apiVersion": "noetl.io/v2",
            "kind": "Playbook",
            "metadata": {
                "name": "explicit-end-no-tool",
                "path": "tests/explicit-end-no-tool",
            },
            "workflow": [
                {
                    "step": "start",
                    "tool": {"kind": "noop"},
                    "next": {
                        "spec": {"mode": "exclusive"},
                        "arcs": [{"step": "end"}],
                    },
                },
                {
                    "step": "end",
                    "desc": "Terminal end step without a tool",
                },
            ],
        }
    )
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9017"
    state = ExecutionState(execution_id, playbook, payload={})
    state.issued_steps.add("start")
    state.completed_steps.add("start")
    await state_store.save_state(state)

    persisted_events = []

    async def fake_persist_event(event, state_obj):
        persisted_events.append(event.name)
        state_obj.last_event_id = (state_obj.last_event_id or 0) + 1

    monkeypatch.setattr(engine, "_persist_event", fake_persist_event)

    event = Event(
        execution_id=execution_id,
        step="start",
        name="call.error",
        payload={"error": {"message": "boom"}},
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert commands == []
    assert state.completed is True
    assert state.failed is True
    assert persisted_events == ["workflow.failed", "playbook.failed"]


@pytest.mark.asyncio
async def test_completed_execution_short_circuits_late_events(monkeypatch):
    playbook = Playbook(
        **{
            "apiVersion": "noetl.io/v2",
            "kind": "Playbook",
            "metadata": {"name": "completed-short-circuit", "path": "tests/completed-short-circuit"},
            "workflow": [
                {
                    "step": "events.batch",
                    "tool": {"kind": "noop"},
                    "next": {
                        "spec": {"mode": "exclusive"},
                        "arcs": [{"step": "follow_up"}],
                    },
                },
                {
                    "step": "follow_up",
                    "tool": {"kind": "noop"},
                },
            ],
        }
    )
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9017"
    state = ExecutionState(execution_id, playbook, payload={})
    state.completed = True
    await state_store.save_state(state)

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("routing should not run for completed execution")

    monkeypatch.setattr(engine, "_evaluate_next_transitions_with_match", fail_if_called)

    event = Event(
        execution_id=execution_id,
        step="events.batch",
        name="call.done",
        payload={"status": "completed", "result": {"row_count": 1}},
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert commands == []


@pytest.mark.asyncio
async def test_state_replay_restores_event_watermark(monkeypatch):
    playbook = Playbook(**yaml.safe_load(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: replay_event_ids
  path: tests/replay_event_ids
workload:
  pg_auth: pg_k8s
workflow:
  - step: load_next_facility
    tool:
      kind: postgres
      auth: pg_k8s
      query: SELECT 1;
  - step: load_patient_ids_context
    tool:
      kind: postgres
      auth: pg_k8s
      query: SELECT 1;
        """
    ))
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
            return {
                "catalog_id": "cat-event-ids",
                "result": {"workload": {"pg_auth": "pg_k8s"}},
            }

        async def fetchall(self):
            return [
                {
                    "event_id": 101,
                    "node_name": "load_next_facility",
                    "event_type": "step.exit",
                    "result": {
                        "kind": "data",
                        "data": {"result": {"command_0": {"rows": [{"facility_mapping_id": 53}]}}},
                    },
                    "meta": None,
                },
                {
                    "event_id": 102,
                    "node_name": "load_patient_ids_context",
                    "event_type": "step.exit",
                    "result": {
                        "kind": "data",
                        "data": {"result": {"command_0": {"rows": [{"patient_count": 3}]}}},
                    },
                    "meta": None,
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

    state = await state_store.load_state("9030")

    assert state is not None
    assert state.last_event_id == 102
    assert state.step_event_ids["load_next_facility"] == 101
    assert state.step_event_ids["load_patient_ids_context"] == 102


@pytest.mark.asyncio
async def test_load_state_preserves_terminal_failure_after_late_events(monkeypatch):
    playbook = Playbook(**yaml.safe_load(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: terminal_replay
  path: tests/terminal_replay
workflow:
  - step: start
    tool:
      kind: python
      code: |
        result = {"ok": True}
        """
    ))
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)

    async def _fake_load_playbook_by_id(_catalog_id):
        return playbook

    monkeypatch.setattr(playbook_repo, "load_playbook_by_id", _fake_load_playbook_by_id)

    class FakeCursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, _params):
            self.last_query = query

        async def fetchone(self):
            return {
                "catalog_id": 999,
                "result": {"workload": {}},
            }

        async def fetchall(self):
            return [
                {
                    "event_id": 201,
                    "node_name": "workflow",
                    "event_type": "workflow.failed",
                    "result": {"kind": "data", "data": {"error": {"message": "boom"}}},
                    "meta": None,
                },
                {
                    "event_id": 202,
                    "node_name": "start",
                    "event_type": "command.issued",
                    "result": None,
                    "meta": {"command_id": "exec:start:202"},
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

    state = await state_store.load_state("9031")

    assert state is not None
    assert state.failed is True
    assert state.completed is True
    assert state.last_event_id == 202


@pytest.mark.asyncio
async def test_handle_event_invalidates_stale_cached_state(monkeypatch):
    playbook = Playbook(**yaml.safe_load(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: stale_cache_refresh
  path: tests/stale_cache_refresh
workflow:
  - step: start
    tool:
      kind: python
      code: |
        result = {"ok": True}
        """
    ))
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9031"
    stale_state = ExecutionState(execution_id, playbook, payload={})
    stale_state.last_event_id = 10
    await state_store.save_state(stale_state)

    refreshed_state = ExecutionState(execution_id, playbook, payload={})
    refreshed_state.last_event_id = 12

    invalidate_calls = []

    async def fake_should_refresh(_execution_id, _last_event_id, *, allowed_missing_events=1):
        assert _execution_id == execution_id
        assert _last_event_id == 10
        assert allowed_missing_events == 1
        return True

    async def fake_invalidate(execution_id_arg, reason="manual"):
        invalidate_calls.append((execution_id_arg, reason))
        return True

    async def fake_load_state(_execution_id):
        assert _execution_id == execution_id
        return refreshed_state

    async def fake_persist_event(_event, state_obj):
        state_obj.last_event_id = (state_obj.last_event_id or 0) + 1

    async def fake_save_state(_state):
        return None

    class FakeCursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, _params=None):
            self.last_query = query

        async def fetchone(self):
            return {"pending_count": 0}

    class FakeConnection:
        def cursor(self, row_factory=None):  # noqa: ARG002
            return FakeCursor()

    class FakeConnectionContext:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(engine_module, "get_pool_connection", lambda: FakeConnectionContext())
    monkeypatch.setattr(state_store, "should_refresh_cached_state", fake_should_refresh)
    monkeypatch.setattr(state_store, "invalidate_state", fake_invalidate)
    monkeypatch.setattr(state_store, "load_state", fake_load_state)
    monkeypatch.setattr(engine, "_persist_event", fake_persist_event)
    monkeypatch.setattr(state_store, "save_state", fake_save_state)

    event = Event(
        execution_id=execution_id,
        step="start",
        name="call.done",
        payload={"response": {"status": "completed", "result": {"ok": True}}},
    )

    await engine.handle_event(event, already_persisted=True)

    assert invalidate_calls == [
        (execution_id, "stale_cache_newer_persisted_events")
    ]


@pytest.mark.asyncio
async def test_task_sequence_loop_concurrent_call_done_dispatches_loop_done_only_once(monkeypatch):
    """Two concurrent call.done handlers at the terminal count must produce loop.done commands only once.

    The ClaimAwareNATSCache grants the claim to exactly one caller (first wins, second loses).
    We use asyncio.gather to run two handle_event calls simultaneously and verify that
    loop.done-related transitions are evaluated exactly once across both handlers.
    """
    import asyncio as _asyncio

    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/"
        "traveler_batch_enrichment_in_step.yaml"
    )
    playbook = Playbook(**yaml.safe_load(fixture.read_text(encoding="utf-8")))

    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    execution_id = "9050"
    parent_step = "run_batch_workers"
    terminal_count = 4  # matches collection_size returned by ClaimAwareNATSCache

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

    claim_cache = ClaimAwareNATSCache(terminal_count)

    async def fake_get_nats_cache():
        return claim_cache

    loop_done_eval_count = {"count": 0}

    async def counting_evaluate_next_transitions(_state, _step_def, event_obj):
        if event_obj.name == "loop.done":
            loop_done_eval_count["count"] += 1
        return []

    async def fake_create_command_for_step(_state, step_def, _args):
        return Command(
            execution_id=execution_id,
            step=step_def.step,
            tool=ToolCall(kind="playbook", config={}),
            input={},
            render_context={},
        )

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_create_command_for_step", fake_create_command_for_step)
    monkeypatch.setattr(engine, "_evaluate_next_transitions", counting_evaluate_next_transitions)

    event_a = Event(
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
    event_b = Event(
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

    await _asyncio.gather(
        engine.handle_event(event_a, already_persisted=True),
        engine.handle_event(event_b, already_persisted=True),
    )

    assert loop_done_eval_count["count"] == 1, (
        f"loop.done transitions evaluated {loop_done_eval_count['count']} times; expected exactly 1"
    )
    # At least one handler must have attempted the claim. In practice the second handler
    # may be blocked earlier by the aggregation_finalized in-process guard (the second layer
    # of defence), so _claim_count may be 1 or 2 depending on asyncio interleaving.
    assert claim_cache._claim_count >= 1
