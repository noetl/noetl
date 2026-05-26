import pytest

import noetl.worker.result_handler as result_handler_module
from noetl.worker.result_handler import ResultHandler


class _FailStore:
    async def put(self, **_kwargs):
        raise RuntimeError("kv unavailable")


class _CaptureStore:
    def __init__(self):
        self.puts = []

    async def put(self, **kwargs):
        from noetl.core.storage import ResultRef, Scope, StoreTier

        self.puts.append(kwargs)
        return ResultRef.create(
            execution_id=kwargs["execution_id"],
            name=kwargs["name"],
            store=StoreTier.MEMORY,
            scope=Scope.EXECUTION,
        )


@pytest.mark.asyncio
async def test_result_handler_store_failure_returns_bounded_payload(monkeypatch):
    monkeypatch.setattr(result_handler_module, "PREVIEW_MAX_BYTES", 64)
    handler = ResultHandler(execution_id = "123", store=_FailStore(), inline_max_bytes=8)
    large_result = {"rows": [{"id": i, "payload": "x" * 80} for i in range(20)]}

    processed = await handler.process_result(
        step_name="fetch_rows",
        result=large_result,
        output_config={"output_select": ["rows"]},
    )

    assert processed["_store_failed"] is True
    assert "_preview" in processed
    assert processed["_size_bytes"] > 64
    assert "rows" in processed
    assert processed["rows"] != large_result["rows"]


@pytest.mark.asyncio
async def test_result_handler_scrubs_preview_extracted_and_stored_data(monkeypatch):
    monkeypatch.setattr(result_handler_module, "PREVIEW_MAX_BYTES", 1024)
    store = _CaptureStore()
    handler = ResultHandler(execution_id="123", store=store, inline_max_bytes=8)
    result = {
        "status": "ok",
        "headers": {"Authorization": "Bearer placeholder-token"},
        "body": "x" * 40,
    }

    processed = await handler.process_result(
        step_name="fetch_rows",
        result=result,
        output_config={"output_select": ["headers.Authorization"]},
    )

    assert store.puts[0]["data"]["headers"]["Authorization"] == "[REDACTED]"
    assert processed["Authorization"] == "[REDACTED]"
    assert "placeholder-token" not in str(processed["_preview"])
