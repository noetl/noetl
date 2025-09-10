from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_worker_pool_register_requires_fields():
    from noetl.api import runtime
    app = FastAPI()
    app.include_router(runtime.router, prefix="/api")
    client = TestClient(app)

    # Missing required fields
    r = client.post("/api/worker/pool/register", json={})
    assert r.status_code == 400
    assert "required" in r.json().get("detail", "")

