"""Tests for the lifecycle dispatch service helper."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from noetl.server.api.mcp.service import dispatch_lifecycle


class _CatalogEntryStub(BaseModel):
    """Minimal stand-in for noetl.server.api.catalog.CatalogEntry.

    Matches the fields the service actually reads (``catalog_id``,
    ``path``, ``version``, ``kind``, ``payload``, ``content``) so the
    Pydantic ``model_dump`` path through ``_normalize_entry`` is
    exercised the same way it would be in production.
    """

    catalog_id: str
    path: str
    version: int
    kind: str
    payload: dict[str, Any] | None = None
    content: str | None = None


class _FakeCatalogService:
    """Minimal stand-in implementing the fetch_entry contract."""

    def __init__(self, entry: _CatalogEntryStub | None = None):
        self.entry = entry

    async def fetch_entry(self, *, path: str, version: Any):  # noqa: D401
        return self.entry


@pytest.mark.asyncio
async def test_dispatch_resolves_lifecycle_to_agent_and_returns_execution_id():
    entry = _CatalogEntryStub(
        catalog_id="100",
        path="mcp/kubernetes",
        version=4,
        kind="Mcp",
        payload={
            "metadata": {"name": "kubernetes"},
            "spec": {
                "lifecycle": {
                    "deploy": "automation/agents/kubernetes/lifecycle/deploy",
                },
            },
        },
    )
    captured: dict[str, Any] = {}

    async def fake_execute(*, path: str, workload: dict[str, Any]) -> str:
        captured["path"] = path
        captured["workload"] = workload
        return "exec-42"

    response = await dispatch_lifecycle(
        catalog_service=_FakeCatalogService(entry),
        execute_callable=fake_execute,
        path="mcp/kubernetes",
        verb="deploy",
        version="latest",
    )

    assert response.status == "started"
    assert response.verb == "deploy"
    assert response.mcp_path == "mcp/kubernetes"
    assert response.mcp_version == 4
    assert response.agent_path == "automation/agents/kubernetes/lifecycle/deploy"
    assert response.execution_id == "exec-42"
    assert captured["path"] == "automation/agents/kubernetes/lifecycle/deploy"
    assert captured["workload"]["mcp_resource"]["path"] == "mcp/kubernetes"
    assert captured["workload"]["verb"] == "deploy"


@pytest.mark.asyncio
async def test_dispatch_422s_when_verb_is_not_in_lifecycle():
    entry = _CatalogEntryStub(
        catalog_id="100",
        path="mcp/kubernetes",
        version=1,
        kind="Mcp",
        payload={"spec": {"lifecycle": {"status": "agents/k8s/status"}}},
    )

    async def fake_execute(**_: Any) -> str:  # pragma: no cover -- not reached
        return "should-not-run"

    with pytest.raises(HTTPException) as info:
        await dispatch_lifecycle(
            catalog_service=_FakeCatalogService(entry),
            execute_callable=fake_execute,
            path="mcp/kubernetes",
            verb="redeploy",
            version="latest",
        )
    assert info.value.status_code == 422
    assert "redeploy" in info.value.detail


@pytest.mark.asyncio
async def test_dispatch_400s_when_resource_kind_is_not_mcp():
    entry = _CatalogEntryStub(
        catalog_id="100",
        path="mcp/kubernetes",
        version=1,
        kind="Playbook",
        payload={"spec": {}},
    )

    async def fake_execute(**_: Any) -> str:  # pragma: no cover
        return "noop"

    with pytest.raises(HTTPException) as info:
        await dispatch_lifecycle(
            catalog_service=_FakeCatalogService(entry),
            execute_callable=fake_execute,
            path="mcp/kubernetes",
            verb="deploy",
            version="latest",
        )
    assert info.value.status_code == 400


@pytest.mark.asyncio
async def test_dispatch_503s_when_service_lacks_lookup_method():
    """Service objects without fetch_entry/get should produce a 503."""

    class _NoLookup:
        pass

    async def fake_execute(**_: Any) -> str:  # pragma: no cover
        return "noop"

    with pytest.raises(HTTPException) as info:
        await dispatch_lifecycle(
            catalog_service=_NoLookup(),
            execute_callable=fake_execute,
            path="mcp/kubernetes",
            verb="deploy",
            version="latest",
        )
    assert info.value.status_code == 503


@pytest.mark.asyncio
async def test_dispatch_falls_back_to_get_when_fetch_entry_missing():
    """Catalog services exposing only `get` should still work."""
    entry = _CatalogEntryStub(
        catalog_id="100",
        path="mcp/kubernetes",
        version=1,
        kind="Mcp",
        payload={"spec": {"lifecycle": {"status": "agents/k8s/status"}}},
    )

    class _GetOnly:
        async def get(self, *, path: str, version: Any):
            return entry

    async def fake_execute(*, path: str, workload: dict[str, Any]) -> str:
        return "exec-7"

    response = await dispatch_lifecycle(
        catalog_service=_GetOnly(),
        execute_callable=fake_execute,
        path="mcp/kubernetes",
        verb="status",
        version="latest",
    )
    assert response.execution_id == "exec-7"
    assert response.agent_path == "agents/k8s/status"


@pytest.mark.asyncio
async def test_workload_overrides_cannot_clobber_reserved_fields():
    """workload_overrides must not be allowed to overwrite mcp_resource/verb."""
    entry = _CatalogEntryStub(
        catalog_id="100",
        path="mcp/kubernetes",
        version=1,
        kind="Mcp",
        payload={"spec": {"lifecycle": {"deploy": "agents/k8s/lifecycle/deploy"}}},
    )

    async def fake_execute(**_: Any) -> str:  # pragma: no cover
        return "should-not-run"

    with pytest.raises(HTTPException) as info:
        await dispatch_lifecycle(
            catalog_service=_FakeCatalogService(entry),
            execute_callable=fake_execute,
            path="mcp/kubernetes",
            verb="deploy",
            version="latest",
            workload_overrides={"mcp_resource": {"hijacked": True}, "extra": 1},
        )
    assert info.value.status_code == 422
    assert "mcp_resource" in info.value.detail


@pytest.mark.asyncio
async def test_workload_overrides_merge_when_no_collision():
    """Override keys outside the reserved set merge cleanly into workload."""
    entry = _CatalogEntryStub(
        catalog_id="100",
        path="mcp/kubernetes",
        version=2,
        kind="Mcp",
        payload={"spec": {"lifecycle": {"deploy": "agents/k8s/lifecycle/deploy"}}},
    )
    captured: dict[str, Any] = {}

    async def fake_execute(*, path: str, workload: dict[str, Any]) -> str:
        captured["workload"] = workload
        return "exec-9"

    response = await dispatch_lifecycle(
        catalog_service=_FakeCatalogService(entry),
        execute_callable=fake_execute,
        path="mcp/kubernetes",
        verb="deploy",
        version="latest",
        workload_overrides={"image_tag": "v1.2.3", "force": True},
    )
    assert response.execution_id == "exec-9"
    assert captured["workload"]["mcp_resource"]["path"] == "mcp/kubernetes"
    assert captured["workload"]["verb"] == "deploy"
    assert captured["workload"]["image_tag"] == "v1.2.3"
    assert captured["workload"]["force"] is True
