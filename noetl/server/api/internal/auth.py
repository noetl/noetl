"""
Service-account bearer-token auth dependency for ``/api/internal/*``.

The system worker pool's K8s ServiceAccount mounts a Secret containing
the expected token; the pod env exposes it as
``NOETL_INTERNAL_API_TOKEN``.  The pool's playbooks send it as
``Authorization: Bearer <token>`` on every internal API call.

User playbooks (user worker pools) don't have the secret; their
requests fail the dependency with 403.

If ``NOETL_INTERNAL_API_TOKEN`` is unset in the server env, the
dependency rejects everything with 503 (mis-configured server).  This
is intentional — we do NOT want a "permissive when unconfigured"
default for a privileged API surface.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, status

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

_TOKEN_ENV = "NOETL_INTERNAL_API_TOKEN"


def _load_expected_token() -> str | None:
    value = os.getenv(_TOKEN_ENV)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


async def require_internal_api_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """FastAPI dependency that gates ``/api/internal/*`` routes.

    Raises:
        HTTPException(503) if the server has no ``NOETL_INTERNAL_API_TOKEN``
            configured.  This is treated as a server misconfiguration —
            the internal API exists but no token has been set up.
        HTTPException(403) if the request lacks a valid Bearer token.
    """

    expected = _load_expected_token()
    if expected is None:
        logger.warning(
            "Internal API called but %s is not set; rejecting with 503.",
            _TOKEN_ENV,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Internal API not configured: {_TOKEN_ENV} env var unset on "
                "the server.  Set it to the system worker pool's ServiceAccount "
                "token before calling /api/internal/* endpoints."
            ),
        )

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal API requires Authorization header with Bearer token.",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal API requires 'Bearer <token>' Authorization scheme.",
        )

    # Constant-time comparison — never use ``==`` on secrets.
    if not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid service-account token for /api/internal/*.",
        )
