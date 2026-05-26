import pytest

import noetl.worker.transient as transient_module
from noetl.worker.transient import TransientVars


class _Response:
    status_code = 200


class _AsyncClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, json):
        _AsyncClient.calls.append({"url": url, "json": json})
        return _Response()


_AsyncClient.calls = []


@pytest.mark.asyncio
async def test_transient_set_cached_scrubs_worker_api_payload(monkeypatch):
    _AsyncClient.calls = []
    monkeypatch.setenv("NOETL_WORKER_MODE", "true")
    monkeypatch.setattr(transient_module.httpx, "AsyncClient", _AsyncClient)

    await TransientVars.set_cached(
        "headers",
        {"Authorization": "Bearer placeholder-token"},
        execution_id=123,
    )

    variables = _AsyncClient.calls[0]["json"]["variables"]
    assert variables["headers"]["Authorization"] == "[REDACTED]"


class _Cursor:
    def __init__(self):
        self.params = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _query, params):
        self.params.append(params)


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def cursor(self, *args, **kwargs):
        return self._cursor


@pytest.mark.asyncio
async def test_transient_set_multiple_scrubs_db_payload(monkeypatch):
    cursor = _Cursor()
    monkeypatch.delenv("NOETL_WORKER_MODE", raising=False)
    monkeypatch.setattr(transient_module, "get_pool_connection", lambda: _Connection(cursor))

    count = await TransientVars.set_multiple(
        {"headers": {"Cookie": "session=placeholder-token"}},
        execution_id=123,
    )

    assert count == 1
    assert cursor.params[0]["var_value"].obj["Cookie"] == "[REDACTED]"
