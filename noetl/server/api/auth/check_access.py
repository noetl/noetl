"""Server-side ``check_playbook_access`` enforcement.

This module is the noetl server's analogue to the
``api_integration/auth0/check_playbook_access`` playbook. The playbook
flow stays as the externally-callable contract (the gateway invokes it
via ``POST /api/auth/check-access`` and the GUI uses it to grey out
forbidden buttons), but the same authorisation decision must also be
enforceable from inside the FastAPI app for deployments that do not put
a gateway in front of noetl (local kind, private GKE).

We hit the same ``auth.sessions`` + ``auth.playbook_permissions`` tables
the playbook queries — granting execute permission via the GUI / SQL /
playbook flow keeps a single source of truth. The implementation here
is a fast SQL path with a small TTL cache, not a recursive playbook
dispatch, so the per-request cost is one Postgres round-trip on cache
miss.

Configuration (environment variables, all optional):

- ``NOETL_AUTH_ENFORCEMENT_MODE`` — ``enforce`` | ``advisory`` | ``skip``
  (default: ``skip`` so existing local-dev keeps working without a flag
  flip; production deploys should set this to ``enforce``).
- ``NOETL_AUTH_CACHE_TTL_SECONDS`` — TTL on the in-memory decision cache
  (default 30s). Cache is keyed on ``(session_token, playbook_path,
  action)``; flip a user's permission and they re-authorize within the
  TTL window.
- ``NOETL_AUTH_SESSION_HEADER`` — alternative header name for the
  session token (default ``X-Session-Token``). The standard
  ``Authorization: Bearer <token>`` header is always honoured.

Modes:

- ``enforce``: a denied check raises ``HTTPException(403)``. This is
  the only mode that actually blocks requests.
- ``advisory``: a denied check is logged and surfaced via the
  ``AccessDecision`` return value (callers can stamp a header on the
  response) but the request still proceeds. Useful while the
  permission table is being populated, so we can audit who *would*
  have been blocked before flipping to enforce.
- ``skip``: the function short-circuits with ``allowed=True`` and never
  hits the database. The default; lets you bring up a local kind
  cluster with no auth tables at all.
"""

from __future__ import annotations

import asyncio
import enum
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, Request

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class EnforcementMode(str, enum.Enum):
    """How a denied auth decision should be handled.

    ``str`` mixin keeps the values readable in logs/configs and lets
    them be compared to the raw env-var string without explicit casting.
    """

    ENFORCE = "enforce"
    ADVISORY = "advisory"
    SKIP = "skip"

    @classmethod
    def parse(cls, raw: Optional[str]) -> "EnforcementMode":
        if not raw:
            return cls.SKIP
        cleaned = str(raw).strip().lower()
        for member in cls:
            if member.value == cleaned:
                return member
        logger.warning(
            "unrecognised NOETL_AUTH_ENFORCEMENT_MODE=%r; falling back to skip",
            raw,
        )
        return cls.SKIP


@dataclass(frozen=True)
class AuthEnforcementSettings:
    """Frozen configuration loaded from env or the test harness.

    Frozen so a stray write inside a hot-path doesn't end up flipping
    enforcement mode for the next request.
    """

    mode: EnforcementMode = EnforcementMode.SKIP
    cache_ttl_seconds: float = 30.0
    session_header: str = "X-Session-Token"
    db_connection_string: Optional[str] = None  # None => default conn

    @classmethod
    def from_env(cls) -> "AuthEnforcementSettings":
        ttl_raw = os.environ.get("NOETL_AUTH_CACHE_TTL_SECONDS")
        try:
            ttl = float(ttl_raw) if ttl_raw is not None else 30.0
        except ValueError:
            logger.warning(
                "invalid NOETL_AUTH_CACHE_TTL_SECONDS=%r; falling back to 30s",
                ttl_raw,
            )
            ttl = 30.0
        # An empty NOETL_AUTH_SESSION_HEADER would otherwise produce a
        # confusing "or : <token>" segment in the 401 detail, and
        # invalidate the fallback header lookup entirely. Treat blank /
        # whitespace-only as "fall back to the default".
        session_header = (
            os.environ.get("NOETL_AUTH_SESSION_HEADER", "X-Session-Token") or ""
        ).strip()
        if not session_header:
            session_header = "X-Session-Token"
        return cls(
            mode=EnforcementMode.parse(os.environ.get("NOETL_AUTH_ENFORCEMENT_MODE")),
            cache_ttl_seconds=max(0.0, ttl),
            session_header=session_header,
            db_connection_string=os.environ.get("NOETL_AUTH_DB_CONNECTION_STRING"),
        )


