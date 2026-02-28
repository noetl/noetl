import asyncio
import importlib.util
from pathlib import Path
import pytest


def _load_pool_module():
    pytest.importorskip("psycopg")
    pool_path = Path(__file__).resolve().parents[2] / "noetl" / "tools" / "postgres" / "pool.py"
    spec = importlib.util.spec_from_file_location("pg_pool_test_module", pool_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class FakeAsyncConnectionPool:
    def __init__(self, *args, **kwargs):
        self.name = kwargs.get("name", "fake_pool")
        self._open = False
        self._closed = False
        self._stats = {"pool_size": 1, "pool_available": 1, "requests_waiting": 0}

    async def open(self, wait=True, timeout=None):
        self._open = True

    async def close(self):
        self._closed = True

    def get_stats(self):
        return self._stats


def test_pool_registry_is_scoped_by_event_loop(monkeypatch):
    pg_pool = _load_pool_module()
    monkeypatch.setattr(pg_pool, "AsyncConnectionPool", FakeAsyncConnectionPool)
    pg_pool._plugin_pools.clear()
    pg_pool._plugin_locks.clear()

    connection_string = "postgresql://user:pass@localhost:5432/testdb"
    pool_name = "loop_scope_test"

    async def _create_pool():
        return await pg_pool.get_or_create_plugin_pool(
            connection_string=connection_string,
            pool_name=pool_name,
            min_size=1,
            max_size=2,
            timeout=1.0,
            max_waiting=5,
        )

    loop1 = asyncio.new_event_loop()
    loop2 = asyncio.new_event_loop()
    try:
        pool1 = loop1.run_until_complete(_create_pool())
        pool2 = loop2.run_until_complete(_create_pool())

        assert pool1 is not pool2
        assert len(pg_pool._plugin_pools) == 2

        stats = pg_pool.get_plugin_pool_stats()
        assert len(stats) == 2
    finally:
        # Cleanup must run in each owning loop because pools are loop-scoped.
        loop1.run_until_complete(pg_pool.close_all_plugin_pools())
        loop2.run_until_complete(pg_pool.close_all_plugin_pools())
        loop1.close()
        loop2.close()
        pg_pool._plugin_pools.clear()
        pg_pool._plugin_locks.clear()
