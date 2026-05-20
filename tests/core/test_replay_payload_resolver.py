import hashlib
import json

import pytest


@pytest.mark.asyncio
async def test_temp_store_replay_payload_resolver_returns_bounded_summary():
    from noetl.core.storage import Scope, StoreTier, TempStore
    from noetl.server.api.replay import TempStoreReplayPayloadResolver

    store = TempStore(max_ref_cache_entries=10, max_memory_cache_entries=10)
    rows = [{"id": 1}, {"id": 2}]
    ref = await store.put(
        execution_id="123",
        name="frame_rows",
        data=rows,
        scope=Scope.EXECUTION,
        store=StoreTier.MEMORY,
    )

    resolution = await TempStoreReplayPayloadResolver(store).resolve_payload_ref(
        ref.model_dump(mode="json")
    )

    payload_bytes = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert resolution.resolved is True
    assert resolution.ref == ref.ref
    assert resolution.checksum == hashlib.sha256(payload_bytes).hexdigest()
    assert resolution.size_bytes == len(payload_bytes)
    assert resolution.row_count == 2
    assert resolution.value_type == "list"
    assert resolution.error is None


@pytest.mark.asyncio
async def test_temp_store_replay_payload_resolver_reports_missing_locator():
    from noetl.core.storage import TempStore
    from noetl.server.api.replay import TempStoreReplayPayloadResolver

    resolution = await TempStoreReplayPayloadResolver(TempStore()).resolve_payload_ref(
        {"sha256": "abc"}
    )

    assert resolution.resolved is False
    assert resolution.checksum is None
    assert resolution.error == "payload reference has no resolvable locator"
