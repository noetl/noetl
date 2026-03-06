from fastapi import FastAPI
from fastapi.testclient import TestClient

from noetl.server.api.catalog.endpoint import router
from noetl.server.api.catalog.service import get_catalog_service


class _FakeCatalogService:
    async def fetch_agent_entries(self, path=None, capabilities=None):
        return {
            "entries": [
                {
                    "catalog_id": "1",
                    "path": path or "agents/sample",
                    "version": 1,
                    "kind": "Playbook",
                    "content": "apiVersion: noetl.io/v2",
                    "payload": {
                        "metadata": {
                            "agent": True,
                            "capabilities": capabilities or ["code-review"],
                        }
                    },
                    "meta": {"agent": True, "capabilities": capabilities or ["code-review"]},
                    "created_at": None,
                }
            ]
        }


def _build_client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_catalog_service] = lambda: _FakeCatalogService()
    return TestClient(app)


def test_catalog_agents_list_endpoint():
    client = _build_client()
    resp = client.post(
        "/api/catalog/agents/list",
        json={"capability": "release-management", "path": "agents/release-coordinator"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "entries" in body
    assert len(body["entries"]) == 1
    assert body["entries"][0]["path"] == "agents/release-coordinator"
    assert body["entries"][0]["payload"]["metadata"]["capabilities"] == ["release-management"]

