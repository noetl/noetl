import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest import mock
from unittest.mock import AsyncMock, patch

def test_postgres_execute_requires_query_or_procedure():
    from noetl.server.api import database
    app = FastAPI()
    app.include_router(database.router, prefix="/api")
    client = TestClient(app)

    r = client.post("/api/postgres/execute", json={})
    assert r.status_code == 400
    assert "query or procedure is required" in r.json().get("error", "")

