"""Lightweight checks for the runtime API worker pool endpoints.

The database layer is mocked so the tests can run without any external
dependencies. Execute with:

```
pytest tests/test_runtime_api.py -q
```
"""

from contextlib import contextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from noetl.server.api import runtime


def test_worker_pool_routes():
    app = FastAPI()
    app.include_router(runtime.router, prefix="/api")
    client = TestClient(app)

    payload = {"name": "testpool", "runtime": "cpu", "base_url": "http://localhost:9000"}

    @contextmanager
    def _dummy_db():
        class Cur:
            def execute(self, *args, **kwargs):
                pass
            def fetchone(self):
                return (1,)
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                pass
        class Conn:
            def cursor(self):
                return Cur()
            def commit(self):
                pass
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                pass
        yield Conn()

    with patch("noetl.core.common.get_db_connection", _dummy_db):
        resp = client.post("/api/worker/pool/register", json=payload)
        assert resp.status_code == 200
        assert resp.json().get("status") in {"registered", "ok"}

        resp = client.request("DELETE", "/api/worker/pool/deregister", json={"name": "testpool"})
        assert resp.status_code == 200
        assert resp.json().get("status") in {"deregistered", "ok"}

    resp = client.post("/api/worker/pool/heartbeat", json={})
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"

    resp = client.get("/api/worker/pools")
    assert resp.status_code == 200
    assert isinstance(resp.json().get("items"), list)
