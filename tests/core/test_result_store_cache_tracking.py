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
async def test_cache_eviction_untracks_refs():
    tracker = ScopeTracker()
    store = TempStore(
        scope_tracker=tracker,
        max_ref_cache_entries=2,
        max_memory_cache_entries=2,
    )

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
        refs.append(ref.ref)

    # Oldest entry is evicted from both caches when limits are reached.
    assert len(store._ref_cache) == 2
    assert len(store._memory_cache) == 2
    assert refs[0] not in store._ref_cache
    assert refs[0] not in store._memory_cache

    # Scope tracker should not keep evicted refs.
    tracked = tracker.get_refs_for_execution_cleanup("exec-evict")
    assert refs[0] not in tracked
    assert refs[1] in tracked
    assert refs[2] in tracked
