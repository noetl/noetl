import pytest

from noetl.core.storage.models import Scope, StoreTier
from noetl.core.storage.result_store import TempStore
from noetl.core.storage.scope_tracker import ScopeTracker


@pytest.mark.asyncio
async def test_put_registers_ref_with_scope_tracker():
    tracker = ScopeTracker()
    store = TempStore(
        scope_tracker=tracker,
        max_ref_cache_entries=100,
        max_memory_cache_entries=100,
    )

    ref = await store.put(
        execution_id = "99013",
        name="fetch_data",
        data={"status": "ok"},
        scope=Scope.EXECUTION,
        store=StoreTier.MEMORY,
        source_step="fetch_data",
    )

    refs = tracker.get_refs_for_execution_cleanup("exec-tracked")
    assert ref.ref in refs


@pytest.mark.asyncio
async def test_cache_eviction_keeps_refs_tracked_for_cleanup(monkeypatch):
    tracker = ScopeTracker()
    store = TempStore(
        scope_tracker=tracker,
        max_ref_cache_entries=2,
        max_memory_cache_entries=2,
    )

    async def _skip_direct_fetch(_ref: str):
        return None

    # Keep test deterministic and local; don't reach external storage backends.
    monkeypatch.setattr(store, "_fetch_direct", _skip_direct_fetch)

    refs = []
    for idx in range(3):
        ref = await store.put(
            execution_id = "99014",
            name=f"step_{idx}",
            data={"idx": idx},
            scope=Scope.EXECUTION,
            store=StoreTier.MEMORY,
            source_step=f"step_{idx}",
        )
        refs.append(ref)

    # Oldest entry should no longer resolve once evicted.
    with pytest.raises(KeyError):
        await store.get(refs[0])

    # Newer refs remain available.
    assert await store.get(refs[1]) == {"idx": 1}
    assert await store.get(refs[2]) == {"idx": 2}

    # Scope tracker should keep evicted refs so lifecycle cleanup can still run.
    tracked = tracker.get_refs_for_execution_cleanup("exec-evict")
    assert set(tracked) == {refs[0].ref, refs[1].ref, refs[2].ref}


@pytest.mark.asyncio
async def test_lru_hit_updates_recency_before_eviction(monkeypatch):
    tracker = ScopeTracker()
    store = TempStore(
        scope_tracker=tracker,
        max_ref_cache_entries=2,
        max_memory_cache_entries=2,
    )

    async def _skip_direct_fetch(_ref: str):
        return None

    monkeypatch.setattr(store, "_fetch_direct", _skip_direct_fetch)

    first_ref = await store.put(
        execution_id = "99015",
        name="step_1",
        data={"idx": 1},
        scope=Scope.EXECUTION,
        store=StoreTier.MEMORY,
        source_step="step_1",
    )
    second_ref = await store.put(
        execution_id = "99015",
        name="step_2",
        data={"idx": 2},
        scope=Scope.EXECUTION,
        store=StoreTier.MEMORY,
        source_step="step_2",
    )

    # Touch first entry so second becomes LRU.
    assert await store.get(first_ref) == {"idx": 1}

    third_ref = await store.put(
        execution_id = "99015",
        name="step_3",
        data={"idx": 3},
        scope=Scope.EXECUTION,
        store=StoreTier.MEMORY,
        source_step="step_3",
    )

    with pytest.raises(KeyError):
        await store.get(second_ref)
    assert await store.get(first_ref) == {"idx": 1}
    assert await store.get(third_ref) == {"idx": 3}


class _FakeKVBackend:
    def __init__(self):
        self.stored = {}
        self.deleted = []

    async def put(self, key: str, data: bytes):
        self.stored[key] = data
        return f"fake-kv://{key}"

    async def delete(self, key: str):
        self.deleted.append(key)
        self.stored.pop(key, None)
        return True


class _FakeNoopBackend:
    async def delete(self, key: str):
        return False


@pytest.mark.asyncio
async def test_cleanup_deletes_evicted_non_memory_refs():
    tracker = ScopeTracker()
    store = TempStore(
        scope_tracker=tracker,
        max_ref_cache_entries=1,
        max_memory_cache_entries=1,
    )
    fake_kv = _FakeKVBackend()
    store._kv_backend = fake_kv
    store._object_backend = _FakeNoopBackend()
    store._s3_backend = _FakeNoopBackend()
    store._gcs_backend = _FakeNoopBackend()

    ref1 = await store.put(
        execution_id = "99016",
        name="step_1",
        data={"idx": 1},
        scope=Scope.EXECUTION,
        store=StoreTier.KV,
        source_step="step_1",
    )
    ref2 = await store.put(
        execution_id = "99016",
        name="step_2",
        data={"idx": 2},
        scope=Scope.EXECUTION,
        store=StoreTier.KV,
        source_step="step_2",
    )

    # ref1 metadata may be evicted, but cleanup tracking should still preserve both refs.
    tracked_refs = tracker.get_refs_for_execution_cleanup("exec-kv-cleanup")
    assert set(tracked_refs) == {ref1.ref, ref2.ref}

    deleted = 0
    for ref in tracked_refs:
        if await store.delete(ref):
            deleted += 1
    assert deleted == 2
    assert len(fake_kv.deleted) == 2


@pytest.mark.asyncio
async def test_resolve_result_ref_returns_full_payload_not_preview():
    store = TempStore(
        max_ref_cache_entries=10,
        max_memory_cache_entries=10,
    )

    payload = {
        "tool_config": {
            "kind": "python",
            "code": "def main(): return {'status': 'ok'}",
        },
        "render_context": {"value": 1},
    }

    ref = await store.put(
        execution_id = "99017",
        name="command_context",
        data=payload,
        scope=Scope.EXECUTION,
        store=StoreTier.MEMORY,
        source_step="start",
    )

    resolved = await store.resolve(ref.model_dump())

    assert resolved == payload
    assert resolved["tool_config"]["code"].startswith("def main")
