from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_credential_requires_name_and_data():
    from noetl.api import credential
    app = FastAPI()
    app.include_router(credential.router, prefix="/api")
    client = TestClient(app)

    # Missing name
    r = client.post("/api/credentials", json={"data": {"key": "secret"}})
    assert r.status_code == 400
    assert "name" in r.json().get("detail", "")

    # Missing data
    r = client.post("/api/credentials", json={"name": "test-cred"})
    assert r.status_code == 400
    assert "data" in r.json().get("detail", "")

