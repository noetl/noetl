from fastapi import FastAPI
from fastapi import HTTPException
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


def test_frame_event_meta_includes_command_lineage():
    from noetl.server.api.frames import endpoint

    meta = endpoint._event_meta(
        frame={"frame_id": 9, "stage_id": 8, "parent_frame_id": 6, "command_id": 7},
        worker_id="worker-a",
    )

    assert meta["frame_id"] == "9"
    assert meta["stage_id"] == "8"
    assert meta["parent_frame_id"] == "6"
    assert meta["command_id"] == "7"


def test_frame_response_includes_lineage_columns():
    from noetl.server.api.frames import endpoint

    response = endpoint._frame_response(
        {
            "frame_id": 9,
            "stage_id": 8,
            "execution_id": 7,
            "status": "COMPLETED",
            "parent_frame_id": 6,
            "command_id": 5,
            "claimed_event_id": 4,
            "terminal_event_id": 3,
        }
    )

    assert response["parent_frame_id"] == 6
    assert response["command_id"] == 5
    assert response["claimed_event_id"] == 4
    assert response["terminal_event_id"] == 3


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


class _CursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FrameEndpointConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self, row_factory=None):  # noqa: ARG002
        return _CursorCtx(self._cursor)

    async def commit(self):
        self.commits += 1


class _FrameEndpointCursor:
    def __init__(self, *, active_row=None, conflict_row=None):
        self._active_row = active_row
        self._conflict_row = conflict_row
        self.queries = []

    async def execute(self, query, params=None):
        self.queries.append((query, params))

    async def fetchone(self):
        query = self.queries[-1][0]
        if "SELECT execution_id, stage_id" in query:
            return {"execution_id": 7, "stage_id": 8}
        if "UPDATE noetl.frame" in query:
            return self._active_row
        if "SELECT frame_id, status, owner_worker, terminal_event_id" in query:
            return self._conflict_row
        raise AssertionError(f"Unexpected fetchone query: {query}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("previous_status", "expected_event_type"),
    [
        ("CLAIMED", "frame.started"),
        ("RUNNING", "frame.heartbeat"),
    ],
)
async def test_heartbeat_frame_separates_start_from_lease_extension(
    monkeypatch,
    previous_status,
    expected_event_type,
):
    from noetl.server.api.frames import endpoint
    from noetl.server.api.frames.schema import FrameHeartbeatRequest

    emitted = []
    cursor = _FrameEndpointCursor(
        active_row={
            "frame_id": 9,
            "stage_id": 8,
            "execution_id": 7,
            "status": "RUNNING",
            "previous_status": previous_status,
            "owner_worker": "worker-a",
            "tenant_id": "tenant-a",
            "organization_id": "org-a",
            "step_name": "fetch_rows",
            "lease_until": "later",
        }
    )
    conn = _FrameEndpointConn(cursor)

    async def insert_frame_event(_cur, **kwargs):  # noqa: ARG001
        emitted.append(kwargs)
        return {"event_id": 123, "event_type": kwargs["event_type"]}

    async def mirror_frame_events(_events):
        return None

    monkeypatch.setattr(endpoint, "get_pool_connection", lambda: _ConnCtx(conn))
    monkeypatch.setattr(endpoint, "_insert_frame_event", insert_frame_event)
    monkeypatch.setattr(endpoint, "_mirror_frame_events", mirror_frame_events)

    response = await endpoint.heartbeat_frame(
        9,
        FrameHeartbeatRequest(worker_id="worker-a", lease_seconds=30, status="RUNNING"),
    )

    assert response["status"] == "ok"
    assert response["frame"]["event_id"] == 123
    assert emitted[0]["event_type"] == expected_event_type
    assert conn.commits == 1


@pytest.mark.asyncio
async def test_commit_frame_rejects_duplicate_terminal_commit_without_event(monkeypatch):
    from noetl.server.api.frames import endpoint
    from noetl.server.api.frames.schema import FrameCommitRequest

    cursor = _FrameEndpointCursor(
        active_row=None,
        conflict_row={
            "frame_id": 9,
            "status": "COMPLETED",
            "owner_worker": "worker-a",
            "terminal_event_id": 77,
        },
    )
    conn = _FrameEndpointConn(cursor)

    async def unexpected_insert_frame_event(*_args, **_kwargs):
        raise AssertionError("duplicate terminal commit must not emit a new event")

    monkeypatch.setattr(endpoint, "get_pool_connection", lambda: _ConnCtx(conn))
    monkeypatch.setattr(endpoint, "_insert_frame_event", unexpected_insert_frame_event)

    with pytest.raises(HTTPException) as exc:
        await endpoint.commit_frame(
            9,
            FrameCommitRequest(worker_id="worker-a", status="COMPLETED", row_count=1),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "frame_already_terminal",
        "frame_id": 9,
        "status": "COMPLETED",
        "terminal_event_id": 77,
    }
    assert conn.commits == 0


@pytest.mark.asyncio
async def test_heartbeat_frame_rejects_terminal_frame_without_event(monkeypatch):
    from noetl.server.api.frames import endpoint
    from noetl.server.api.frames.schema import FrameHeartbeatRequest

    cursor = _FrameEndpointCursor(
        active_row=None,
        conflict_row={
            "frame_id": 9,
            "status": "FAILED",
            "owner_worker": "worker-a",
            "terminal_event_id": 78,
        },
    )

    async def unexpected_insert_frame_event(*_args, **_kwargs):
        raise AssertionError("terminal heartbeat must not emit a new event")

    monkeypatch.setattr(endpoint, "get_pool_connection", lambda: _ConnCtx(_FrameEndpointConn(cursor)))
    monkeypatch.setattr(endpoint, "_insert_frame_event", unexpected_insert_frame_event)

    with pytest.raises(HTTPException) as exc:
        await endpoint.heartbeat_frame(
            9,
            FrameHeartbeatRequest(worker_id="worker-a", lease_seconds=30, status="RUNNING"),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "frame_already_terminal"
    assert exc.value.detail["terminal_event_id"] == 78
