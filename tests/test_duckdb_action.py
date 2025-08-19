import pytest
pytest.skip("Moved to tests/noetl/worker/action/", allow_module_level=True)

from jinja2 import Environment

from noetl.worker.action import duckdb as duckdb_module


def test_sql_split_handles_quotes():
    sql = "SELECT 'a; b' as txt; SELECT 1 as one; \"semi;colon\"; SELECT 2;"
    parts = duckdb_module.sql_split(sql)
    assert parts[0].startswith("SELECT 'a; b'")
    assert 'SELECT 1' in parts[1]
    assert '"semi;colon"' in parts[2]
    assert parts[-1].strip() == 'SELECT 2'


def test_execute_duckdb_task_select(monkeypatch):
    # Ensure module thinks duckdb is available
    monkeypatch.setattr(duckdb_module, 'DUCKDB_AVAILABLE', True)

    class FakeCursor:
        def __init__(self):
            self.description = None
            self._rows = []
        def execute(self, cmd):
            self.last_cmd = cmd
            if 'SELECT' in cmd.upper():
                self.description = [('value',)]
                self._rows = [(1,)]
            else:
                self.description = None
                self._rows = []
        def fetchall(self):
            return self._rows

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    class DummyCM:
        def __init__(self, conn):
            self.conn = conn
        def __enter__(self):
            return self.conn
        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_get_conn(path):
        return DummyCM(FakeConn())

    monkeypatch.setattr(duckdb_module, 'get_duckdb_connection', fake_get_conn)

    env = Environment()
    context = {}
    cfg = {'task': 'duck', 'command': 'SELECT 1 as value;'}
    task_with = {'db': ':memory:'}

    out = duckdb_module.execute_duckdb_task(cfg, context, env, task_with, log_event_callback=None)

    assert out['status'] == 'success'
    assert isinstance(out['data'], list)
    assert out['data'][0]['value'] == 1
