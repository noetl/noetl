"""Unit tests for the noetl-side check_playbook_access enforcement.

The DB-backed SQL query is patched out — these tests focus on the mode
gating, header extraction, cache, and the FastAPI HTTPException shapes
the dispatcher relies on. A separate integration test exercises the
real auth.sessions / auth.playbook_permissions tables.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Optional

import pytest
from fastapi import HTTPException

from noetl.server.api.auth import check_access as ca


class _StubRequest:
    """Minimal fastapi.Request stand-in exposing only ``headers``."""

    def __init__(self, headers: Optional[dict[str, str]] = None) -> None:
        self.headers = headers or {}


def _settings(**overrides) -> ca.AuthEnforcementSettings:
    base = ca.AuthEnforcementSettings(
        mode=ca.EnforcementMode.ENFORCE,
        cache_ttl_seconds=0.0,  # Disable cache by default for deterministic tests.
        session_header="X-Session-Token",
        db_connection_string=None,
    )
    return replace(base, **overrides)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test starts (and ends) with an empty decision cache.

    Spin up a dedicated event loop and tear it down deterministically
    around each test instead of relying on ``asyncio.get_event_loop()``
    — on Python 3.12+ that helper either implicitly creates a loop and
    leaks it, or raises ``DeprecationWarning`` / ``RuntimeError``
    depending on the pytest-asyncio configuration. A try/finally
    around a fresh loop keeps the fixture portable across versions and
    avoids ``ResourceWarning: unclosed event loop`` noise on the
    synchronous header-extraction tests.
    """
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(ca._cache.clear())
        yield
        loop.run_until_complete(ca._cache.clear())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------


def test_extract_session_token_bearer():
    settings = _settings()
    req = _StubRequest({"Authorization": "Bearer abc.def.ghi"})
    assert ca.extract_session_token(req, settings) == "abc.def.ghi"


def test_extract_session_token_raw_authorization():
    settings = _settings()
    req = _StubRequest({"Authorization": "raw-token-no-scheme"})
    assert ca.extract_session_token(req, settings) == "raw-token-no-scheme"


def test_extract_session_token_custom_header():
    settings = _settings(session_header="X-Session-Token")
    req = _StubRequest({"X-Session-Token": "from-custom-header"})
    assert ca.extract_session_token(req, settings) == "from-custom-header"


def test_extract_session_token_missing():
    settings = _settings()
    req = _StubRequest({})
    assert ca.extract_session_token(req, settings) is None


def test_extract_session_token_empty_bearer_returns_none():
    """`Bearer ` prefix with no token must surface as no token, not the literal 'Bearer'."""
    settings = _settings()
    req = _StubRequest({"Authorization": "Bearer    "})
    assert ca.extract_session_token(req, settings) is None


def test_extract_session_token_bare_bearer_returns_none():
    """A bare `Authorization: Bearer` (no whitespace, no token) is no token, not literal 'Bearer'."""
    settings = _settings()
    assert ca.extract_session_token(_StubRequest({"Authorization": "Bearer"}), settings) is None
    assert ca.extract_session_token(_StubRequest({"Authorization": "  Bearer  "}), settings) is None
    # Case-insensitive — RFC 7235 makes the scheme case-insensitive.
    assert ca.extract_session_token(_StubRequest({"Authorization": "bearer"}), settings) is None
    assert ca.extract_session_token(_StubRequest({"Authorization": "BEARER"}), settings) is None


def test_settings_blank_session_header_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("NOETL_AUTH_SESSION_HEADER", "")
    s = ca.AuthEnforcementSettings.from_env()
    assert s.session_header == "X-Session-Token"

    monkeypatch.setenv("NOETL_AUTH_SESSION_HEADER", "   ")
    s = ca.AuthEnforcementSettings.from_env()
    assert s.session_header == "X-Session-Token"


# ---------------------------------------------------------------------------
# Mode gating — skip / advisory / enforce
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skip_mode_short_circuits_without_token_or_db():
    settings = _settings(mode=ca.EnforcementMode.SKIP)
    req = _StubRequest({})  # No token at all.
    decision = await ca.check_playbook_access(
        request=req,
        playbook_path="any/playbook",
        action="execute",
        settings=settings,
    )
    assert decision.allowed is True
    assert decision.mode == ca.EnforcementMode.SKIP


