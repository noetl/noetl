from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_context_render_requires_fields():
    import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

@pytest.mark.asyncio
async def test_context_validation():
    from noetl.server.api.event.context import router as context_router

    app = FastAPI()
    app.include_router(context_router, prefix="/api")
    client = TestClient(app)

    # Missing execution_id
    r = client.post("/api/context/render", json={"template": {"x": "y"}})
    assert r.status_code == 400
    assert "execution_id" in r.json().get("detail", "")

    # Missing template
    r = client.post("/api/context/render", json={"execution_id": "123"})
    assert r.status_code == 400
    assert "template" in r.json().get("detail", "")

