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
