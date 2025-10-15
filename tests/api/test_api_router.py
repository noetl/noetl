def test_top_level_api_router_health():
    # Import here to ensure package-level router imports cleanly
    pass
from fastapi import FastAPI
from starlette.testclient import TestClient


def test_all_api_routes_loaded():
    from noetl.server.api import router as api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"

