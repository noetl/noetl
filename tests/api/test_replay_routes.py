from datetime import datetime, timezone

import pytest
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
    assert set(state["projection_checksums"]) == {
        "execution",
        "stages",
        "frames",
        "commands",
        "business_objects",
        "loops",
    }
    assert all(len(checksum) == 64 for checksum in state["projection_checksums"].values())


@pytest.mark.asyncio
async def test_replay_service_accepts_per_call_event_reader():
    from noetl.server.api.replay import ReplayCutoff, ReplayService

    class _Reader:
        async def load_snapshot_seed(self, **kwargs):
            return None

        async def load_events(self, **kwargs):
            return [
                {
                    "event_id": 2,
                    "event_type": "execution.failed",
                    "status": "FAILED",
                    "execution_id": kwargs["execution_id"],
                }
            ]

    state = await ReplayService.replay_state(
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=456,
        cutoff=ReplayCutoff(),
        projection="all",
        limit=100,
        event_reader=_Reader(),
    )

    assert state["execution_id"] == 456
    assert state["execution"]["status"] == "FAILED"


@pytest.mark.asyncio
async def test_replay_service_accepts_per_call_upcaster_registry():
    from noetl.server.api.replay import EventUpcasterRegistry, ReplayCutoff, ReplayService

    class _Reader:
        async def load_snapshot_seed(self, **kwargs):
            return None

        async def load_events(self, **kwargs):
            return [
                {
                    "event_id": 1,
                    "event_type": "legacy.execution.finished",
                    "schema_name": "noetl.event",
                    "schema_version": 1,
                    "execution_id": kwargs["execution_id"],
                }
            ]

    registry = EventUpcasterRegistry()
    registry.register(
        "noetl.event",
        1,
        lambda event: {
            **event,
            "schema_version": 2,
            "event_type": "execution.completed",
            "status": "COMPLETED",
        },
    )

    state = await ReplayService.replay_state(
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=789,
        cutoff=ReplayCutoff(),
        projection="all",
        limit=100,
        event_reader=_Reader(),
        upcaster_registry=registry,
    )

    assert state["execution"]["status"] == "COMPLETED"
    assert state["last_event_type"] == "execution.completed"
    assert state["upcaster_registry_digest"] == registry.digest()


@pytest.mark.asyncio
async def test_replay_service_resolves_payload_refs_with_adapter():
    from noetl.server.api.replay import (
        ReplayCutoff,
        ReplayPayloadResolution,
        ReplayService,
        replay_payload_references,
    )

    payload_ref = {
        "rows_ref": {
            "ref": "noetl://execution/123/result/frame/9",
            "meta": {
                "sha256": "payload-sha",
                "row_count": 2,
                "media_type": "application/vnd.apache.arrow.stream",
            },
        }
    }

    class _Reader:
        async def load_snapshot_seed(self, **kwargs):
            return None

        async def load_events(self, **kwargs):
            return [
                {
                    "event_id": 1,
                    "event_type": "frame.committed",
                    "aggregate_type": "frame",
                    "aggregate_id": "frame/9",
                    "stage_id": 7,
                    "payload_ref": payload_ref,
                    "meta": {"row_count": 2},
                    "execution_id": kwargs["execution_id"],
                }
            ]

    class _Resolver:
        def __init__(self):
            self.references = []

        async def resolve_payload_ref(self, reference):
            self.references.append(reference)
            return ReplayPayloadResolution(
                ref=reference["rows_ref"]["ref"],
                resolved=True,
                checksum="a" * 64,
                size_bytes=128,
                row_count=2,
                value_type="list",
            )

    resolver = _Resolver()
    state = await ReplayService.replay_state(
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
        cutoff=ReplayCutoff(),
        projection="all",
        limit=100,
        event_reader=_Reader(),
        resolve_payloads=True,
        payload_resolver=resolver,
    )

    references = replay_payload_references(state)
    assert len(references) == 2
    assert references[0]["scope"] == "execution"
    assert references[1]["scope"] == "frame"
    assert resolver.references == [payload_ref]
    assert state["payload_resolution"] == [
        {
            "scope": "execution",
            "event_id": 1,
            "reference_summary": {
                "sha256": "payload-sha",
                "schema_digest": None,
                "row_count": 2,
                "media_type": "application/vnd.apache.arrow.stream",
                "ref": "noetl://execution/123/result/frame/9",
            },
            "resolution": {
                "ref": "noetl://execution/123/result/frame/9",
                "resolved": True,
                "checksum": "a" * 64,
                "size_bytes": 128,
                "row_count": 2,
                "value_type": "list",
                "error": None,
            },
        },
        {
            "scope": "frame",
            "frame_id": "9",
            "event_id": 1,
            "reference_summary": {
                "sha256": "payload-sha",
                "schema_digest": None,
                "row_count": 2,
                "media_type": "application/vnd.apache.arrow.stream",
                "ref": "noetl://execution/123/result/frame/9",
            },
            "resolution": {
                "ref": "noetl://execution/123/result/frame/9",
                "resolved": True,
                "checksum": "a" * 64,
                "size_bytes": 128,
                "row_count": 2,
                "value_type": "list",
                "error": None,
            },
        },
    ]
    assert state["payload_resolution_summary"] == {
        "total": 2,
        "resolved": 2,
        "unresolved": 0,
        "unique_refs": 1,
        "all_resolved": True,
        "checksum": state["payload_resolution_summary"]["checksum"],
    }
    assert len(state["payload_resolution_summary"]["checksum"]) == 64


