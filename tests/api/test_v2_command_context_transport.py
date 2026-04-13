import pytest

from noetl.server.api.core import commands as api_commands
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

    monkeypatch.setattr(api_commands, "_COMMAND_CONTEXT_INLINE_MAX_BYTES", 128)
    monkeypatch.setattr(api_commands.default_store, "put", _fake_put)

    result = await api_commands._store_command_context_if_needed(
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
    monkeypatch.setattr(api_commands, "_COMMAND_CONTEXT_INLINE_MAX_BYTES", 4096)

    context = {
        "tool_config": {"kind": "http"},
        "input": {"page": 1},
    }
    result = await api_commands._store_command_context_if_needed(
        execution_id=123,
        step="fetch_data",
        command_id="123:fetch_data:1",
        context=context,
    )

    assert result == context


@pytest.mark.asyncio
async def test_store_command_context_if_needed_externalizes_nested_heavy_fields(monkeypatch):
    calls = []

    async def _fake_put(**kwargs):
        calls.append(kwargs["name"])
        return ResultRef.create(
            execution_id=str(kwargs["execution_id"]),
            name=str(kwargs["name"]),
            store=StoreTier.KV,
            scope=Scope.EXECUTION,
            meta=ResultRefMeta(bytes=2048),
        )

    monkeypatch.setattr(api_commands, "_COMMAND_CONTEXT_INLINE_MAX_BYTES", 4096)
    monkeypatch.setattr(api_commands, "_COMMAND_CONTEXT_FIELD_INLINE_MAX_BYTES", 64)
    monkeypatch.setattr(api_commands.default_store, "put", _fake_put)

    result = await api_commands._store_command_context_if_needed(
        execution_id=123,
        step="fetch_data",
        command_id="123:fetch_data:2",
        context={
            "tool_config": {"kind": "http", "tasks": [{"name": "task1", "url": "https://example.test", "template": "x" * 256}]},
            "render_context": {"payload": "x" * 2048},
            "input": {"page": 1},
        },
    )

    assert result["tool_config"]["kind"] == "result_ref"
    assert result["render_context"]["kind"] == "result_ref"
    assert calls == ["fetch_data_tool_config", "fetch_data_render_context"]


def test_validate_postgres_command_context_requires_auth():
    with pytest.raises(ValueError, match="missing auth"):
        api_commands._validate_postgres_command_context(
            step="load_rows",
            tool_kind="postgres",
            context={
                "tool_config": {},
                "input": {},
            },
        )


def test_validate_postgres_command_context_accepts_tool_or_input_auth():
    api_commands._validate_postgres_command_context(
        step="load_rows",
        tool_kind="postgres",
        context={
            "tool_config": {"auth": "pg_main"},
            "input": {},
        },
    )

    api_commands._validate_postgres_command_context(
        step="load_rows",
        tool_kind="postgres",
        context={
            "tool_config": {},
            "input": {"auth": "pg_main"},
        },
    )


def test_validate_postgres_command_context_rejects_legacy_args_alias():
    with pytest.raises(ValueError, match="missing auth"):
        api_commands._validate_postgres_command_context(
            step="load_rows",
            tool_kind="postgres",
            context={
                "tool_config": {},
                "args": {"auth": "pg_main"},
            },
        )


def test_validate_postgres_command_context_rejects_direct_connection_fields():
    with pytest.raises(ValueError, match="forbidden direct connection fields"):
        api_commands._validate_postgres_command_context(
            step="load_rows",
            tool_kind="postgres",
            context={
                "tool_config": {"auth": "pg_main", "db_host": "localhost"},
                "input": {},
            },
        )