@pytest.mark.asyncio
async def test_enforce_mode_missing_token_raises_401():
    settings = _settings(mode=ca.EnforcementMode.ENFORCE)
    req = _StubRequest({})
    with pytest.raises(HTTPException) as exc:
        await ca.check_playbook_access(
            request=req,
            playbook_path="any/playbook",
            action="execute",
            settings=settings,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_advisory_mode_missing_token_returns_decision_without_raising():
    settings = _settings(mode=ca.EnforcementMode.ADVISORY)
    req = _StubRequest({})
    decision = await ca.check_playbook_access(
        request=req,
        playbook_path="any/playbook",
        action="execute",
        settings=settings,
    )
    assert decision.allowed is False
    assert decision.mode == ca.EnforcementMode.ADVISORY


# ---------------------------------------------------------------------------
# Mode gating — denied vs allowed via patched _query_access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_mode_denied_query_raises_403(monkeypatch):
    settings = _settings(mode=ca.EnforcementMode.ENFORCE)

    async def fake_query(**_kwargs):
        return ca.AccessDecision(
            allowed=False,
            reason="no matching playbook_permission",
            user_id=42,
            email="user@example.com",
            mode=ca.EnforcementMode.ENFORCE,
        )

    monkeypatch.setattr(ca, "_query_access", fake_query)
    req = _StubRequest({"Authorization": "Bearer tok"})

    with pytest.raises(HTTPException) as exc:
        await ca.check_playbook_access(
            request=req,
            playbook_path="restricted/playbook",
            action="execute",
            settings=settings,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_advisory_mode_denied_returns_decision_without_raising(monkeypatch):
    settings = _settings(mode=ca.EnforcementMode.ADVISORY)

    async def fake_query(**_kwargs):
        return ca.AccessDecision(
            allowed=False,
            reason="no matching playbook_permission",
            user_id=42,
            email="user@example.com",
            mode=ca.EnforcementMode.ADVISORY,
        )

    monkeypatch.setattr(ca, "_query_access", fake_query)
    req = _StubRequest({"Authorization": "Bearer tok"})

    decision = await ca.check_playbook_access(
        request=req,
        playbook_path="restricted/playbook",
        action="execute",
        settings=settings,
    )
    assert decision.allowed is False
    assert decision.mode == ca.EnforcementMode.ADVISORY


@pytest.mark.asyncio
async def test_enforce_mode_allowed_query_returns_decision(monkeypatch):
    settings = _settings(mode=ca.EnforcementMode.ENFORCE)

    async def fake_query(**_kwargs):
        return ca.AccessDecision(
            allowed=True,
            reason="granted",
            user_id=42,
            email="user@example.com",
            mode=ca.EnforcementMode.ENFORCE,
        )

    monkeypatch.setattr(ca, "_query_access", fake_query)
    req = _StubRequest({"Authorization": "Bearer tok"})

    decision = await ca.check_playbook_access(
        request=req,
        playbook_path="allowed/playbook",
        action="execute",
        settings=settings,
    )
    assert decision.allowed is True
    assert decision.user_id == 42


# ---------------------------------------------------------------------------
# Failure path — DB exception fails closed in enforce, open-with-deny in advisory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_mode_db_error_raises_503(monkeypatch):
    settings = _settings(mode=ca.EnforcementMode.ENFORCE)

    async def fake_query(**_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ca, "_query_access", fake_query)
    req = _StubRequest({"Authorization": "Bearer tok"})

    with pytest.raises(HTTPException) as exc:
        await ca.check_playbook_access(
            request=req,
            playbook_path="any/playbook",
            action="execute",
            settings=settings,
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_advisory_mode_db_error_returns_denied_decision(monkeypatch):
    settings = _settings(mode=ca.EnforcementMode.ADVISORY)

    async def fake_query(**_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ca, "_query_access", fake_query)
    req = _StubRequest({"Authorization": "Bearer tok"})

    decision = await ca.check_playbook_access(
        request=req,
        playbook_path="any/playbook",
        action="execute",
        settings=settings,
    )
    assert decision.allowed is False
    assert "auth backend unavailable" in decision.reason


# ---------------------------------------------------------------------------
# Cache hit short-circuits the SQL path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_query(monkeypatch):
    settings = _settings(
        mode=ca.EnforcementMode.ADVISORY,
        cache_ttl_seconds=60.0,
    )
    call_count = {"n": 0}

    async def fake_query(**_kwargs):
        call_count["n"] += 1
        return ca.AccessDecision(
            allowed=True,
            reason="granted",
            user_id=7,
            email="cache@example.com",
            mode=ca.EnforcementMode.ADVISORY,
        )

    monkeypatch.setattr(ca, "_query_access", fake_query)
    req = _StubRequest({"Authorization": "Bearer same-token"})

    first = await ca.check_playbook_access(
        request=req,
        playbook_path="cached/path",
        action="execute",
        settings=settings,
    )
    second = await ca.check_playbook_access(
        request=req,
        playbook_path="cached/path",
        action="execute",
        settings=settings,
    )
    assert first.allowed is True
    assert second.allowed is True
    assert second.cached is True
    assert call_count["n"] == 1  # second call hit the cache.


# ---------------------------------------------------------------------------
# EnforcementMode parse helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("enforce", ca.EnforcementMode.ENFORCE),
        ("ENFORCE", ca.EnforcementMode.ENFORCE),
        ("advisory", ca.EnforcementMode.ADVISORY),
        ("skip", ca.EnforcementMode.SKIP),
        (None, ca.EnforcementMode.SKIP),
        ("", ca.EnforcementMode.SKIP),
        ("nonsense", ca.EnforcementMode.SKIP),
    ],
)
def test_enforcement_mode_parse(raw, expected):
    assert ca.EnforcementMode.parse(raw) == expected