def test_replay_payload_resolution_summary_reports_unresolved_refs():
    from noetl.server.api.replay import replay_payload_resolution_summary

    summary = replay_payload_resolution_summary(
        [
            {"resolution": {"ref": "noetl://payload/1", "resolved": True}},
            {"resolution": {"ref": "noetl://payload/2", "resolved": False}},
            {"resolution": {"ref": "noetl://payload/1", "resolved": True}},
        ]
    )

    assert summary["total"] == 3
    assert summary["resolved"] == 2
    assert summary["unresolved"] == 1
    assert summary["unique_refs"] == 2
    assert summary["all_resolved"] is False
    assert len(summary["checksum"]) == 64


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


@pytest.mark.asyncio
async def test_replay_service_uses_configured_event_reader():
    from noetl.server.api.replay import ReplayCutoff, ReplayService

    class _Reader:
        def __init__(self):
            self.after_event_id = None

        async def load_snapshot_seed(self, **kwargs):
            return None

        async def load_events(self, **kwargs):
            self.after_event_id = kwargs["after_event_id"]
            return [
                {
                    "event_id": 1,
                    "event_type": "execution.completed",
                    "status": "COMPLETED",
                    "execution_id": kwargs["execution_id"],
                }
            ]

    reader = _Reader()
    previous_reader = ReplayService.event_reader
    ReplayService.configure_event_reader(reader)
    try:
        state = await ReplayService.replay_state(
            tenant_id="tenant-a",
            organization_id="org-a",
            execution_id=123,
            cutoff=ReplayCutoff(),
            projection="all",
            limit=100,
        )
    finally:
        ReplayService.configure_event_reader(previous_reader)

    assert reader.after_event_id is None
    assert state["execution"]["status"] == "COMPLETED"
    assert set(state["projection_checksums"]) == {
        "execution",
        "stages",
        "frames",
        "commands",
        "business_objects",
        "loops",
    }


