import pytest

from noetl.core.storage import ResultRef, Scope, StoreTier
from noetl.server.api.result import endpoint as result_endpoint
from noetl.server.api.result.endpoint import ResultPutRequest
from noetl.server.api.temp import endpoint as temp_endpoint
from noetl.server.api.temp.endpoint import TempPutRequest


class _CaptureStore:
    def __init__(self):
        self.puts = []

    async def put(self, **kwargs):
        self.puts.append(kwargs)
        return ResultRef.create(
            execution_id=kwargs["execution_id"],
            name=kwargs["name"],
            store=StoreTier.MEMORY,
            scope=Scope.EXECUTION,
        )


class _Tracker:
    def register_ref(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_result_put_scrubs_payload_before_store(monkeypatch):
    store = _CaptureStore()
    monkeypatch.setattr(result_endpoint, "default_store", store)
    monkeypatch.setattr(result_endpoint, "default_tracker", _Tracker())

    await result_endpoint.put_result(
        "123",
        ResultPutRequest(
            name="api_result",
            data={"headers": {"Authorization": "Bearer placeholder-token"}},
            correlation={"Cookie": "session=placeholder-token"},
        ),
    )

    assert store.puts[0]["data"]["headers"]["Authorization"] == "[REDACTED]"
    assert store.puts[0]["correlation"]["Cookie"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_temp_put_scrubs_payload_before_store(monkeypatch):
    store = _CaptureStore()
    monkeypatch.setattr(temp_endpoint, "default_store", store)
    monkeypatch.setattr(temp_endpoint, "default_tracker", _Tracker())

    await temp_endpoint.put_temp(
        "123",
        TempPutRequest(
            name="api_temp",
            data={"headers": {"X-API-Key": "placeholder-token"}},
            correlation={"Set-Cookie": "session=placeholder-token"},
        ),
    )

    assert store.puts[0]["data"]["headers"]["X-API-Key"] == "[REDACTED]"
    assert store.puts[0]["correlation"]["Set-Cookie"] == "[REDACTED]"
