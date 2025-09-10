import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_top_level_api_router_health():
    # Import here to ensure package-level router imports cleanly
    from noetl.api import router as api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"

