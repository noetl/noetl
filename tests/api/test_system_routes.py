def test_system_status_and_threads():
    pass
from fastapi import FastAPI
from fastapi.testclient import TestClient

def test_system_routes_basic():
    from noetl.server.api import system
    app = FastAPI()
    app.include_router(system.router, prefix="/api/sys")
    client = TestClient(app)

    r = client.get("/api/sys/status")
    assert r.status_code == 200
    assert "system" in r.json()
    assert "process" in r.json()

    r = client.get("/api/sys/threads")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

