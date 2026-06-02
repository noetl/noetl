"""
Tests for the ``/api/internal/*`` route surface (noetl/noetl#658).

Focuses on:

- Auth gate (``require_internal_api_token``) — accepts valid token,
  rejects missing / wrong scheme / wrong value / unconfigured server.
- Schema validation — request bodies parse the expected shapes; bad
  shapes get 422.

The DB-touching service layer (outbox claim/mark, events project) is
validated end-to-end on kind via the system playbook smoke test in
noetl/ai-meta#46 Phase 2 — not here, because spinning up a real
Postgres just to exercise SQL is heavyweight for this round.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from noetl.server.api.internal import auth, schema
from noetl.server.api.internal.endpoint import router as internal_router


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app with just the internal router mounted.

    Avoids the cost of bringing up the full noetl.server.api package
    for tests focused on internal routes.
    """

    app = FastAPI()
    app.include_router(internal_router)
    return app


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_gate_rejects_when_server_token_unset(monkeypatch):
    monkeypatch.delenv("NOETL_INTERNAL_API_TOKEN", raising=False)
    with pytest.raises(HTTPException) as excinfo:
        await auth.require_internal_api_token(authorization="Bearer something")
    assert excinfo.value.status_code == 503
    assert "NOETL_INTERNAL_API_TOKEN" in excinfo.value.detail


@pytest.mark.asyncio
async def test_auth_gate_rejects_blank_token_env(monkeypatch):
    monkeypatch.setenv("NOETL_INTERNAL_API_TOKEN", "   ")
    with pytest.raises(HTTPException) as excinfo:
        await auth.require_internal_api_token(authorization="Bearer x")
    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_auth_gate_rejects_missing_authorization(monkeypatch):
    monkeypatch.setenv("NOETL_INTERNAL_API_TOKEN", "secret-123")
    with pytest.raises(HTTPException) as excinfo:
        await auth.require_internal_api_token(authorization=None)
    assert excinfo.value.status_code == 403
    assert "Bearer" in excinfo.value.detail


@pytest.mark.asyncio
async def test_auth_gate_rejects_non_bearer_scheme(monkeypatch):
    monkeypatch.setenv("NOETL_INTERNAL_API_TOKEN", "secret-123")
    with pytest.raises(HTTPException) as excinfo:
        await auth.require_internal_api_token(authorization="Basic secret-123")
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_auth_gate_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("NOETL_INTERNAL_API_TOKEN", "secret-123")
    with pytest.raises(HTTPException) as excinfo:
        await auth.require_internal_api_token(authorization="Bearer wrong-token")
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_auth_gate_accepts_valid_token(monkeypatch):
    monkeypatch.setenv("NOETL_INTERNAL_API_TOKEN", "secret-123")
    # Should not raise.
    await auth.require_internal_api_token(authorization="Bearer secret-123")


def test_endpoint_returns_403_without_auth(monkeypatch):
    monkeypatch.setenv("NOETL_INTERNAL_API_TOKEN", "secret-123")
    app = _build_app()
    client = TestClient(app)
    response = client.get("/api/internal/outbox/pending-count")
    assert response.status_code == 403
    assert "Bearer" in response.json()["detail"]


def test_endpoint_returns_503_when_token_unset(monkeypatch):
    monkeypatch.delenv("NOETL_INTERNAL_API_TOKEN", raising=False)
    app = _build_app()
    client = TestClient(app)
    response = client.get(
        "/api/internal/outbox/pending-count",
        headers={"Authorization": "Bearer anything"},
    )
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_outbox_claim_request_defaults_limit():
    req = schema.OutboxClaimRequest()
    assert req.limit == 100


def test_outbox_claim_request_clamps_min():
    with pytest.raises(ValueError):
        schema.OutboxClaimRequest(limit=0)


def test_outbox_claim_request_clamps_max():
    with pytest.raises(ValueError):
        schema.OutboxClaimRequest(limit=1001)


def test_outbox_mark_published_requires_ids():
    with pytest.raises(ValueError):
        schema.OutboxMarkPublishedRequest(outbox_ids=[])


def test_outbox_mark_failed_requires_outbox_id_and_error():
    with pytest.raises(ValueError):
        schema.OutboxMarkFailedRequest(error="boom")  # missing outbox_id
    with pytest.raises(ValueError):
        schema.OutboxMarkFailedRequest(outbox_id=42)  # missing error


def test_events_project_request_requires_events():
    with pytest.raises(ValueError):
        schema.EventsProjectRequest(events=[])


def test_event_envelope_allows_extra_fields():
    """The projector must tolerate unknown fields from emitters."""
    envelope = schema.EventEnvelope(
        event_id=12345,
        event_type="step.exit",
        extra_field="from-the-future",  # type: ignore[call-arg]
    )
    assert envelope.event_id == 12345
    # extra field is preserved via model_config={"extra": "allow"}
    assert envelope.model_dump().get("extra_field") == "from-the-future"


def test_event_envelope_requires_event_id():
    with pytest.raises(ValueError):
        schema.EventEnvelope(event_type="step.exit")


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_all_five_routes_registered():
    """Sanity check: all five internal routes registered with correct paths."""
    paths = {(route.path, frozenset(route.methods)) for route in internal_router.routes}
    expected = {
        ("/api/internal/outbox/claim", frozenset({"POST"})),
        ("/api/internal/outbox/mark-published", frozenset({"POST"})),
        ("/api/internal/outbox/mark-failed", frozenset({"POST"})),
        ("/api/internal/outbox/pending-count", frozenset({"GET"})),
        ("/api/internal/events/project", frozenset({"POST"})),
    }
    assert expected.issubset(paths), f"missing: {expected - paths}"
