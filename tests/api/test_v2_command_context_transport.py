import pytest

import noetl.server.api.v2 as v2_api
from noetl.core.storage.models import ResultRef, ResultRefMeta, Scope, StoreTier


@pytest.mark.asyncio
async def test_store_command_context_if_needed_externalizes_large_context(monkeypatch):
    async def _fake_put(**kwargs):
        return ResultRef.create(
            execution_id=str(kwargs["execution_id"]),
            name=str(kwargs["name"]),
            store=StoreTier.KV,
            scope=Scope.EXECUTION,
            meta=ResultRefMeta(bytes=4096),
        )

    monkeypatch.setattr(v2_api, "_COMMAND_CONTEXT_INLINE_MAX_BYTES", 128)
    monkeypatch.setattr(v2_api.default_store, "put", _fake_put)

    result = await v2_api._store_command_context_if_needed(
        execution_id=123,
        step="fetch_data",
        command_id="123:fetch_data:1",
        context={
            "tool_config": {"kind": "http"},
            "render_context": {"payload": "x" * 2048},
        },
    )

    assert result["kind"] == "result_ref"
    assert result["store"] == "kv"
    assert result["ref"].startswith("noetl://execution/123/")
    assert "preview" not in result


@pytest.mark.asyncio
async def test_store_command_context_if_needed_keeps_small_context_inline(monkeypatch):
    monkeypatch.setattr(v2_api, "_COMMAND_CONTEXT_INLINE_MAX_BYTES", 4096)

    context = {
        "tool_config": {"kind": "http"},
        "args": {"page": 1},
    }
    result = await v2_api._store_command_context_if_needed(
        execution_id=123,
        step="fetch_data",
        command_id="123:fetch_data:1",
        context=context,
    )

    assert result == context


def test_validate_postgres_command_context_requires_auth():
    with pytest.raises(ValueError, match="missing auth"):
        v2_api._validate_postgres_command_context(
            step="load_rows",
            tool_kind="postgres",
            context={
                "tool_config": {},
                "args": {},
            },
        )


def test_validate_postgres_command_context_accepts_tool_or_args_auth():
    v2_api._validate_postgres_command_context(
        step="load_rows",
        tool_kind="postgres",
        context={
            "tool_config": {"auth": "pg_main"},
            "args": {},
        },
    )

    v2_api._validate_postgres_command_context(
        step="load_rows",
        tool_kind="postgres",
        context={
            "tool_config": {},
            "args": {"auth": "pg_main"},
        },
    )
