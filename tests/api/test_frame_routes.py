from fastapi import FastAPI
from fastapi.testclient import TestClient


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
