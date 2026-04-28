"""Tests for the lifecycle dispatch service helper."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from noetl.server.api.mcp.service import dispatch_lifecycle


class _FakeCatalogService:
    """Minimal stand-in implementing the get_entry contract used here."""

    def __init__(self, entry: dict[str, Any] | None = None):
        self.entry = entry

    async def get_entry(self, *, path: str, version: Any):
        return self.entry


@pytest.mark.asyncio
async def test_dispatch_resolves_lifecycle_to_agent_and_returns_execution_id():
    entry = {
        "catalog_id": "100",
        "path": "mcp/kubernetes",
        "version": 4,
        "kind": "Mcp",
        "payload": {
            "metadata": {"name": "kubernetes"},
            "spec": {
                "lifecycle": {
                    "deploy": "automation/agents/kubernetes/lifecycle/deploy",
                },
            },
        },
    }
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
    entry = {
        "catalog_id": "100",
        "path": "mcp/kubernetes",
        "version": 1,
        "kind": "Mcp",
        "payload": {"spec": {"lifecycle": {"status": "agents/k8s/status"}}},
    }

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
    entry = {
        "catalog_id": "100",
        "path": "mcp/kubernetes",
        "version": 1,
        "kind": "Playbook",
        "payload": {"spec": {}},
    }

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
