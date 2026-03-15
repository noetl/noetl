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
        execution_id="exec-tracked",
        name="fetch_data",
        data={"status": "ok"},
        scope=Scope.EXECUTION,
        store=StoreTier.MEMORY,
        source_step="fetch_data",
    )

    refs = tracker.get_refs_for_execution_cleanup("exec-tracked")
    assert ref.ref in refs


@pytest.mark.asyncio
async def test_cache_eviction_untracks_refs(monkeypatch):
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
            execution_id="exec-evict",
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

    # Scope tracker should not keep evicted refs.
    tracked = tracker.get_refs_for_execution_cleanup("exec-evict")
    assert refs[0].ref not in tracked
    assert refs[1].ref in tracked
    assert refs[2].ref in tracked


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
        execution_id="exec-lru",
        name="step_1",
        data={"idx": 1},
        scope=Scope.EXECUTION,
        store=StoreTier.MEMORY,
        source_step="step_1",
    )
    second_ref = await store.put(
        execution_id="exec-lru",
        name="step_2",
        data={"idx": 2},
        scope=Scope.EXECUTION,
        store=StoreTier.MEMORY,
        source_step="step_2",
    )

    # Touch first entry so second becomes LRU.
    assert await store.get(first_ref) == {"idx": 1}

    third_ref = await store.put(
        execution_id="exec-lru",
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
