"""Unit tests for ``noetl.server.api.core.catalog_path`` — see
noetl/ai-meta#46 Phase 2.a.2.

Exercises the in-process LRU cache without touching a real Postgres
connection.  The DB miss path is patched via ``monkeypatch`` so the
tests run anywhere ``pytest`` runs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

import pytest

from noetl.server.api.core import catalog_path as catalog_path_module
from noetl.server.api.core.catalog_path import (
    _CACHE_MAX_ENTRIES,
    cache_clear,
    catalog_path_for,
)


@pytest.fixture(autouse=True)
def _isolate_cache():
    """Each test starts and ends with an empty cache."""
    cache_clear()
    yield
    cache_clear()


class _StubCursor:
    """Mimics the slice of psycopg's cursor surface ``catalog_path_for`` uses."""

    def __init__(self, fixture: dict[int, Optional[str]], call_log: list[int]):
        self._fixture = fixture
        self._call_log = call_log
        self._next: Optional[Any] = None

    async def execute(self, sql: str, params: tuple) -> None:  # noqa: D401
        # params is (catalog_id,) per the helper's SQL.
        cid = int(params[0])
        self._call_log.append(cid)
        path = self._fixture.get(cid)
        # Mirror our default ``dict_row`` cursor shape.
        self._next = {"path": path} if path is not None else None

    async def fetchone(self) -> Optional[dict]:
        return self._next

    async def __aenter__(self) -> "_StubCursor":
        return self

    async def __aexit__(self, *exc) -> None:
        return None


class _StubConnection:
    def __init__(self, fixture: dict[int, Optional[str]], call_log: list[int]):
        self._fixture = fixture
        self._call_log = call_log

    def cursor(self) -> _StubCursor:
        return _StubCursor(self._fixture, self._call_log)

    async def __aenter__(self) -> "_StubConnection":
        return self

    async def __aexit__(self, *exc) -> None:
        return None


def _stub_pool(fixture: dict[int, Optional[str]], call_log: list[int]):
    @asynccontextmanager
    async def _get_pool_connection():
        yield _StubConnection(fixture, call_log)

    return _get_pool_connection


@pytest.mark.asyncio
async def test_catalog_path_for_none_input_returns_none():
    assert await catalog_path_for(None) is None


@pytest.mark.asyncio
async def test_catalog_path_for_non_numeric_returns_none():
    assert await catalog_path_for("not-a-number") is None


@pytest.mark.asyncio
async def test_catalog_path_for_hits_db_then_caches(monkeypatch):
    fixture = {42: "system/outbox_publisher"}
    call_log: list[int] = []
    monkeypatch.setattr(
        "noetl.core.db.pool.get_pool_connection",
        _stub_pool(fixture, call_log),
    )

    # First call: cache miss → DB query.
    assert await catalog_path_for(42) == "system/outbox_publisher"
    assert call_log == [42]

    # Second call for same id: served from cache, no DB query.
    assert await catalog_path_for(42) == "system/outbox_publisher"
    assert call_log == [42]


@pytest.mark.asyncio
async def test_catalog_path_for_caches_misses_too(monkeypatch):
    """Unknown catalog_ids cache as None to avoid re-querying a missing row."""
    fixture: dict[int, Optional[str]] = {}
    call_log: list[int] = []
    monkeypatch.setattr(
        "noetl.core.db.pool.get_pool_connection",
        _stub_pool(fixture, call_log),
    )

    assert await catalog_path_for(999) is None
    assert call_log == [999]

    # Negative cache: the second miss does not hit the DB again.
    assert await catalog_path_for(999) is None
    assert call_log == [999]


@pytest.mark.asyncio
async def test_catalog_path_for_distinct_ids(monkeypatch):
    fixture = {1: "user/foo", 2: "system/projector", 3: None}
    call_log: list[int] = []
    monkeypatch.setattr(
        "noetl.core.db.pool.get_pool_connection",
        _stub_pool(fixture, call_log),
    )

    assert await catalog_path_for(1) == "user/foo"
    assert await catalog_path_for(2) == "system/projector"
    assert await catalog_path_for(3) is None
    assert sorted(call_log) == [1, 2, 3]
    # Repeats hit cache.
    assert await catalog_path_for(1) == "user/foo"
    assert await catalog_path_for(2) == "system/projector"
    assert sorted(call_log) == [1, 2, 3]


@pytest.mark.asyncio
async def test_catalog_path_for_db_error_returns_none(monkeypatch):
    """DB exception → ``None`` (caller falls back to kind-based routing)."""

    @asynccontextmanager
    async def _broken_pool():
        raise RuntimeError("pool unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(
        "noetl.core.db.pool.get_pool_connection",
        _broken_pool,
    )

    assert await catalog_path_for(7) is None
    # Error path does NOT cache — next call retries.  (Important so a
    # transient DB blip doesn't pin a stale None for the session.)
    assert 7 not in catalog_path_module._cache  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_catalog_path_for_lru_eviction(monkeypatch):
    """Cache stays bounded — oldest entries get evicted past the cap."""
    fixture = {i: f"user/path_{i}" for i in range(_CACHE_MAX_ENTRIES + 5)}
    call_log: list[int] = []
    monkeypatch.setattr(
        "noetl.core.db.pool.get_pool_connection",
        _stub_pool(fixture, call_log),
    )

    for cid in range(_CACHE_MAX_ENTRIES + 5):
        await catalog_path_for(cid)

    # Cache is bounded.
    assert len(catalog_path_module._cache) == _CACHE_MAX_ENTRIES  # type: ignore[attr-defined]
    # The oldest 5 ids were evicted.
    for cid in range(5):
        assert cid not in catalog_path_module._cache  # type: ignore[attr-defined]
    # The most recent ids are still resident.
    for cid in range(_CACHE_MAX_ENTRIES, _CACHE_MAX_ENTRIES + 5):
        assert cid in catalog_path_module._cache  # type: ignore[attr-defined]
