import pytest

import noetl.worker.result_handler as result_handler_module
from noetl.worker.result_handler import ResultHandler


class _FailStore:
    async def put(self, **_kwargs):
        raise RuntimeError("kv unavailable")


@pytest.mark.asyncio
async def test_result_handler_store_failure_returns_bounded_payload(monkeypatch):
    monkeypatch.setattr(result_handler_module, "PREVIEW_MAX_BYTES", 64)
    handler = ResultHandler(execution_id="123", store=_FailStore(), inline_max_bytes=8)
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
