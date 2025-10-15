from fastapi import FastAPI
from fastapi.testclient import TestClient

from noetl.server.api import credential


def _create_client():
    app = FastAPI()
    app.include_router(credential.router, prefix="/api")
    return TestClient(app)


def test_credential_requires_name():
    client = _create_client()
    response = client.post("/api/credentials", json={"data": {"key": "secret"}})
    assert response.status_code == 400
    assert "name" in response.json().get("detail", "")


def test_credential_requires_data():
    client = _create_client()
    response = client.post("/api/credentials", json={"name": "test-cred"})
    assert response.status_code == 400
    assert "data" in response.json().get("detail", "")
