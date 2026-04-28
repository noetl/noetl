"""FastAPI endpoints for MCP lifecycle / discovery / ui_schema.

Routes are mounted into the main API router (``noetl.server.api.router``)
which is itself prefixed at ``/api``; therefore the decorators here use
paths *without* a leading ``/api`` so the final URL stays at
``/api/mcp/{path}/lifecycle/{verb}`` and friends.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from fastapi.responses import JSONResponse

from noetl.core.logger import setup_logger

from . import schema as mcp_schema
from . import service as mcp_service

logger = setup_logger(__name__, include_location=True)


router = APIRouter(prefix="", tags=["mcp"])


# Maximum size we'll accept from a discovery URL fetch. Twenty kilobytes is
# more than any reasonable MCP `tools/list` response while still preventing
# a hostile server from streaming endless data into the worker.
_DISCOVERY_FETCH_MAX_BYTES = 20 * 1024
_DISCOVERY_FETCH_TIMEOUT_SECONDS = 10


# ---------------------------------------------------------------------------
# Dependency wiring -- lazily resolves the catalog service + execute helper.
# Keeping these as injectables makes the module testable without standing up
# the full server wiring; the test suite passes mocks.
# ---------------------------------------------------------------------------


def _get_catalog_service():
    """Return the CatalogService class.

    `CatalogService` exposes its lookup methods (``fetch_entry``, ``get``,
    ``register_resource``) as ``@staticmethod``, so the "service" here is
    really just the class itself. Returning the class lets callers do
    ``service.fetch_entry(...)`` interchangeably with the rest of the
    server code without instantiating anything.
    """
    from noetl.server.api.catalog import CatalogService

    return CatalogService


async def _execute_via_core(*, path: str, workload: dict[str, Any]) -> str:
    """Default execute helper: delegate to ``noetl.server.api.core.execute``."""
    # Late imports keep the module importable without pulling the full broker
    # graph at server-startup time.
    from noetl.server.api.core.execution import execute as core_execute
    from noetl.server.api.core.models import ExecuteRequest

    request = ExecuteRequest(path=path, payload=workload or {})
    response = await core_execute(request)

    payload: Optional[dict[str, Any]] = None
    if hasattr(response, "model_dump"):
        payload = response.model_dump()
    elif isinstance(response, dict):
        payload = response
    elif isinstance(response, JSONResponse):
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None

    if isinstance(payload, dict) and payload.get("execution_id"):
        return str(payload["execution_id"])

    raise HTTPException(
        status_code=500,
        detail=f"agent dispatch for {path} returned no execution_id",
    )


async def _fetch_url_default(url: str) -> str:
    """Fetcher for direct discovery -- validates the URL, caps the response.

    SSRF mitigation: refuses anything other than http/https, blocks
    requests targeting loopback, link-local, multicast, or RFC 1918
    addresses unless the URL host explicitly resolves to a kind/cluster
    namespace (the most common case for kubernetes-native MCP servers).
    DNS resolution and the actual HTTP fetch both run off the event
    loop so a slow resolver can't stall the server.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"discovery URL must be http or https; got '{parsed.scheme}'",
        )
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="discovery URL missing host")

    if not await _host_is_safe_for_discovery(host):
        raise HTTPException(
            status_code=400,
            detail=(
                f"discovery URL host '{host}' resolves to a blocked address range "
                "(loopback / link-local / multicast). Use the in-cluster service "
                "DNS or a routable public host instead."
            ),
        )

    def _read() -> str:
        with urllib.request.urlopen(  # noqa: S310 -- validated above
            url,
            timeout=_DISCOVERY_FETCH_TIMEOUT_SECONDS,
        ) as response:
            data = response.read(_DISCOVERY_FETCH_MAX_BYTES + 1)
        if len(data) > _DISCOVERY_FETCH_MAX_BYTES:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"discovery URL response exceeded "
                    f"{_DISCOVERY_FETCH_MAX_BYTES} bytes"
                ),
            )
        return data.decode("utf-8")

    return await asyncio.get_running_loop().run_in_executor(None, _read)


