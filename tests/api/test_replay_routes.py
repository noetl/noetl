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
    assert state["frames"]["42"]["cursor"] == {}
    assert state["frames"]["42"]["output_ref_summary"]["sha256"] == "abc"
    assert state["loops"]["loop-1"]["done"] == 1
    assert state["loops"]["loop-1"]["completed"] is True
    assert state["upcaster_registry_digest"] == "abc123"
    assert state["checksum_algorithm"] == "sha256"
    assert len(state["checksum"]) == 64


def test_fold_replay_state_tracks_commands_and_topology():
    from noetl.server.api.replay import fold_replay_state

    state = fold_replay_state(
        [
            {
                "event_id": 11,
                "event_type": "command.issued",
                "status": "PENDING",
                "command_id": 900,
                "stage_id": 7,
                "node_name": "fetch",
                "meta": {"parent_command_id": "899"},
            },
            {
                "event_id": 12,
                "event_type": "command.claimed",
                "status": "CLAIMED",
                "command_id": 900,
                "stage_id": 7,
                "worker_id": "worker-a",
                "meta": {
                    "worker_id": "worker-a",
                    "worker_locator": "noetl://tenant/tenant-a/org/org-a/node/node-a/worker/worker-cpu-01",
                    "locality": {"node_id": "node-a", "worker_pool": "worker-cpu-01"},
                    "source_locality": {"node_id": "node-a"},
                    "placement": {
                        "distance": "node",
                        "max_distance": "node",
                        "within_max_distance": True,
                    },
                },
            },
            {
                "event_id": 13,
                "event_type": "command.started",
                "status": "RUNNING",
                "command_id": 900,
                "stage_id": 7,
            },
            {
                "event_id": 14,
                "event_type": "command.completed",
                "status": "COMPLETED",
                "command_id": 900,
                "stage_id": 7,
            },
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
    )

    command = state["commands"]["900"]
    assert command["status"] == "COMPLETED"
    assert command["stage_id"] == "7"
    assert command["parent_command_id"] == "899"
    assert command["worker_id"] == "worker-a"
    assert command["issued_event_id"] == 11
    assert command["claimed_event_id"] == 12
    assert command["started_event_id"] == 13
    assert command["terminal_event_id"] == 14
    assert command["worker_locator"].endswith("/node/node-a/worker/worker-cpu-01")
    assert command["locality"] == {"node_id": "node-a", "worker_pool": "worker-cpu-01"}
    assert command["source_locality"] == {"node_id": "node-a"}
    assert command["placement"]["within_max_distance"] is True


def test_fold_replay_state_tracks_business_objects():
    from noetl.server.api.replay import fold_replay_state

    state = fold_replay_state(
        [
            {
                "event_id": 21,
                "event_type": "patient.created",
                "aggregate_type": "business_object",
                "aggregate_id": "patient/p-1",
                "status": "ACTIVE",
                "meta": {
                    "business_object": {
                        "state": {"name": "Ada", "risk": "low"},
                        "version": 3,
                    }
                },
            },
            {
                "event_id": 22,
                "event_type": "patient.updated",
                "meta": {
                    "business_object_type": "patient",
                    "business_object_id": "p-1",
                    "business_object": {"patch": {"risk": "high"}},
                },
                "payload_ref": {
                    "uri": "noetl://tenant/tenant-a/org/org-a/payloads/sha256/patient",
                    "sha256": "patient",
                },
            },
            {
                "event_id": 23,
                "event_type": "patient.deleted",
                "aggregate_type": "business_object",
                "aggregate_id": "business_object/patient/p-1",
            },
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
    )

    patient = state["business_objects"]["patient/p-1"]
    assert patient["object_type"] == "patient"
    assert patient["object_id"] == "p-1"
    assert patient["status"] == "DELETED"
    assert patient["version"] == 3
    assert patient["event_count"] == 3
    assert patient["first_event_id"] == 21
    assert patient["last_event_id"] == 23
    assert patient["deleted_event_id"] == 23
    assert patient["attributes"] == {"name": "Ada", "risk": "high"}
    assert patient["payload_refs"][0]["summary"]["sha256"] == "patient"
    assert patient["last_payload_ref"]["event_id"] == 22


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


def test_frame_projection_checksum_matches_live_rows_and_replayed_state():
    from noetl.server.api.replay import (
        fold_replay_state,
        frame_projection_checksum,
        normalize_live_frame_projection,
        normalize_replayed_frame_projection,
    )

    output_ref = {
        "rows_ref": {
            "ref": "noetl://execution/123/result/frame/abc",
            "meta": {
                "sha256": "payload-sha",
                "schema_digest": "schema-sha",
                "row_count": 50,
                "media_type": "application/vnd.apache.arrow.stream",
            },
        },
        "row_count": 50,
        "schema_digest": "schema-sha",
        "media_type": "application/vnd.apache.arrow.stream",
    }
    events = [
        {
            "event_id": 10,
            "event_type": "frame.dispatched",
            "aggregate_type": "frame",
            "aggregate_id": "frame/42",
            "stage_id": 7,
            "command_id": 99,
            "meta": {"attempt": 1, "parent_frame_id": "41"},
        },
        {
            "event_id": 11,
            "event_type": "frame.committed",
            "aggregate_type": "frame",
            "aggregate_id": "frame/42",
            "status": "COMPLETED",
            "payload_ref": output_ref,
            "stage_id": 7,
            "command_id": 99,
            "meta": {
                "row_count": 50,
                "events_emitted": 2,
                "cursor": {"last_id": "p-50"},
            },
        },
    ]
    state = fold_replay_state(
        events,
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
    )
    live_rows = normalize_live_frame_projection(
        [
            {
                "frame_id": 42,
                "stage_id": 7,
                "parent_frame_id": 41,
                "command_id": 99,
                "claimed_event_id": 10,
                "terminal_event_id": 11,
                "status": "COMPLETED",
                "row_count": 50,
                "cursor": {"last_id": "p-50"},
                "events_emitted": 2,
                "output_ref": output_ref,
            }
        ]
    )
    replayed_rows = normalize_replayed_frame_projection(state)

    assert replayed_rows == live_rows
    assert frame_projection_checksum(replayed_rows) == frame_projection_checksum(live_rows)
    assert replayed_rows[0]["output_ref_summary"] == {
        "sha256": "payload-sha",
        "schema_digest": "schema-sha",
        "row_count": 50,
        "media_type": "application/vnd.apache.arrow.stream",
        "ref": "noetl://execution/123/result/frame/abc",
    }


def test_command_projection_checksum_matches_live_rows_and_replayed_state():
    from noetl.server.api.replay import (
        command_projection_checksum,
        fold_replay_state,
        normalize_live_command_projection,
        normalize_replayed_command_projection,
    )

    events = [
        {
            "event_id": 20,
            "event_type": "command.issued",
            "status": "PENDING",
            "command_id": 900,
            "stage_id": 7,
            "frame_id": 42,
            "meta": {"parent_command_id": "899"},
        },
        {
            "event_id": 21,
            "event_type": "command.claimed",
            "status": "CLAIMED",
            "command_id": 900,
            "stage_id": 7,
            "frame_id": 42,
            "worker_id": "worker-a",
            "meta": {
                "worker_id": "worker-a",
                "worker_locator": "noetl://tenant/tenant-a/org/org-a/node/node-a/worker/worker-cpu-01",
                "locality": {"node_id": "node-a"},
                "source_locality": {"node_id": "node-a"},
                "placement": {
                    "distance": "node",
                    "max_distance": "node",
                    "within_max_distance": True,
                },
            },
        },
        {
            "event_id": 22,
            "event_type": "command.completed",
            "status": "COMPLETED",
            "command_id": 900,
            "stage_id": 7,
            "frame_id": 42,
        },
    ]
    state = fold_replay_state(
        events,
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
    )
    live_rows = normalize_live_command_projection(
        [
            {
                "command_id": 900,
                "stage_id": 7,
                "frame_id": 42,
                "parent_command_id": "899",
                "worker_id": "worker-a",
                "worker_locator": "noetl://tenant/tenant-a/org/org-a/node/node-a/worker/worker-cpu-01",
                "locality": {"node_id": "node-a"},
                "source_locality": {"node_id": "node-a"},
                "placement": {
                    "distance": "node",
                    "max_distance": "node",
                    "within_max_distance": True,
                },
                "status": "COMPLETED",
                "issued_event_id": 20,
                "claimed_event_id": 21,
                "started_event_id": None,
                "terminal_event_id": 22,
            }
        ]
    )
    replayed_rows = normalize_replayed_command_projection(state)

    assert replayed_rows == live_rows
    assert command_projection_checksum(replayed_rows) == command_projection_checksum(live_rows)


def test_business_object_projection_checksum_matches_live_rows_and_replayed_state():
    from noetl.server.api.replay import (
        business_object_projection_checksum,
        fold_replay_state,
        normalize_live_business_object_projection,
        normalize_replayed_business_object_projection,
    )

    payload_ref = {
        "uri": "noetl://tenant/tenant-a/org/org-a/payloads/sha256/patient",
        "sha256": "patient",
        "media_type": "application/json",
    }
    events = [
        {
            "event_id": 30,
            "event_type": "patient.created",
            "aggregate_type": "business_object",
            "aggregate_id": "patient/p-1",
            "status": "ACTIVE",
            "meta": {
                "business_object": {
                    "state": {"name": "Ada", "risk": "low"},
                    "version": 1,
                }
            },
        },
        {
            "event_id": 31,
            "event_type": "patient.updated",
            "payload_ref": payload_ref,
            "meta": {
                "business_object_type": "patient",
                "business_object_id": "p-1",
                "business_object": {"patch": {"risk": "high"}, "version": 2},
            },
        },
    ]
    state = fold_replay_state(
        events,
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
    )
    live_rows = normalize_live_business_object_projection(
        [
            {
                "object_key": "patient/p-1",
                "object_type": "patient",
                "object_id": "p-1",
                "status": "ACTIVE",
                "version": 2,
                "event_count": 2,
                "first_event_id": 30,
                "last_event_id": 31,
                "deleted_event_id": None,
                "last_event_type": "patient.updated",
                "last_payload_ref": {"event_id": 31, "reference": payload_ref},
                "payload_refs": [{"event_id": 31, "reference": payload_ref}],
                "attributes": {"name": "Ada", "risk": "high"},
            }
        ]
    )
    replayed_rows = normalize_replayed_business_object_projection(state)

    assert replayed_rows == live_rows
    assert business_object_projection_checksum(replayed_rows) == business_object_projection_checksum(live_rows)
