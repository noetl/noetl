"""
Unit tests for noetl.core.storage.backends.DiskCacheBackend.

Phase 1 of the RisingWave storage alignment. Covers the core contract:
put, get, delete, LRU eviction, rate-limited inserts, warm-start
re-indexing, and the cloud read-through / spill flow.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, Optional

import pytest

from noetl.core.storage.backends import (
    DiskCacheBackend,
    StorageBackend,
    _DiskCachePool,
    _TokenBucket,
)


# -----------------------------------------------------------------------------
# Test doubles
# -----------------------------------------------------------------------------


class _FakeCloud(StorageBackend):
    """In-memory cloud backend used as the DISK spill target."""

    def __init__(self):
        self._store: Dict[str, bytes] = {}
        self.put_calls = 0
        self.get_calls = 0
        self.delete_calls = 0

    async def put(self, key: str, data: bytes, metadata: Optional[dict] = None) -> str:
        self.put_calls += 1
        self._store[key] = data
        return f"fake-cloud://{key}"

    async def get(self, key: str) -> bytes:
        self.get_calls += 1
        if key not in self._store:
            raise KeyError(key)
        return self._store[key]

    async def delete(self, key: str) -> bool:
        self.delete_calls += 1
        return self._store.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        return key in self._store


# -----------------------------------------------------------------------------
# DiskCacheBackend.put / get / delete
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_and_get_roundtrip(tmp_path):
    backend = DiskCacheBackend(
        cache_dir=str(tmp_path / "cache"),
        data_capacity_mb=4,
        meta_capacity_mb=1,
    )
    await backend.put("k1", b"hello world")
    assert await backend.get("k1") == b"hello world"


@pytest.mark.asyncio
async def test_meta_vs_data_pool_routing(tmp_path):
    backend = DiskCacheBackend(
        cache_dir=str(tmp_path / "cache"),
        data_capacity_mb=4,
        meta_capacity_mb=1,
    )
    small = b"x" * 256  # < META_ENTRY_THRESHOLD_BYTES
    big = b"y" * (50 * 1024)  # > threshold
    await backend.put("small", small)
    await backend.put("big", big)

    stats = backend.stats()
    assert stats["meta"]["entries"] == 1
    assert stats["data"]["entries"] == 1


@pytest.mark.asyncio
async def test_lru_eviction_when_capacity_exceeded(tmp_path):
    # 4 KB data pool -> holds at most 4 entries of 1 KB.
    backend = DiskCacheBackend(
        cache_dir=str(tmp_path / "cache"),
        data_capacity_mb=0,  # override via direct pool manipulation below
        meta_capacity_mb=0,
    )
    pool = _DiskCachePool(
        str(tmp_path / "cache" / "data_small"),
        capacity_bytes=4 * 1024,
        rate_limiter=None,
        name="data_small",
    )

    payload = b"z" * 1024
    # Insert 5 distinct keys; first should be evicted.
    for i in range(5):
        await pool.put(f"k{i}", payload)

    # k0 was evicted; k1..k4 should be present.
    with pytest.raises(KeyError):
        await pool.get("k0")
    for i in range(1, 5):
        assert await pool.get(f"k{i}") == payload


@pytest.mark.asyncio
async def test_delete_removes_from_pool(tmp_path):
    backend = DiskCacheBackend(
        cache_dir=str(tmp_path / "cache"),
        data_capacity_mb=2,
        meta_capacity_mb=1,
    )
    await backend.put("k1", b"payload")
    assert await backend.exists("k1")
    assert await backend.delete("k1") is True
    assert not await backend.exists("k1")
    with pytest.raises(KeyError):
        await backend.get("k1")


@pytest.mark.asyncio
async def test_get_miss_reads_through_cloud(tmp_path):
    cloud = _FakeCloud()
    await cloud.put("k2", b"from-cloud")
    backend = DiskCacheBackend(
        cache_dir=str(tmp_path / "cache"),
        data_capacity_mb=2,
        meta_capacity_mb=1,
        cloud_backend=cloud,
    )
    # Fresh backend: no local copy. get should fetch from cloud and
    # re-populate the local pool for subsequent reads.
    assert await backend.get("k2") == b"from-cloud"
    assert cloud.get_calls == 1

    # Second get hits local cache -> no additional cloud call.
    assert await backend.get("k2") == b"from-cloud"
    assert cloud.get_calls == 1


@pytest.mark.asyncio
async def test_put_spills_to_cloud_async(tmp_path):
    cloud = _FakeCloud()
    backend = DiskCacheBackend(
        cache_dir=str(tmp_path / "cache"),
        data_capacity_mb=2,
        meta_capacity_mb=1,
        cloud_backend=cloud,
    )
    await backend.put("k3", b"payload")
    # Spill is fire-and-forget; give the task a chance to run.
    for _ in range(10):
        if cloud.put_calls >= 1:
            break
        await asyncio.sleep(0.01)
    assert cloud.put_calls == 1
    assert cloud._store["k3"] == b"payload"


@pytest.mark.asyncio
async def test_delete_also_removes_cloud(tmp_path):
    cloud = _FakeCloud()
    backend = DiskCacheBackend(
        cache_dir=str(tmp_path / "cache"),
        data_capacity_mb=2,
        meta_capacity_mb=1,
        cloud_backend=cloud,
    )
    await backend.put("k4", b"payload")
    for _ in range(10):
        if cloud.put_calls >= 1:
            break
        await asyncio.sleep(0.01)
    assert await backend.delete("k4") is True
    assert cloud.delete_calls == 1


@pytest.mark.asyncio
async def test_warm_start_reindexes_on_disk_entries(tmp_path):
    cache_dir = tmp_path / "cache"
    # First backend writes some entries, then is discarded.
    b1 = DiskCacheBackend(
        cache_dir=str(cache_dir),
        data_capacity_mb=2,
        meta_capacity_mb=1,
    )
    for i in range(3):
        await b1.put(f"warm-{i}", b"persistent")

    # New backend instance with recover_mode=Quiet should find them.
    b2 = DiskCacheBackend(
        cache_dir=str(cache_dir),
        data_capacity_mb=2,
        meta_capacity_mb=1,
        recover_mode="Quiet",
    )
    # Trigger the lazy warm-start by calling any get.
    for i in range(3):
        assert await b2.get(f"warm-{i}") == b"persistent"

    stats = b2.stats()
    # All three entries are under 10KB, so they live in the meta pool.
    total_entries = stats["meta"]["entries"] + stats["data"]["entries"]
    assert total_entries >= 3


@pytest.mark.asyncio
async def test_warm_start_skipped_when_recover_mode_none(tmp_path):
    cache_dir = tmp_path / "cache"
    b1 = DiskCacheBackend(
        cache_dir=str(cache_dir),
        data_capacity_mb=2,
        meta_capacity_mb=1,
    )
    await b1.put("cold-1", b"persistent")

    b2 = DiskCacheBackend(
        cache_dir=str(cache_dir),
        data_capacity_mb=2,
        meta_capacity_mb=1,
        # recover_mode defaults to "None"
    )
    # Fresh backend without recover_mode should treat the cache as empty
    # locally. The read path will fall through to the cloud (unconfigured
    # here) and raise KeyError.
    with pytest.raises(KeyError):
        await b2.get("cold-1")


# -----------------------------------------------------------------------------
# Rate limiter
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_bucket_rate_limits_large_writes():
    # 1024 bytes / second. Requesting 2048 bytes should take at least ~1s.
    bucket = _TokenBucket(rate_bytes_per_sec=1024, burst_bytes=1024)
    # Drain the initial burst so the second take has to wait for refill.
    await bucket.take(1024)
    t0 = time.monotonic()
    await bucket.take(1024)
    elapsed = time.monotonic() - t0
    # Allow ±20% slack for scheduler noise.
    assert elapsed >= 0.8, f"rate limiter did not throttle: elapsed={elapsed:.3f}s"


@pytest.mark.asyncio
async def test_token_bucket_zero_rate_is_unlimited():
    bucket = _TokenBucket(rate_bytes_per_sec=0)
    t0 = time.monotonic()
    for _ in range(100):
        await bucket.take(1_000_000)
    assert time.monotonic() - t0 < 0.1


# -----------------------------------------------------------------------------
# Atomic write / crash resilience
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_leaves_no_tmp_files(tmp_path):
    backend = DiskCacheBackend(
        cache_dir=str(tmp_path / "cache"),
        data_capacity_mb=2,
        meta_capacity_mb=1,
    )
    await backend.put("k1", b"payload")
    for pool_name in ("meta", "data"):
        tmp_dir = tmp_path / "cache" / pool_name / "tmp"
        if tmp_dir.exists():
            assert list(tmp_dir.iterdir()) == [], f"tmp files left in {tmp_dir}"
