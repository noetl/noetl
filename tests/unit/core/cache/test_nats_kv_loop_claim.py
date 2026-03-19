import json

import pytest

from noetl.core.cache.nats_kv import NATSKVCache


class _FakeKVEntry:
    def __init__(self, payload: dict, revision: int):
        self.value = json.dumps(payload).encode("utf-8")
        self.revision = revision


class _FakeKV:
    def __init__(self, payload: dict):
        self.payload = dict(payload)
        self.revision = 1

    async def get(self, _key: str):
        return _FakeKVEntry(self.payload, self.revision)

    async def update(self, _key: str, value: bytes, last: int):
        assert last == self.revision
        self.payload = json.loads(value.decode("utf-8"))
        self.revision += 1
        return self.revision


@pytest.mark.asyncio
async def test_claim_next_loop_index_preserves_existing_nonzero_collection_size():
    cache = NATSKVCache()
    fake_kv = _FakeKV(
        {
            "collection_size": 7,
            "completed_count": 1,
            "scheduled_count": 1,
        }
    )
    cache._kv = fake_kv

    claimed = await cache.claim_next_loop_index(
        execution_id="e1",
        step_name="loop_step",
        collection_size=0,
        max_in_flight=4,
        event_id="loop_1",
    )

    assert claimed == 1
    assert fake_kv.payload["collection_size"] == 7
    assert fake_kv.payload["scheduled_count"] == 2


@pytest.mark.asyncio
async def test_claim_next_loop_index_keeps_zero_when_no_existing_size():
    cache = NATSKVCache()
    fake_kv = _FakeKV(
        {
            "collection_size": 0,
            "completed_count": 0,
            "scheduled_count": 0,
        }
    )
    cache._kv = fake_kv

    claimed = await cache.claim_next_loop_index(
        execution_id="e2",
        step_name="loop_step",
        collection_size=0,
        max_in_flight=2,
        event_id="loop_2",
    )

    assert claimed is None
    assert fake_kv.payload["collection_size"] == 0
    assert fake_kv.payload["scheduled_count"] == 0