def load_enforcement_settings() -> AuthEnforcementSettings:
    """Public entry point for the FastAPI dep wiring."""
    return AuthEnforcementSettings.from_env()


@dataclass
class AccessDecision:
    """Result of a single ``check_playbook_access`` evaluation.

    ``allowed`` is the only field a hot-path needs. ``reason``,
    ``user_id``, and ``email`` are populated when available and are
    primarily for logging / response headers.
    """

    allowed: bool
    reason: str = ""
    user_id: Optional[int] = None
    email: Optional[str] = None
    mode: EnforcementMode = EnforcementMode.SKIP
    cached: bool = False


@dataclass
class _CacheEntry:
    decision: AccessDecision
    expires_at: float


class _DecisionCache:
    """Tiny TTL cache keyed on ``(session_token, playbook_path, action)``.

    Lock is per-process; we don't expect contention to be a problem at
    the request rates this handles, and a single ``asyncio.Lock`` keeps
    the implementation portable across deployment shapes (multi-worker
    Uvicorn, single-process kind, etc.).
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str, str], _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: tuple[str, str, str]) -> Optional[AccessDecision]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                # Lazy expiry — drop the entry and report a miss.
                self._store.pop(key, None)
                return None
            decision = AccessDecision(
                allowed=entry.decision.allowed,
                reason=entry.decision.reason,
                user_id=entry.decision.user_id,
                email=entry.decision.email,
                mode=entry.decision.mode,
                cached=True,
            )
            return decision

    async def set(
        self,
        key: tuple[str, str, str],
        decision: AccessDecision,
        ttl_seconds: float,
    ) -> None:
        if ttl_seconds <= 0:
            return
        async with self._lock:
            self._store[key] = _CacheEntry(
                decision=decision,
                expires_at=time.monotonic() + ttl_seconds,
            )

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()


# Module-level cache. Reset by tests via ``check_access._cache.clear()``.
_cache = _DecisionCache()


def extract_session_token(
    request: Request, settings: AuthEnforcementSettings
) -> Optional[str]:
    """Pull the session token from a FastAPI request.

    Tries (in order): ``Authorization: Bearer <token>``,
    ``Authorization: <token>`` (raw token), the configured
    ``settings.session_header``. Returns ``None`` if no token is
    present — callers in ``enforce`` mode treat that as a deny.
    """
    auth = request.headers.get("Authorization")
    if auth:
        stripped_auth = auth.strip()
        # Treat a bare Bearer scheme — with or without trailing
        # whitespace — as "no token". Accepting the literal string
        # "Bearer" as a raw token would cause a misleading DB lookup
        # and surface as a 403 ("invalid session") instead of the
        # 401 the missing-token path produces.
        if stripped_auth.lower() == "bearer":
            return None
        # Check the Bearer prefix on the unstripped value so we still
        # catch "Bearer    " (prefix-with-trailing-whitespace) before
        # falling back to raw-token handling.
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() or None
        # Some clients send the raw token in Authorization without the
        # Bearer prefix. Accept that form too — a 64-char opaque string
        # can't reasonably be confused with another scheme.
        return stripped_auth or None
    header_name = settings.session_header
    if header_name:
        token = request.headers.get(header_name)
        if token:
            token = token.strip()
            return token or None
    return None


async def _query_access(
    *,
    session_token: str,
    playbook_path: str,
    action: str,
    settings: AuthEnforcementSettings,
) -> AccessDecision:
    """Run the same SQL the check_playbook_access playbook does.

    Returns an ``AccessDecision`` populated from the database result.
    On any DB error we fail closed in enforce mode (caller maps to
    ``HTTPException(503)`` rather than silently allowing) — this branch
    raises so the wrapper can decide based on mode.
    """
    # Late import so importing this module doesn't pull psycopg into the
    # test path when we're stubbing the SQL layer.
    from noetl.core.common import get_async_db_connection
    from psycopg.rows import dict_row

    async with get_async_db_connection(
        connection_string=settings.db_connection_string,
    ) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                  s.user_id,
                  u.email
                FROM auth.sessions s
                JOIN auth.users u ON s.user_id = u.user_id
                WHERE s.session_token = %s
                  AND s.is_active = TRUE
                  AND s.expires_at > NOW()
                  AND u.is_active = TRUE
                LIMIT 1
                """,
                (session_token,),
            )
            session_row = await cur.fetchone()

            if not session_row:
                return AccessDecision(
                    allowed=False,
                    reason="invalid or expired session",
                    mode=settings.mode,
                )

            user_id = int(session_row["user_id"])
            email = str(session_row.get("email") or "")

            await cur.execute(
                """
                SELECT COUNT(*) > 0 AS has_permission
                FROM auth.user_roles ur
                JOIN auth.roles r ON ur.role_id = r.role_id
                JOIN auth.playbook_permissions pp ON r.role_id = pp.role_id
                WHERE ur.user_id = %s
                  AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
                  AND (
                    pp.playbook_path = %s
                    OR (pp.allow_pattern IS NOT NULL AND %s LIKE pp.allow_pattern)
                  )
                  AND (pp.deny_pattern IS NULL OR %s NOT LIKE pp.deny_pattern)
                  AND (
                    (%s = 'execute' AND pp.can_execute = TRUE)
                    OR (%s = 'view' AND pp.can_view = TRUE)
                    OR (%s = 'modify' AND pp.can_modify = TRUE)
                  )
                """,
                (
                    user_id,
                    playbook_path,
                    playbook_path,
                    playbook_path,
                    action,
                    action,
                    action,
                ),
            )
            perm_row = await cur.fetchone()
            allowed = bool(perm_row and perm_row.get("has_permission"))

            return AccessDecision(
                allowed=allowed,
                reason="granted" if allowed else "no matching playbook_permission",
                user_id=user_id,
                email=email,
                mode=settings.mode,
            )


