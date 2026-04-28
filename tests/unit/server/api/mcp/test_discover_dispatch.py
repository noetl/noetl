"""Tests for the MCP discovery dispatch helper.

Covers both strategies:

- ``refresh_via`` agent dispatch (returns ``status='started'`` and an
  ``execution_id``).
- direct ``tools_list_url`` fetch with diff + re-register.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from noetl.server.api.mcp.service import dispatch_discover


class _CatalogEntryStub(BaseModel):
    catalog_id: str
    path: str
    version: int
    kind: str
    payload: dict[str, Any] | None = None
    content: str | None = None


class _FakeCatalogService:
    def __init__(self, entry: _CatalogEntryStub):
        self.entry = entry

    async def fetch_entry(self, *, path: str, version: Any):
        return self.entry


def _mcp_entry(*, lifecycle: dict[str, str] | None = None,
               discovery: dict[str, str] | None = None,
               tools: list[dict[str, str]] | None = None) -> _CatalogEntryStub:
    spec: dict[str, Any] = {}
    if lifecycle:
        spec["lifecycle"] = lifecycle
    if discovery:
        spec["discovery"] = discovery
    if tools is not None:
        spec["tools"] = tools
    return _CatalogEntryStub(
        catalog_id="100",
        path="mcp/kubernetes",
        version=3,
        kind="Mcp",
        payload={"metadata": {"name": "kubernetes"}, "spec": spec},
    )


# ---------------------------------------------------------------------------
# Strategy 1 -- refresh_via agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_via_dispatches_agent_and_returns_started():
    entry = _mcp_entry(discovery={"refresh_via": "agents/k8s/discover"})
    captured: dict[str, Any] = {}

    async def fake_execute(*, path: str, workload: dict[str, Any]) -> str:
        captured["path"] = path
        captured["workload"] = workload
        return "exec-77"

    async def unused_fetch(_: str) -> str:  # pragma: no cover -- agent path skips it
        raise AssertionError("fetch_url should not be called for refresh_via")

    async def unused_register(**_: Any) -> dict[str, Any]:  # pragma: no cover
        raise AssertionError("register should not be called for refresh_via")

    response = await dispatch_discover(
        catalog_service=_FakeCatalogService(entry),
        execute_callable=fake_execute,
        fetch_url_callable=unused_fetch,
        register_callable=unused_register,
        path="mcp/kubernetes",
        version="latest",
        force=False,
    )

    assert response.status == "started"
    assert response.strategy == "agent"
    assert response.execution_id == "exec-77"
    assert captured["path"] == "agents/k8s/discover"
    assert captured["workload"]["mcp_resource"]["path"] == "mcp/kubernetes"


# ---------------------------------------------------------------------------
# Strategy 2 -- direct tools_list_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_fetch_re_registers_when_tool_list_changes():
    entry = _mcp_entry(
        discovery={"tools_list_url": "http://kubernetes-mcp-server.mcp.svc/tools"},
        tools=[{"name": "pods_list_in_namespace"}],
    )
    captured: dict[str, Any] = {}

    async def fake_fetch(url: str) -> str:
        captured["url"] = url
        return json.dumps(
            {"tools": [
                {"name": "pods_list_in_namespace"},
                {"name": "namespaces_list"},
            ]}
        )

    async def fake_register(*, content: str, resource_type: str) -> dict[str, Any]:
        captured["content"] = content
        captured["resource_type"] = resource_type
        return {"version": 4}

    async def unused_execute(**_: Any) -> str:  # pragma: no cover
        raise AssertionError("execute should not be called in direct strategy")

    response = await dispatch_discover(
        catalog_service=_FakeCatalogService(entry),
        execute_callable=unused_execute,
        fetch_url_callable=fake_fetch,
        register_callable=fake_register,
        path="mcp/kubernetes",
        version="latest",
        force=False,
    )

    assert response.status == "updated"
    assert response.strategy == "direct"
    assert response.mcp_version_old == 3
    assert response.mcp_version_new == 4
    assert response.tool_count_before == 1
    assert response.tool_count_after == 2
    # The newly-registered YAML should contain both tool names.
    assert "namespaces_list" in captured["content"]
    assert captured["resource_type"] == "mcp"


@pytest.mark.asyncio
async def test_direct_fetch_does_not_re_register_when_tool_list_unchanged():
    entry = _mcp_entry(
        discovery={"tools_list_url": "http://kubernetes-mcp-server.mcp.svc/tools"},
        tools=[{"name": "pods_list_in_namespace"}],
    )

    async def fake_fetch(_: str) -> str:
        return json.dumps({"tools": [{"name": "pods_list_in_namespace"}]})

    async def fail_register(**_: Any) -> dict[str, Any]:
        raise AssertionError("register should not fire when nothing changed")

    response = await dispatch_discover(
        catalog_service=_FakeCatalogService(entry),
        execute_callable=lambda **_: "noop",  # type: ignore[arg-type]
        fetch_url_callable=fake_fetch,
        register_callable=fail_register,
        path="mcp/kubernetes",
        version="latest",
        force=False,
    )

    assert response.status == "started"  # i.e. queried but no version bump
    assert response.mcp_version_new is None
    assert response.tool_count_before == 1
    assert response.tool_count_after == 1


@pytest.mark.asyncio
async def test_direct_fetch_force_re_registers_even_without_diff():
    entry = _mcp_entry(
        discovery={"tools_list_url": "http://kubernetes-mcp-server.mcp.svc/tools"},
        tools=[{"name": "pods_list_in_namespace"}],
    )
    captured: dict[str, Any] = {}

    async def fake_fetch(_: str) -> str:
        return json.dumps({"tools": [{"name": "pods_list_in_namespace"}]})

    async def fake_register(*, content: str, resource_type: str) -> dict[str, Any]:
        captured["resource_type"] = resource_type
        return {"version": 5}

    response = await dispatch_discover(
        catalog_service=_FakeCatalogService(entry),
        execute_callable=lambda **_: "noop",  # type: ignore[arg-type]
        fetch_url_callable=fake_fetch,
        register_callable=fake_register,
        path="mcp/kubernetes",
        version="latest",
        force=True,
    )

    assert response.status == "updated"
    assert response.mcp_version_new == 5
    assert captured["resource_type"] == "mcp"


@pytest.mark.asyncio
async def test_direct_fetch_502s_on_invalid_json():
    entry = _mcp_entry(
        discovery={"tools_list_url": "http://kubernetes-mcp-server.mcp.svc/tools"},
    )

    async def fake_fetch(_: str) -> str:
        return "<html>not json</html>"

    async def unused_execute(**_: Any) -> str:  # pragma: no cover
        return "noop"

    async def unused_register(**_: Any) -> dict[str, Any]:  # pragma: no cover
        return {}

    with pytest.raises(HTTPException) as info:
        await dispatch_discover(
            catalog_service=_FakeCatalogService(entry),
            execute_callable=unused_execute,
            fetch_url_callable=fake_fetch,
            register_callable=unused_register,
            path="mcp/kubernetes",
            version="latest",
            force=False,
        )
    assert info.value.status_code == 502


@pytest.mark.asyncio
async def test_422_when_neither_strategy_configured():
    entry = _mcp_entry(discovery=None)

    async def unused(*_: Any, **__: Any) -> Any:  # pragma: no cover
        raise AssertionError("not reached")

    with pytest.raises(HTTPException) as info:
        await dispatch_discover(
            catalog_service=_FakeCatalogService(entry),
            execute_callable=unused,
            fetch_url_callable=unused,
            register_callable=unused,
            path="mcp/kubernetes",
            version="latest",
            force=False,
        )
    assert info.value.status_code == 422
