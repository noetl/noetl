from pathlib import Path

import pytest
import yaml

import noetl.core.dsl.engine.engine as engine_module
from noetl.core.dsl.engine.engine import ExecutionState, Playbook, PlaybookRepo, StateStore


def _load_heavy_payload_playbook() -> Playbook:
    fixture = Path(
        "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step/"
        "heavy_payload_pipeline_in_step.yaml"
    )
    return Playbook(**yaml.safe_load(fixture.read_text(encoding="utf-8")))


def test_execution_state_caps_loop_result_buffer(monkeypatch):
    playbook = _load_heavy_payload_playbook()
    state = ExecutionState("9401", playbook, payload={})
    state.init_loop("run_batch_workers", list(range(20)), "batch", "sequential")

    monkeypatch.setattr(engine_module, "_LOOP_RESULT_MAX_ITEMS", 8)

    for idx in range(20):
        state.add_loop_result("run_batch_workers", {"idx": idx})

    loop_state = state.loop_state["run_batch_workers"]
    assert len(loop_state["results"]) == 8
    assert loop_state["omitted_results_count"] == 12
    assert state.get_loop_completed_count("run_batch_workers") == 20
    assert loop_state["results"][0]["idx"] == 12
    assert loop_state["results"][-1]["idx"] == 19

    aggregation = state.get_loop_aggregation("run_batch_workers")
    assert aggregation["stats"]["total"] == 20
    assert aggregation["omitted_results_count"] == 12
    assert len(aggregation["results"]) == 8


@pytest.mark.asyncio
async def test_state_replay_caps_loop_results_and_preserves_total_count(monkeypatch):
    playbook = _load_heavy_payload_playbook()
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)

    async def fake_load_playbook_by_id(_catalog_id):
        return playbook

    monkeypatch.setattr(playbook_repo, "load_playbook_by_id", fake_load_playbook_by_id)
    monkeypatch.setattr(engine_module, "_LOOP_RESULT_MAX_ITEMS", 16)

    replay_rows = [
        {
            "node_name": "run_batch_workers:task_sequence",
            "event_type": "command.issued",
            "result": None,
            "meta": {"loop_event_id": "loop_9011"},
        }
    ]
    replay_rows.extend(
        {
            "node_name": "run_batch_workers",
            "event_type": "step.exit",
            "result": {
                "kind": "data",
                "data": {
                    "status": "completed",
                    "result": {"idx": idx},
                },
            },
            "meta": None,
        }
        for idx in range(40)
    )

    class FakeCursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, _params):
            self.last_query = query

        async def fetchone(self):
            return {
                "catalog_id": "cat-loop",
                "result": {"workload": {"seed_rows": 40}},
            }

        async def fetchall(self):
            return replay_rows

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
    assert state.get_loop_completed_count("run_batch_workers") == 40

    loop_state = state.loop_state["run_batch_workers"]
    assert loop_state["index"] == 40
    assert loop_state["scheduled_count"] == 40
    assert loop_state["iterator"] == "batch"
    assert loop_state["mode"] == "sequential"
    assert loop_state["event_id"] == "loop_9011"
    assert len(loop_state["results"]) == 16
    assert loop_state["omitted_results_count"] == 24
    assert loop_state["results"][0]["idx"] == 24
    assert loop_state["results"][-1]["idx"] == 39
