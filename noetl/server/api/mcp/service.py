"""MCP lifecycle / discovery service helpers.

Wraps catalog lookups, agent dispatch, and tool-list refresh so the
endpoints stay thin. All public helpers are async to fit the existing
catalog/service layer.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import yaml as _yaml

from fastapi import HTTPException

from noetl.core.logger import setup_logger

from . import schema as mcp_schema
from .ui_schema import infer_ui_schema

logger = setup_logger(__name__, include_location=True)


# ---------------------------------------------------------------------------
# Catalog accessors
# ---------------------------------------------------------------------------


async def fetch_mcp_resource(catalog_service, path: str, version: Any) -> dict[str, Any]:
    """Look up an Mcp catalog entry by path + version.

    Returns the parsed YAML payload as a dict so callers can read
    spec.lifecycle / spec.discovery / spec.runtime without re-parsing.
    Raises HTTPException(404) when the entry is absent or not an Mcp.
    """
    entry = await _fetch_entry(catalog_service, path, version)
    kind = (entry.get("kind") or "").lower()
    if kind not in ("mcp",):
        raise HTTPException(
            status_code=400,
            detail=f"resource '{path}' is kind='{kind}', expected 'mcp'",
        )

    payload = entry.get("payload") or _parse_yaml_string(entry.get("content"))
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail=f"Mcp resource '{path}' has unparseable payload",
        )
    # Shallow-copy before mutating — the parsed payload may come from the
    # CatalogService LRU cache and re-using it directly would leak the
    # synthetic ``_catalog`` key into subsequent reads (and worse, into
    # any future re-registration that round-trips the dict back to YAML).
    resource_payload = dict(payload)
    resource_payload["_catalog"] = {
        "catalog_id": entry.get("catalog_id"),
        "path": entry.get("path"),
        "version": entry.get("version"),
        "kind": entry.get("kind"),
    }
    return resource_payload


async def fetch_any_resource(catalog_service, path: str, version: Any) -> dict[str, Any]:
    """Look up any catalog entry (Playbook / Agent / Mcp) for ui_schema."""
    return await _fetch_entry(catalog_service, path, version)


async def _fetch_entry(catalog_service, path: str, version: Any) -> dict[str, Any]:
    """Look up a catalog entry and normalize the result to a plain dict.

    The real ``CatalogService`` exposes its lookups as static methods —
    most callers pass the class itself rather than an instance. The
    canonical method is ``fetch_entry(path=..., version=...)`` which
    returns a ``CatalogEntry`` Pydantic model. We probe for
    ``fetch_entry`` first (the contract the rest of the server uses) and
    fall back to ``get`` if a future refactor moves the surface around.
    Tests can pass an arbitrary object that exposes either method.
    """
    if catalog_service is None:
        raise HTTPException(status_code=503, detail="catalog service unavailable")

    fetcher = getattr(catalog_service, "fetch_entry", None) or getattr(
        catalog_service, "get", None
    )
    if fetcher is None:
        logger.warning(
            "catalog service does not expose fetch_entry/get for %s@%s",
            path,
            version,
        )
        raise HTTPException(status_code=503, detail="catalog service unavailable")

    requested_version = "latest" if version in (None, "", "latest") else version
    try:
        entry = await fetcher(path=path, version=requested_version)
    except HTTPException:
        # Catalog service may decide to surface its own typed HTTP errors —
        # let them propagate unchanged so the client sees the right status.
        raise
    except Exception:  # pragma: no cover -- service-layer error surface varies
        # Real DB/network/IO problems are 503, not 404. Masking them as
        # "not found" makes incidents look like benign client errors.
        logger.exception(
            "catalog lookup failed for %s@%s; mapping to 503",
            path,
            requested_version,
        )
        raise HTTPException(
            status_code=503,
            detail="catalog service unavailable",
        )

    if not entry:
        # Explicit absence -- reserved 404 case.
        raise HTTPException(
            status_code=404,
            detail=f"resource not found: {path}@{requested_version}",
        )

    return _normalize_entry(entry)


def _normalize_entry(entry: Any) -> dict[str, Any]:
    """Return a plain dict view of a catalog entry.

    Pydantic models go through ``model_dump`` (which serialises nested
    models too); dicts pass through unchanged; anything else gets a
    ``__dict__`` snapshot as a last resort. Test fakes that yield dicts
    directly stay supported.
    """
    if isinstance(entry, dict):
        return entry
    if hasattr(entry, "model_dump"):
        dumped = entry.model_dump()
        if isinstance(dumped, dict):
            return dumped
    fallback = getattr(entry, "__dict__", None)
    if isinstance(fallback, dict):
        return dict(fallback)
    raise HTTPException(
        status_code=500,
        detail=f"catalog entry has unsupported type: {type(entry).__name__}",
    )


# ---------------------------------------------------------------------------
# Lifecycle dispatch
# ---------------------------------------------------------------------------


async def dispatch_lifecycle(
    *,
    catalog_service,
    execute_callable,
    path: str,
    verb: str,
    version: Any,
    workload_overrides: Optional[dict[str, Any]] = None,
    auth_check_callable=None,
) -> mcp_schema.McpLifecycleResponse:
    """Resolve resource.lifecycle.{verb} -> Agent path and dispatch.

    `execute_callable(path: str, workload: dict) -> str` is injected so
    this stays testable without standing up the full /api/execute
    machinery in unit tests. Pass a thin wrapper around the existing
    execute service in production wiring.

    `auth_check_callable(playbook_path: str, action: str) -> awaitable`
    is the optional authorisation hook. The endpoint wires it to the
    server-side ``check_playbook_access`` flow, which in ``enforce``
    mode may raise ``HTTPException`` with one of:

    - ``401`` — no session token on the request
    - ``403`` — the session is valid but lacks the requested permission
    - ``503`` — the auth backend (Postgres) is unreachable; we fail
      closed rather than silently waving the request through

    Any of those propagate out of ``dispatch_lifecycle`` unchanged and
    we never reach ``execute_callable``. In ``advisory`` / ``skip``
    modes (or when no callable is provided) the dispatch proceeds
    unchanged, preserving compatibility with existing test harnesses.
    """
    resource = await fetch_mcp_resource(catalog_service, path, version)
    spec = resource.get("spec") or {}
    lifecycle = spec.get("lifecycle") or {}
    agent_path = lifecycle.get(verb)
    if not agent_path:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Mcp resource '{path}' does not declare lifecycle verb '{verb}' "
                f"(known verbs: {sorted(lifecycle.keys())})"
            ),
        )

    if auth_check_callable is not None:
        # The callable is responsible for raising HTTPException(403) on
        # an enforce-mode deny. We invoke it here — after the lifecycle
        # path has been resolved — so authorisation is checked against
        # the actual playbook the dispatcher would run, not the URL the
        # client sent. That distinction matters: granting execute on
        # `automation/agents/kubernetes/lifecycle/deploy` should gate
        # the deploy verb regardless of which Mcp resource exposed it.
        await auth_check_callable(playbook_path=str(agent_path), action="execute")

    workload = {
        "mcp_resource": {
            "path": path,
            "version": resource["_catalog"]["version"],
            "spec": spec,
            "metadata": resource.get("metadata") or {},
        },
        "verb": verb,
    }
    # workload_overrides is a convenience for adding caller-specific values
    # to the dispatched agent's workload (e.g. a ticket id or a forced
    # image tag). It is NOT a way to overwrite the resource's own
    # identity: blocking ``mcp_resource`` and ``verb`` here keeps audit
    # trails and downstream dispatch logic consistent with the catalog
    # entry that was actually resolved.
    if workload_overrides:
        reserved = {"mcp_resource", "verb"}
        clobbered = sorted(k for k in workload_overrides if k in reserved)
        if clobbered:
            raise HTTPException(
                status_code=422,
                detail=(
                    "workload_overrides cannot override reserved fields: "
                    f"{clobbered}"
                ),
            )
        workload.update(workload_overrides)

    execution_id = await execute_callable(path=agent_path, workload=workload)

    return mcp_schema.McpLifecycleResponse(
        status="started",
        verb=verb,
        mcp_path=path,
        mcp_version=int(resource["_catalog"]["version"]),
        agent_path=str(agent_path),
        execution_id=str(execution_id),
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


async def dispatch_discover(
    *,
    catalog_service,
    execute_callable,
    fetch_url_callable,
    register_callable,
    path: str,
    version: Any,
    force: bool,
    auth_check_callable=None,
) -> mcp_schema.McpDiscoverResponse:
    """Refresh the Mcp resource's tools list.

    Strategy 1 -- agent: when spec.discovery.refresh_via is set, dispatch
    that Agent playbook and return immediately. The agent is responsible
    for re-registering the catalog entry.

    Strategy 2 -- direct: when spec.discovery.tools_list_url is set,
    fetch the URL, parse `tools`, diff against current spec.tools, and
    re-register a new catalog version when changed (or always when
    force=True).
    """
    resource = await fetch_mcp_resource(catalog_service, path, version)
    spec = resource.get("spec") or {}
    discovery = spec.get("discovery") or {}
    refresh_via = discovery.get("refresh_via")
    tools_list_url = discovery.get("tools_list_url")

    # Authorisation is performed against the *agent* playbook path when
    # discovery dispatches one (matches lifecycle's behaviour); for the
    # direct URL strategy we authorise against the resource's own
    # catalog path instead — there's no separate playbook to grant
    # execute on, so the resource path is the only stable handle.
    if auth_check_callable is not None:
        if refresh_via:
            await auth_check_callable(playbook_path=str(refresh_via), action="execute")
        elif tools_list_url:
            await auth_check_callable(playbook_path=str(path), action="execute")

    if refresh_via:
        execution_id = await execute_callable(
            path=refresh_via,
            workload={
                "mcp_resource": {
                    "path": path,
                    "version": resource["_catalog"]["version"],
                    "spec": spec,
                    "metadata": resource.get("metadata") or {},
                },
                "verb": "discover",
                "force": force,
            },
        )
        return mcp_schema.McpDiscoverResponse(
            status="started",
            mcp_path=path,
            mcp_version_old=int(resource["_catalog"]["version"]),
            mcp_version_new=None,
            strategy="agent",
            execution_id=str(execution_id),
        )

    if tools_list_url:
        body = await fetch_url_callable(tools_list_url)
        try:
            payload = json.loads(body) if isinstance(body, (str, bytes)) else body
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"discovery URL returned non-JSON body: {exc}",
            ) from exc

        new_tools = payload.get("tools") if isinstance(payload, dict) else None
        if not isinstance(new_tools, list):
            raise HTTPException(
                status_code=502,
                detail="discovery URL must return {'tools': [...]} JSON",
            )

        old_tools = spec.get("tools") if isinstance(spec.get("tools"), list) else []
        old_count = len(old_tools)
        new_count = len(new_tools)
        changed = force or _tool_lists_differ(old_tools, new_tools)

        new_version = None
        if changed:
            spec_copy = dict(spec)
            spec_copy["tools"] = new_tools
            updated_doc = dict(resource)
            updated_doc.pop("_catalog", None)
            updated_doc["spec"] = spec_copy
            new_yaml = _yaml.safe_dump(updated_doc, sort_keys=False)
            register = await register_callable(content=new_yaml, resource_type="mcp")
            new_version = int(register.get("version"))

        return mcp_schema.McpDiscoverResponse(
            status="updated" if changed else "started",
            mcp_path=path,
            mcp_version_old=int(resource["_catalog"]["version"]),
            mcp_version_new=new_version,
            strategy="direct",
            execution_id=None,
            tool_count_before=old_count,
            tool_count_after=new_count,
        )

    raise HTTPException(
        status_code=422,
        detail=(
            f"Mcp resource '{path}' has no discovery configured "
            "(set spec.discovery.refresh_via or spec.discovery.tools_list_url)"
        ),
    )


# ---------------------------------------------------------------------------
# UI schema inference
# ---------------------------------------------------------------------------


async def build_ui_schema(catalog_service, path: str, version: Any) -> mcp_schema.UiSchemaResponse:
    entry = await fetch_any_resource(catalog_service, path, version)
    payload = entry.get("payload") or _parse_yaml_string(entry.get("content")) or {}
    metadata = payload.get("metadata") or {}
    fields = infer_ui_schema(entry.get("content") or "")
    return mcp_schema.UiSchemaResponse(
        path=str(entry.get("path") or path),
        version=int(entry.get("version") or 0),
        kind=str(entry.get("kind") or "").lower(),
        title=metadata.get("name") if isinstance(metadata, dict) else None,
        description_markdown=metadata.get("description") if isinstance(metadata, dict) else None,
        exposed_in_ui=bool((metadata or {}).get("exposed_in_ui", False)) if isinstance(metadata, dict) else False,
        fields=fields,
        generated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_yaml_string(content: Any) -> Optional[dict[str, Any]]:
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        parsed = _yaml.safe_load(content)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _tool_lists_differ(old_tools: list[Any], new_tools: list[Any]) -> bool:
    def _normalize(items: list[Any]) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for item in items:
            if isinstance(item, dict):
                out.append((str(item.get("name") or ""), str(item.get("title") or "")))
            else:
                out.append((str(item), ""))
        return sorted(out)

    return _normalize(old_tools) != _normalize(new_tools)
