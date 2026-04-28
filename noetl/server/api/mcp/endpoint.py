"""FastAPI endpoints for MCP lifecycle / discovery / ui_schema."""

from __future__ import annotations

import urllib.request
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from fastapi.responses import JSONResponse

from noetl.core.logger import setup_logger

from . import schema as mcp_schema
from . import service as mcp_service

logger = setup_logger(__name__, include_location=True)


router = APIRouter(prefix="", tags=["mcp"])


# ---------------------------------------------------------------------------
# Dependency wiring -- lazily resolves the catalog service + execute helper.
# Keeping these as injectables makes the module testable without standing up
# the full server wiring; the test suite passes mocks.
# ---------------------------------------------------------------------------


def _get_catalog_service():
    """Resolve the catalog service singleton."""
    # Late import to avoid pulling the full app graph during module import.
    from noetl.server.api.catalog import get_catalog_service

    return get_catalog_service()


async def _execute_via_core(*, path: str, workload: dict[str, Any]) -> str:
    """Default execute helper: delegate to the core /api/execute path."""
    # Late import keeps optional dependency on the broker subsystem.
    from noetl.server.api.core import execute_resource_default  # type: ignore[import-not-found]

    response = await execute_resource_default(path=path, workload=workload)
    if isinstance(response, dict) and response.get("execution_id"):
        return str(response["execution_id"])
    raise HTTPException(
        status_code=500,
        detail=f"agent dispatch for {path} returned no execution_id",
    )


async def _fetch_url_default(url: str) -> str:
    """Default URL fetcher used by direct-discovery."""
    # Network calls are kept synchronous via run_in_executor to avoid pulling
    # in a new HTTP client dependency for what should be a rare code path.
    import asyncio

    def _read() -> str:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 -- caller-controlled URL
            return response.read().decode("utf-8")

    return await asyncio.get_event_loop().run_in_executor(None, _read)


async def _register_default(*, content: str, resource_type: str) -> dict[str, Any]:
    """Default catalog register helper used by direct-discovery."""
    from noetl.server.api.catalog import get_catalog_service

    service = get_catalog_service()
    return await service.register(content=content, resource_type=resource_type)


# ---------------------------------------------------------------------------
# Lifecycle dispatch
# ---------------------------------------------------------------------------


@router.post(
    "/api/mcp/{path:path}/lifecycle/{verb}",
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
    "/api/mcp/{path:path}/discover",
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
    "/api/catalog/{path:path}/ui_schema",
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
