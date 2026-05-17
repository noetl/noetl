from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def test_frame_routes_are_registered():
    from noetl.server.api import frames

    app = FastAPI()
    app.include_router(frames.router, prefix="/api")
    client = TestClient(app)

    response = client.post(
        "/api/stages/not-an-int/frames/claim",
        json={"worker_id": "worker-a"},
    )

    assert response.status_code == 422


def test_frame_request_contracts_validate_bounds():
    from pydantic import ValidationError

    from noetl.server.api.frames import FrameClaimRequest, FrameCommitRequest

    claim = FrameClaimRequest(worker_id="worker-a", requested_count=2)
    assert claim.requested_count == 2
    assert claim.lease_seconds == 60

    commit = FrameCommitRequest(
        worker_id="worker-a",
        status="COMPLETED",
        row_count=10,
        output_ref={"uri": "noetl://payloads/sha256/abc", "sha256": "abc"},
    )
    assert commit.output_ref["sha256"] == "abc"

    try:
        FrameClaimRequest(worker_id="worker-a", requested_count=0)
    except ValidationError as exc:
        assert "greater than or equal to 1" in str(exc)
    else:
        raise AssertionError("requested_count=0 should fail validation")


def test_frame_commit_result_keeps_event_result_shape():
    from noetl.server.api.frames import endpoint

    result = endpoint._frame_commit_result(
        status="FAILED",
        output_ref={"uri": "noetl://payloads/sha256/abc", "sha256": "abc"},
        error="one or more frame rows failed",
    )

    assert result == {
        "status": "FAILED",
        "reference": {"uri": "noetl://payloads/sha256/abc", "sha256": "abc"},
        "context": {"error": "one or more frame rows failed"},
    }
    assert set(result) <= {"status", "reference", "context"}


@pytest.mark.asyncio
async def test_insert_frame_event_sets_stream_version_and_checksum(monkeypatch):
    from noetl.server.api.frames import endpoint

    class Cursor:
        def __init__(self):
            self.calls = []
            self.insert_params = None
            self.fetchone_rows = [{"catalog_id": 6}, {"next_version": 4}]

        async def execute(self, query, params=None):
            self.calls.append((query, params))
            if "INSERT INTO noetl.event" in query:
                self.insert_params = params

        async def fetchone(self):
            return self.fetchone_rows.pop(0)

    async def next_event_id(cur):  # noqa: ARG001
        return 123

    monkeypatch.setattr(endpoint, "_next_snowflake_id", next_event_id)
    cur = Cursor()

    event = await endpoint._insert_frame_event(
        cur,
        frame={
            "frame_id": 9,
            "stage_id": 8,
            "execution_id": 7,
            "tenant_id": "tenant-a",
            "organization_id": "org-a",
            "step_name": "fetch_rows",
        },
        event_type="frame.committed",
        status="COMPLETED",
        worker_id="worker-a",
        result={
            "status": "COMPLETED",
            "reference": {"uri": "noetl://payloads/sha256/abc", "sha256": "abc"},
        },
        meta_extra={"row_count": 10},
    )

    assert event["event_id"] == 123
    assert event["stream_version"] == 4
    assert event["envelope_checksum"] == cur.insert_params["envelope_checksum"]
    assert cur.insert_params["stream_version"] == 4
    assert cur.insert_params["catalog_id"] == 6
    assert cur.insert_params["stream_id"] == "execution/7/stage/8"
    assert cur.insert_params["aggregate_id"] == "frame/9"
    assert len(cur.insert_params["envelope_checksum"]) == 64
    assert "stream_version" in cur.calls[-1][0]
    assert "envelope_checksum" in cur.calls[-1][0]


@pytest.mark.asyncio
async def test_frame_event_mirror_is_opt_in(monkeypatch):
    from noetl.server.api.frames import endpoint

    calls = []

    class _FakePublisher:
        async def publish_event(self, event):
            calls.append(event)

    monkeypatch.setattr(endpoint, "_event_mirror_publisher", _FakePublisher())
    monkeypatch.delenv("NOETL_EVENT_MIRROR_ENABLED", raising=False)

    await endpoint._mirror_frame_events([{"event_id": 1, "event_type": "frame.dispatched"}])

    assert calls == []


@pytest.mark.asyncio
async def test_frame_event_mirror_publishes_when_enabled(monkeypatch):
    from noetl.server.api.frames import endpoint

    calls = []

    class _FakePublisher:
        async def publish_event(self, event):
            calls.append(event)

    monkeypatch.setattr(endpoint, "_event_mirror_publisher", _FakePublisher())
    monkeypatch.setenv("NOETL_EVENT_MIRROR_ENABLED", "true")

    await endpoint._mirror_frame_events([{"event_id": 1, "event_type": "frame.dispatched"}])

    assert calls == [{"event_id": 1, "event_type": "frame.dispatched"}]
