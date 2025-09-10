from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_dashboard_routes_basic():
    from noetl.api import dashboard
    app = FastAPI()
    app.include_router(dashboard.router, prefix="/api")
    client = TestClient(app)

    r = client.get("/api/dashboard/stats")
    assert r.status_code == 200

    r = client.get("/api/dashboard/widgets")
    assert r.status_code == 200

