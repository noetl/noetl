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
                "meta": {"stage_id": "7", "attempt": 1},
            },
            {
                "event_id": 3,
                "event_type": "frame.committed",
                "aggregate_type": "frame",
                "aggregate_id": "frame/42",
                "status": "COMPLETED",
                "payload_ref": {"uri": "noetl://payloads/sha256/abc", "sha256": "abc"},
                "meta": {"stage_id": "7", "row_count": 50},
            },
            {
                "event_id": 4,
                "event_type": "command.completed",
                "node_name": "loop_step",
                "meta": {"loop_id": "loop-1"},
            },
            {
                "event_id": 5,
                "event_type": "loop.done",
                "node_name": "loop_step",
                "meta": {"loop_id": "loop-1"},
            },
            {
                "event_id": 6,
                "event_type": "playbook.completed",
                "status": "COMPLETED",
                "node_name": "end",
            },
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
    )

    assert state["event_count"] == 6
    assert state["last_event_id"] == 6
    assert state["execution"]["status"] == "COMPLETED"
    assert state["frames"]["42"]["status"] == "COMPLETED"
    assert state["frames"]["42"]["row_count"] == 50
    assert state["loops"]["loop-1"]["done"] == 1
    assert state["loops"]["loop-1"]["completed"] is True
    assert state["checksum_algorithm"] == "sha256"
    assert len(state["checksum"]) == 64
