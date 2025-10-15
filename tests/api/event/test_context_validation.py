from fastapi import FastAPI
from fastapi.testclient import TestClient

from noetl.server.api.event.context import router as context_router


def _create_client():
    app = FastAPI()
    app.include_router(context_router, prefix="/api")
    return TestClient(app)


def test_context_render_requires_execution_id():
    client = _create_client()
    response = client.post("/api/context/render", json={"template": {"x": "y"}})
    assert response.status_code == 400
    assert "execution_id" in response.json().get("detail", "")


def test_context_render_requires_template():
    client = _create_client()
    response = client.post("/api/context/render", json={"execution_id": "123"})
    assert response.status_code == 400
    assert "template" in response.json().get("detail", "")
