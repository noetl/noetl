from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_catalog_validate_requires_content():
    from noetl.api import catalog
    app = FastAPI()
    app.include_router(catalog.router, prefix="/api")
    client = TestClient(app)

    r = client.post("/api/catalog/playbooks/validate", json={})
    assert r.status_code == 400
    assert "Content is required" in r.json().get("detail", "")

