import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
EXECUTION_PATH = ROOT / "noetl" / "tools" / "postgres" / "execution.py"
SPEC = importlib.util.spec_from_file_location("noetl_postgres_execution_under_test", EXECUTION_PATH)
execution_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(execution_module)


class _FakeConnInfo:
    backend_pid = 12345


class _FakeConn:
    def __init__(self):
        self.info = _FakeConnInfo()
        self.autocommit = False

    async def close(self):
        return None


class _FakePoolConnCtx:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_midstream_retry_safety_predicates():
    assert execution_module._is_retry_safe_read_statement("SELECT 1")
    assert execution_module._is_retry_safe_read_statement("/*hint*/\nSHOW search_path")
    assert not execution_module._is_retry_safe_read_statement("INSERT INTO t VALUES (1)")
    assert not execution_module._is_retry_safe_read_statement("SELECT * FROM t FOR UPDATE")

    assert execution_module._is_midstream_connection_drop_error(
        Exception("server closed the connection unexpectedly")
    )
    assert not execution_module._is_midstream_connection_drop_error(
        Exception("statement timeout expired")
    )


@pytest.mark.asyncio
async def test_direct_connection_retries_transient_drop_from_failed_index(monkeypatch):
    connect_calls = []
    execute_calls = []

    async def fake_connect(*_args, **_kwargs):
        connect_calls.append(True)
        return _FakeConn()

    async def fake_execute_sql_statements_async(_conn, commands, start_index=0):
        execute_calls.append((list(commands), start_index))
        if len(execute_calls) == 1:
            raise execution_module._TransientConnectionDrop(
                "connection is lost",
                failed_command_index=1,
                partial_results={"command_0": {"status": "success", "row_count": 1}},
            )
        return {"command_1": {"status": "success", "row_count": 1}}

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(execution_module.AsyncConnection, "connect", fake_connect)
    monkeypatch.setattr(execution_module, "execute_sql_statements_async", fake_execute_sql_statements_async)
    monkeypatch.setattr(execution_module, "_CONNECT_ATTEMPTS", 2)
    monkeypatch.setattr(execution_module.asyncio, "sleep", fake_sleep)

    result = await execution_module._execute_with_direct_connection(
        connection_string="postgresql://user:pass@host/db",
        commands=["SELECT 1", "SELECT 2"],
        conn_id="conn-1",
        host="host",
        port="5432",
        database="db",
    )

    assert len(connect_calls) == 2
    assert execute_calls[0][1] == 0
    assert execute_calls[1][1] == 1
    assert result["command_0"]["status"] == "success"
    assert result["command_1"]["status"] == "success"


@pytest.mark.asyncio
async def test_pooled_connection_retries_transient_drop_from_failed_index(monkeypatch):
    pool_open_calls = []
    execute_calls = []

    def fake_get_plugin_connection_ctx(*_args, **_kwargs):
        pool_open_calls.append(True)
        return _FakePoolConnCtx()

    async def fake_execute_sql_statements_async(_conn, commands, start_index=0):
        execute_calls.append((list(commands), start_index))
        if len(execute_calls) == 1:
            raise execution_module._TransientConnectionDrop(
                "server closed the connection unexpectedly",
                failed_command_index=2,
                partial_results={
                    "command_0": {"status": "success", "row_count": 1},
                    "command_1": {"status": "success", "row_count": 1},
                },
            )
        return {"command_2": {"status": "success", "row_count": 1}}

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(execution_module, "_get_plugin_connection_ctx", fake_get_plugin_connection_ctx)
    monkeypatch.setattr(execution_module, "execute_sql_statements_async", fake_execute_sql_statements_async)
    monkeypatch.setattr(execution_module, "_CONNECT_ATTEMPTS", 2)
    monkeypatch.setattr(execution_module.asyncio, "sleep", fake_sleep)

    result = await execution_module._execute_with_pooled_connection(
        connection_string="postgresql://user:pass@host/db",
        commands=["SELECT 1", "SELECT 2", "SELECT 3"],
        conn_id="conn-2",
        host="host",
        port="5432",
        database="db",
        pool_name="pg_db",
        pool_params={},
    )

    assert len(pool_open_calls) == 2
    assert execute_calls[0][1] == 0
    assert execute_calls[1][1] == 2
    assert result["command_0"]["status"] == "success"
    assert result["command_1"]["status"] == "success"
    assert result["command_2"]["status"] == "success"