@pytest.mark.asyncio
async def test_replay_service_ignores_snapshot_with_mismatched_upcaster_digest():
    from noetl.core.replay import EventUpcasterRegistry
    from noetl.server.api.replay import ReplayCutoff, ReplayService
    from noetl.server.api.replay.service import ReplaySnapshotSeed, fold_replay_state

    stale_state = fold_replay_state(
        [
            {
                "event_id": 1,
                "event_type": "execution.failed",
                "status": "FAILED",
                "execution_id": 123,
            }
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
        upcaster_registry_digest="stale-digest",
    )

    class _Reader:
        def __init__(self):
            self.after_event_id = None

        async def load_snapshot_seed(self, **kwargs):
            return ReplaySnapshotSeed(
                aggregate_id="execution/123/all",
                aggregate_type="replay_state",
                version=1,
                checksum=stale_state["checksum"],
                state=stale_state,
                meta={},
            )

        async def load_events(self, **kwargs):
            self.after_event_id = kwargs["after_event_id"]
            return [
                {
                    "event_id": 1,
                    "event_type": "execution.started",
                    "status": "RUNNING",
                    "execution_id": kwargs["execution_id"],
                },
                {
                    "event_id": 2,
                    "event_type": "execution.completed",
                    "status": "COMPLETED",
                    "execution_id": kwargs["execution_id"],
                },
            ]

    reader = _Reader()
    registry = EventUpcasterRegistry()

    state = await ReplayService.replay_state(
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
        cutoff=ReplayCutoff(),
        projection="all",
        limit=100,
        event_reader=reader,
        upcaster_registry=registry,
    )

    assert reader.after_event_id is None
    assert "replay_snapshot" not in state
    assert state["event_count"] == 2
    assert state["execution"]["status"] == "COMPLETED"
    assert state["upcaster_registry_digest"] == registry.digest()


@pytest.mark.asyncio
async def test_postgres_replay_reader_uses_snapshot_seed_for_time_cutoff(monkeypatch):
    import noetl.server.api.replay.event_reader as event_reader_module

    from noetl.server.api.replay import ReplayCutoff
    from noetl.server.api.replay.event_reader import PostgresReplayEventReader

    cutoff_time = datetime(2026, 5, 20, 4, 30, tzinfo=timezone.utc)

    class _Cursor:
        def __init__(self, conn):
            self.conn = conn
            self.kind = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, params=None):
            self.conn.calls.append((query, list(params or [])))
            if "information_schema.columns" in query:
                self.kind = "columns"
            elif "MAX(event_id)" in query:
                self.kind = "time_cutoff"
            elif "FROM noetl.projection_snapshot" in query:
                self.kind = "snapshot"
            else:  # pragma: no cover - catches unexpected SQL shape
                raise AssertionError(query)

        async def fetchall(self):
            assert self.kind == "columns"
            return [
                {"column_name": "tenant_id"},
                {"column_name": "organization_id"},
                {"column_name": "event_time"},
            ]

        async def fetchone(self):
            if self.kind == "time_cutoff":
                return {"cutoff_event_id": 10}
            if self.kind == "snapshot":
                return {
                    "aggregate_id": "execution/123/all",
                    "aggregate_type": "replay_state",
                    "version": 7,
                    "snapshot": {"event_count": 7},
                    "checksum": "abc",
                    "meta": {"projection_code_version": "test"},
                }
            raise AssertionError(self.kind)

    class _Conn:
        def __init__(self):
            self.calls = []

        def cursor(self, **_kwargs):
            return _Cursor(self)

    class _ConnCtx:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    conn = _Conn()
    monkeypatch.setattr(event_reader_module, "get_pool_connection", lambda: _ConnCtx(conn))

    seed = await PostgresReplayEventReader().load_snapshot_seed(
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
        projection="all",
        cutoff=ReplayCutoff(as_of_time=cutoff_time),
    )

    assert seed is not None
    assert seed.version == 7
    time_query, time_params = conn.calls[1]
    snapshot_query, snapshot_params = conn.calls[2]
    assert "event_time <= %s" in time_query
    assert time_params == [123, "tenant-a", "org-a", cutoff_time]
    assert "version <= %s" in snapshot_query
    assert snapshot_params == [
        "tenant-a",
        "org-a",
        "replay_state",
        "execution/123/all",
        10,
    ]


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


def test_stage_projection_checksum_matches_live_rows_and_replayed_state():
    from noetl.server.api.replay import (
        fold_replay_state,
        normalize_live_stage_projection,
        normalize_replayed_stage_projection,
        stage_projection_checksum,
    )

    events = [
        {
            "event_id": 60,
            "event_type": "stage.opened",
            "aggregate_type": "stage",
            "aggregate_id": "stage/7",
            "status": "OPEN",
            "node_name": "fetch_patients",
            "meta": {
                "kind": "loop",
                "parent_stage_id": "6",
                "loop_event_id": "loop-1",
            },
        },
        {
            "event_id": 61,
            "event_type": "stage.closed",
            "aggregate_type": "stage",
            "aggregate_id": "stage/7",
            "status": "COMPLETED",
            "node_name": "fetch_patients",
            "meta": {
                "frame_count": 3,
                "row_count": 150,
                "events_emitted": 6,
                "failed_count": 1,
            },
        },
    ]
    state = fold_replay_state(
        events,
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
    )
    live_rows = normalize_live_stage_projection(
        [
            {
                "stage_id": 7,
                "status": "COMPLETED",
                "kind": "loop",
                "step_name": "fetch_patients",
                "parent_stage_id": "6",
                "loop_event_id": "loop-1",
                "opened_event_id": 60,
                "closed_event_id": 61,
                "frame_count": 3,
                "row_count": 150,
                "events_emitted": 6,
                "failed_count": 1,
                "last_event_id": 61,
            }
        ]
    )
    replayed_rows = normalize_replayed_stage_projection(state)

    assert replayed_rows == live_rows
    assert stage_projection_checksum(replayed_rows) == stage_projection_checksum(live_rows)


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


