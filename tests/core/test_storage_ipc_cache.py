from datetime import datetime, timedelta, timezone

import pytest


def test_ipc_cache_round_trips_arrow_ipc_bytes():
    from noetl.core.storage import ArrowIpcSharedMemoryCache

    cache = ArrowIpcSharedMemoryCache(
        namespace="noetl-test",
        budget_bytes=1024,
        default_lease_seconds=30,
        producer="worker-a",
    )
    hint = cache.put_arrow_ipc(
        b"arrow-stream-bytes",
        schema_digest="schema-1",
        row_count=3,
    )
    try:
        assert hint.kind == "arrow_ipc"
        assert hint.producer == "worker-a"
        assert hint.byte_length == len(b"arrow-stream-bytes")
        assert hint.row_count == 3
        assert cache.get(hint) == b"arrow-stream-bytes"
    finally:
        cache.delete(hint)


def test_ipc_cache_rejects_payload_over_budget():
    from noetl.core.storage import ArrowIpcSharedMemoryCache

    cache = ArrowIpcSharedMemoryCache(namespace="noetl-test", budget_bytes=4)

    with pytest.raises(ValueError, match="exceeds IPC cache budget"):
        cache.put_arrow_ipc(b"too-large", schema_digest="schema-1")


def test_ipc_cache_sweeps_expired_entries():
    from noetl.core.storage import ArrowIpcSharedMemoryCache

    cache = ArrowIpcSharedMemoryCache(namespace="noetl-test", budget_bytes=1024)
    hint = cache.put_arrow_ipc(b"payload", schema_digest="schema-1", lease_seconds=1)

    deleted = cache.sweep_expired(
        now=datetime.now(timezone.utc) + timedelta(seconds=2)
    )

    assert deleted == 1
    with pytest.raises(FileNotFoundError):
        cache.get(hint)


@pytest.mark.asyncio
async def test_tempstore_put_ipc_bytes_uses_ipc_hint_and_durable_fallback():
    from noetl.core.storage import ArrowIpcSharedMemoryCache, Scope, StoreTier, TempStore

    store = TempStore()
    cache = ArrowIpcSharedMemoryCache(namespace="noetl-test", budget_bytes=1024)
    ref = await store.put_ipc_bytes(
        execution_id="exec-1",
        name="frame-1",
        data_bytes=b"arrow-frame",
        schema_digest="schema-1",
        row_count=10,
        scope=Scope.EXECUTION,
        store=StoreTier.MEMORY,
        ipc_cache=cache,
    )
    try:
        assert ref.ipc is not None
        assert ref.meta.media_type == "application/vnd.apache.arrow.stream"
        assert ref.meta.schema_digest == "schema-1"
        assert ref.meta.row_count == 10
        assert await store.get_ipc_bytes(ref, ipc_cache=cache) == b"arrow-frame"

        cache.delete(ref.ipc)
        assert await store.get_ipc_bytes(ref, ipc_cache=cache) == b"arrow-frame"
    finally:
        await store.delete(ref)