async def _host_is_safe_for_discovery(host: str) -> bool:
    """Best-effort SSRF guard. Allows in-cluster service DNS by name.

    Async because DNS resolution is delegated to
    ``loop.getaddrinfo`` so a slow resolver can't stall other handlers.

    We let through:

    - hostnames ending in `.svc`, `.svc.cluster.local`, `.cluster.local`
      (typical kubernetes service DNS — operators target the same MCP
      pod via these names).
    - any host that, after DNS resolution, lies outside the
      loopback / link-local / multicast / private ranges.

    We block:

    - explicit IPs in loopback (127.0.0.0/8, ::1), link-local
      (169.254.0.0/16, fe80::/10), multicast (224.0.0.0/4),
      RFC 1918 (10/8, 172.16/12, 192.168/16) when the URL is an IP
      literal and *not* one of the in-cluster DNS suffixes above.
      Cluster DNS typically resolves to a private 10.x or 172.x
      address, but the hostname-based allowlist short-circuits the
      check before we hit that branch.
    """
    suffix_allowlist = (
        ".svc",
        ".svc.cluster.local",
        ".cluster.local",
    )
    lowered = host.lower()
    if any(lowered.endswith(suffix) for suffix in suffix_allowlist):
        return True

    try:
        loop = asyncio.get_running_loop()
        # loop.getaddrinfo runs the lookup in a thread/executor so the
        # event loop stays responsive. Returns the same tuple shape as
        # socket.getaddrinfo.
        infos = await loop.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    seen_ok = False
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return False
        if ip.is_private:
            return False
        seen_ok = True
    return seen_ok


async def _register_default(*, content: str, resource_type: str) -> dict[str, Any]:
    """Default catalog register helper used by direct-discovery."""
    from noetl.server.api.catalog import CatalogService

    return await CatalogService.register_resource(
        content=content,
        resource_type=resource_type,
    )


# ---------------------------------------------------------------------------
# Lifecycle dispatch
# ---------------------------------------------------------------------------


@router.post(
    "/mcp/{path:path}/lifecycle/{verb}",
    response_model=mcp_schema.McpLifecycleResponse,
    summary="Dispatch a lifecycle verb on a registered Mcp resource",
)
async def post_lifecycle_verb(
    path: str = Path(..., description="Mcp catalog path"),
    verb: str = Path(..., description="Lifecycle verb (deploy / restart / etc.)"),
    body: mcp_schema.McpLifecycleRequest = Body(default_factory=mcp_schema.McpLifecycleRequest),
    catalog_service=Depends(_get_catalog_service),
):
    cleaned_verb = mcp_schema.coerce_lifecycle_verb(verb)
    try:
        return await mcp_service.dispatch_lifecycle(
            catalog_service=catalog_service,
            execute_callable=_execute_via_core,
            path=path,
            verb=cleaned_verb,
            version=body.version,
            workload_overrides=body.workload_overrides,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("MCP lifecycle dispatch failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@router.post(
    "/mcp/{path:path}/discover",
    response_model=mcp_schema.McpDiscoverResponse,
    summary="Refresh the tool list of a registered Mcp resource",
)
async def post_discover(
    path: str = Path(..., description="Mcp catalog path"),
    body: mcp_schema.McpDiscoverRequest = Body(default_factory=mcp_schema.McpDiscoverRequest),
    catalog_service=Depends(_get_catalog_service),
):
    try:
        return await mcp_service.dispatch_discover(
            catalog_service=catalog_service,
            execute_callable=_execute_via_core,
            fetch_url_callable=_fetch_url_default,
            register_callable=_register_default,
            path=path,
            version=body.version,
            force=body.force,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("MCP discover failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# UI schema
# ---------------------------------------------------------------------------


@router.get(
    "/catalog/{path:path}/ui_schema",
    response_model=mcp_schema.UiSchemaResponse,
    summary="Inferred workload form for a Playbook / Agent / Mcp resource",
)
async def get_ui_schema(
    path: str = Path(..., description="Catalog path"),
    version: Any = "latest",
    catalog_service=Depends(_get_catalog_service),
):
    try:
        return await mcp_service.build_ui_schema(catalog_service, path, version)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("ui_schema build failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