def test_loop_projection_checksum_matches_live_rows_and_replayed_state():
    from noetl.server.api.replay import (
        fold_replay_state,
        loop_projection_checksum,
        normalize_live_loop_projection,
        normalize_replayed_loop_projection,
    )

    events = [
        {
            "event_id": 40,
            "event_type": "stage.opened",
            "node_name": "fetch_patients",
            "meta": {"loop_id": "loop-1", "total": 3},
        },
        {
            "event_id": 41,
            "event_type": "command.completed",
            "node_name": "fetch_patients",
            "meta": {"loop_id": "loop-1"},
        },
        {
            "event_id": 42,
            "event_type": "command.failed",
            "node_name": "fetch_patients",
            "meta": {"loop_id": "loop-1"},
        },
        {
            "event_id": 43,
            "event_type": "loop.done",
            "node_name": "fetch_patients",
            "meta": {"loop_id": "loop-1"},
        },
    ]
    state = fold_replay_state(
        events,
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
    )
    live_rows = normalize_live_loop_projection(
        [
            {
                "loop_id": "loop-1",
                "step_name": "fetch_patients",
                "total": 3,
                "done": 1,
                "failed": 1,
                "completed": True,
                "last_event_id": 43,
            }
        ]
    )
    replayed_rows = normalize_replayed_loop_projection(state)

    assert replayed_rows == live_rows
    assert loop_projection_checksum(replayed_rows) == loop_projection_checksum(live_rows)


def test_execution_projection_checksum_matches_live_rows_and_replayed_state():
    from noetl.server.api.replay import (
        execution_projection_checksum,
        fold_replay_state,
        normalize_live_execution_projection,
        normalize_replayed_execution_projection,
    )

    payload_ref = {
        "uri": "noetl://tenant/tenant-a/org/org-a/payloads/sha256/final",
        "sha256": "final",
        "media_type": "application/json",
    }
    events = [
        {
            "event_id": 50,
            "event_type": "execution.started",
            "status": "RUNNING",
            "node_name": "start",
        },
        {
            "event_id": 51,
            "event_type": "command.completed",
            "status": "COMPLETED",
            "node_name": "fetch",
            "payload_ref": payload_ref,
        },
        {
            "event_id": 52,
            "event_type": "execution.completed",
            "status": "COMPLETED",
            "node_name": "end",
        },
    ]
    state = fold_replay_state(
        events,
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
        upcaster_registry_digest="digest-a",
    )
    live_rows = normalize_live_execution_projection(
        [
            {
                "execution_id": 123,
                "tenant_id": "tenant-a",
                "organization_id": "org-a",
                "projection": "all",
                "status": "COMPLETED",
                "last_node_name": "end",
                "event_count": 3,
                "last_event_id": 52,
                "last_event_type": "execution.completed",
                "payload_refs": [{"event_id": 51, "reference": payload_ref}],
                "upcaster_registry_digest": "digest-a",
            }
        ]
    )
    replayed_rows = normalize_replayed_execution_projection(state)

    assert replayed_rows == live_rows
    assert execution_projection_checksum(replayed_rows) == execution_projection_checksum(live_rows)