async def check_playbook_access(
    *,
    request: Request,
    playbook_path: str,
    action: str = "execute",
    settings: Optional[AuthEnforcementSettings] = None,
) -> AccessDecision:
    """Authorise a request to dispatch ``playbook_path``.

    Returns an ``AccessDecision``. In ``enforce`` mode this raises
    ``HTTPException(403)`` on a denied result and ``HTTPException(401)``
    on a missing session token; the caller doesn't need to inspect
    ``allowed`` again. In ``advisory`` mode it returns the decision
    unchanged (so the caller can stamp a response header) but never
    blocks. In ``skip`` mode it short-circuits with ``allowed=True``
    and never touches the database.

    The TTL cache means hot paths (a GUI polling the same lifecycle
    status verb) only hit Postgres once per ``cache_ttl_seconds`` per
    ``(session_token, playbook_path, action)`` triple.
    """
    settings = settings or load_enforcement_settings()

    if settings.mode == EnforcementMode.SKIP:
        return AccessDecision(
            allowed=True,
            reason="enforcement skipped",
            mode=EnforcementMode.SKIP,
        )

    session_token = extract_session_token(request, settings)
    if not session_token:
        decision = AccessDecision(
            allowed=False,
            reason="missing session token",
            mode=settings.mode,
        )
        if settings.mode == EnforcementMode.ENFORCE:
            # Build the detail dynamically — only mention the fallback
            # header when one is actually configured. ``from_env``
            # normalises blank / whitespace values back to the default,
            # so this branch shouldn't fire in practice, but a stray
            # ``replace(settings, session_header="")`` from a test
            # harness should still produce a sensible message.
            detail = "missing session token; provide Authorization: Bearer <token>"
            fallback_header = (settings.session_header or "").strip()
            if fallback_header:
                detail += f" or {fallback_header}: <token>"
            raise HTTPException(status_code=401, detail=detail)
        logger.warning(
            "advisory: would deny dispatch of %s — missing session token",
            playbook_path,
        )
        return decision

    cache_key = (session_token, playbook_path, action)
    cached = await _cache.get(cache_key)
    if cached is not None:
        decision = cached
    else:
        try:
            decision = await _query_access(
                session_token=session_token,
                playbook_path=playbook_path,
                action=action,
                settings=settings,
            )
        except Exception as exc:
            logger.exception("auth check_playbook_access SQL failed")
            if settings.mode == EnforcementMode.ENFORCE:
                # Fail closed — better a 503 than silently waving through
                # a request because the auth tables are unreachable.
                raise HTTPException(
                    status_code=503,
                    detail="auth backend unavailable",
                ) from exc
            return AccessDecision(
                allowed=False,
                reason=f"auth backend unavailable: {exc}",
                mode=settings.mode,
            )
        await _cache.set(cache_key, decision, settings.cache_ttl_seconds)

    if not decision.allowed and settings.mode == EnforcementMode.ENFORCE:
        raise HTTPException(
            status_code=403,
            detail=f"access denied: {decision.reason}",
        )
    if not decision.allowed and settings.mode == EnforcementMode.ADVISORY:
        logger.warning(
            "advisory: would deny dispatch of %s by user_id=%s (%s) — %s",
            playbook_path,
            decision.user_id,
            decision.email,
            decision.reason,
        )

    return decision
