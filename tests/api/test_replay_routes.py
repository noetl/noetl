from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_replay_route_rejects_multiple_cutoffs():
    from noetl.server.api import replay

    app = FastAPI()
    app.include_router(replay.router, prefix="/api")
    client = TestClient(app)

    response = client.get(
        "/api/replay/state",
        params={
            "execution_id": "123",
            "as_of_event_id": "10",
            "as_of_position": "10",
        },
    )

    assert response.status_code == 400
    assert "Use only one replay cutoff" in response.json()["detail"]


def test_fold_replay_state_tracks_execution_frames_loops_and_checksum():
    from noetl.server.api.replay import fold_replay_state

    state = fold_replay_state(
        [
            {
                "event_id": 1,
                "event_type": "playbook.initialized",
                "status": "RUNNING",
                "node_name": "start",
                "tenant_id": "tenant-a",
                "organization_id": "org-a",
            },
            {
                "event_id": 2,
                "event_type": "frame.dispatched",
                "aggregate_type": "frame",
                "aggregate_id": "frame/42",
                "stage_id": 7,
                "command_id": 99,
                "meta": {"attempt": 1},
            },
            {
                "event_id": 3,
                "event_type": "frame.abandoned",
                "aggregate_type": "frame",
                "aggregate_id": "frame/42",
                "status": "ABANDONED",
                "stage_id": 7,
                "command_id": 99,
                "meta": {"reason": "lease_expired"},
            },
            {
                "event_id": 4,
                "event_type": "frame.dispatched",
                "aggregate_type": "frame",
                "aggregate_id": "frame/42",
                "stage_id": 7,
                "command_id": 100,
                "meta": {"attempt": 2},
            },
            {
                "event_id": 5,
                "event_type": "frame.committed",
                "aggregate_type": "frame",
                "aggregate_id": "frame/42",
                "status": "COMPLETED",
                "payload_ref": {"uri": "noetl://payloads/sha256/abc", "sha256": "abc"},
                "stage_id": 7,
                "meta": {"row_count": 50},
            },
            {
                "event_id": 6,
                "event_type": "stage.opened",
                "aggregate_type": "stage",
                "aggregate_id": "stage/7",
                "status": "OPEN",
                "node_name": "loop_step",
                "meta": {"loop_event_id": "loop-1"},
            },
            {
                "event_id": 7,
                "event_type": "command.completed",
                "node_name": "loop_step",
                "meta": {"loop_id": "loop-1"},
            },
            {
                "event_id": 8,
                "event_type": "loop.done",
                "node_name": "loop_step",
                "meta": {"loop_id": "loop-1"},
            },
            {
                "event_id": 9,
                "event_type": "stage.closed",
                "aggregate_type": "stage",
                "aggregate_id": "stage/7",
                "status": "COMPLETED",
                "node_name": "loop_step",
                "meta": {
                    "loop_event_id": "loop-1",
                    "frame_count": 1,
                    "row_count": 50,
                    "events_emitted": 3,
                    "failed_count": 0,
                },
            },
            {
                "event_id": 10,
                "event_type": "playbook.completed",
                "status": "COMPLETED",
                "node_name": "end",
            },
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
        upcaster_registry_digest="abc123",
    )

    assert state["event_count"] == 10
    assert state["last_event_id"] == 10
    assert state["execution"]["status"] == "COMPLETED"
    assert state["stages"]["7"]["status"] == "COMPLETED"
    assert state["stages"]["7"]["opened_event_id"] == 6
    assert state["stages"]["7"]["closed_event_id"] == 9
    assert state["stages"]["7"]["loop_event_id"] == "loop-1"
    assert state["stages"]["7"]["frame_count"] == 1
    assert state["stages"]["7"]["row_count"] == 50
    assert state["frames"]["42"]["status"] == "COMPLETED"
    assert state["frames"]["42"]["stage_id"] == "7"
    assert state["frames"]["42"]["command_id"] == "100"
    assert state["frames"]["42"]["claimed_event_id"] == 4
    assert state["frames"]["42"]["terminal_event_id"] == 5
    assert state["frames"]["42"]["attempts"] == 2
    assert state["frames"]["42"]["row_count"] == 50
    assert state["loops"]["loop-1"]["done"] == 1
    assert state["loops"]["loop-1"]["completed"] is True
    assert state["upcaster_registry_digest"] == "abc123"
    assert state["checksum_algorithm"] == "sha256"
    assert len(state["checksum"]) == 64


def test_fold_replay_state_can_resume_from_snapshot_seed():
    from noetl.server.api.replay.service import ReplaySnapshotSeed, fold_replay_state

    snapshot_state = fold_replay_state(
        [
            {
                "event_id": 1,
                "event_type": "playbook.initialized",
                "status": "RUNNING",
                "node_name": "start",
            },
            {
                "event_id": 2,
                "event_type": "frame.committed",
                "aggregate_type": "frame",
                "aggregate_id": "frame/10",
                "status": "COMPLETED",
                "meta": {"row_count": 3},
            },
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
        upcaster_registry_digest="digest-a",
    )
    seed = ReplaySnapshotSeed(
        aggregate_id="execution/123/all",
        aggregate_type="replay_state",
        version=2,
        checksum=snapshot_state["checksum"],
        state=snapshot_state,
        meta={"projection_code_version": "test"},
    )

    resumed = fold_replay_state(
        [
            {
                "event_id": 3,
                "event_type": "playbook.completed",
                "status": "COMPLETED",
                "node_name": "end",
            }
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
        upcaster_registry_digest="digest-a",
        base_state=snapshot_state,
        snapshot_seed=seed,
    )

    assert resumed["event_count"] == 3
    assert resumed["last_event_id"] == 3
    assert resumed["execution"]["status"] == "COMPLETED"
    assert resumed["frames"]["10"]["row_count"] == 3
    assert resumed["replay_snapshot"]["version"] == 2
    assert resumed["replay_snapshot"]["meta"] == {"projection_code_version": "test"}