def test_replay_projection_checksum_bundle_includes_all_surfaces():
    from noetl.server.api.replay import (
        business_object_projection_checksum,
        command_projection_checksum,
        execution_projection_checksum,
        fold_replay_state,
        frame_projection_checksum,
        loop_projection_checksum,
        normalize_replayed_business_object_projection,
        normalize_replayed_command_projection,
        normalize_replayed_execution_projection,
        normalize_replayed_frame_projection,
        normalize_replayed_loop_projection,
        normalize_replayed_stage_projection,
        replay_projection_checksum_bundle,
        stage_projection_checksum,
    )

    state = fold_replay_state(
        [
            {"event_id": 1, "event_type": "execution.started", "status": "RUNNING"},
            {
                "event_id": 2,
                "event_type": "stage.opened",
                "aggregate_type": "stage",
                "aggregate_id": "stage/7",
                "status": "OPEN",
                "node_name": "stage",
            },
            {
                "event_id": 3,
                "event_type": "frame.dispatched",
                "aggregate_type": "frame",
                "aggregate_id": "frame/9",
                "stage_id": 7,
                "command_id": 11,
            },
            {
                "event_id": 4,
                "event_type": "command.claimed",
                "command_id": 11,
                "stage_id": 7,
                "worker_id": "worker-a",
            },
            {
                "event_id": 5,
                "event_type": "patient.created",
                "aggregate_type": "business_object",
                "aggregate_id": "patient/p-1",
                "meta": {"business_object": {"state": {"risk": "low"}}},
            },
            {
                "event_id": 6,
                "event_type": "loop.done",
                "node_name": "stage",
                "meta": {"loop_id": "loop-1"},
            },
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
    )

    assert replay_projection_checksum_bundle(state) == {
        "execution": execution_projection_checksum(
            normalize_replayed_execution_projection(state)
        ),
        "stages": stage_projection_checksum(normalize_replayed_stage_projection(state)),
        "frames": frame_projection_checksum(normalize_replayed_frame_projection(state)),
        "commands": command_projection_checksum(
            normalize_replayed_command_projection(state)
        ),
        "business_objects": business_object_projection_checksum(
            normalize_replayed_business_object_projection(state)
        ),
        "loops": loop_projection_checksum(normalize_replayed_loop_projection(state)),
    }


def test_projection_checksum_parity_report_compares_adapter_bundles():
    from noetl.server.api.replay import (
        fold_replay_state,
        live_projection_checksum_bundle,
        normalize_replayed_business_object_projection,
        normalize_replayed_command_projection,
        normalize_replayed_execution_projection,
        normalize_replayed_frame_projection,
        normalize_replayed_loop_projection,
        normalize_replayed_stage_projection,
        projection_checksum_parity_report,
    )

    state = fold_replay_state(
        [
            {"event_id": 1, "event_type": "execution.started", "status": "RUNNING"},
            {
                "event_id": 2,
                "event_type": "stage.opened",
                "aggregate_type": "stage",
                "aggregate_id": "stage/7",
                "status": "OPEN",
                "node_name": "stage",
            },
            {
                "event_id": 3,
                "event_type": "frame.dispatched",
                "aggregate_type": "frame",
                "aggregate_id": "frame/9",
                "stage_id": 7,
                "command_id": 11,
            },
            {
                "event_id": 4,
                "event_type": "command.claimed",
                "command_id": 11,
                "stage_id": 7,
                "worker_id": "worker-a",
            },
            {
                "event_id": 5,
                "event_type": "patient.created",
                "aggregate_type": "business_object",
                "aggregate_id": "patient/p-1",
                "meta": {"business_object": {"state": {"risk": "low"}}},
            },
            {
                "event_id": 6,
                "event_type": "loop.done",
                "node_name": "stage",
                "meta": {"loop_id": "loop-1"},
            },
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
    )
    live_bundle = live_projection_checksum_bundle(
        execution_rows=normalize_replayed_execution_projection(state),
        stage_rows=normalize_replayed_stage_projection(state),
        frame_rows=normalize_replayed_frame_projection(state),
        command_rows=normalize_replayed_command_projection(state),
        business_object_rows=normalize_replayed_business_object_projection(state),
        loop_rows=normalize_replayed_loop_projection(state),
    )

    report = projection_checksum_parity_report(
        replayed=state["projection_checksums"],
        live=live_bundle,
    )

    assert report["matched"] is True
    assert all(surface["matched"] for surface in report["surfaces"].values())

    diverged_live_bundle = {**live_bundle, "frames": "0" * 64}
    diverged_report = projection_checksum_parity_report(
        replayed=state["projection_checksums"],
        live=diverged_live_bundle,
    )
    assert diverged_report["matched"] is False
    assert diverged_report["surfaces"]["frames"] == {
        "replayed": state["projection_checksums"]["frames"],
        "live": "0" * 64,
        "matched": False,
    }
