import json

import pytest

from noetl.core.cache.nats_kv import NATSKVCache
from nats.js.errors import KeyNotFoundError as NatsKeyNotFoundError


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

    async def put(self, _key: str, value: bytes):
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


@pytest.mark.asyncio
async def test_set_loop_state_skips_existing_lookup_for_positive_collection_size(monkeypatch):
    cache = NATSKVCache()
    fake_kv = _FakeKV({"collection_size": 1, "completed_count": 0, "scheduled_count": 0})
    cache._kv = fake_kv
    lookup_calls = 0

    async def fake_get_loop_state(*_args, **_kwargs):
        nonlocal lookup_calls
        lookup_calls += 1
        return {"collection_size": 99}

    monkeypatch.setattr(cache, "get_loop_state", fake_get_loop_state)

    ok = await cache.set_loop_state(
        execution_id="e3",
        step_name="loop_step",
        state={"collection_size": 4, "completed_count": 0, "scheduled_count": 0},
        event_id="loop_3",
    )

    assert ok is True
    assert lookup_calls == 0
    assert fake_kv.payload["collection_size"] == 4


@pytest.mark.asyncio
async def test_set_loop_state_preserves_existing_collection_size_when_incoming_zero(monkeypatch):
    cache = NATSKVCache()
    fake_kv = _FakeKV({"collection_size": 1, "completed_count": 0, "scheduled_count": 0})
    cache._kv = fake_kv
    lookup_calls = 0

    async def fake_get_loop_state(*_args, **_kwargs):
        nonlocal lookup_calls
        lookup_calls += 1
        return {"collection_size": 8}

    monkeypatch.setattr(cache, "get_loop_state", fake_get_loop_state)

    ok = await cache.set_loop_state(
        execution_id="e4",
        step_name="loop_step",
        state={"collection_size": 0, "completed_count": 1, "scheduled_count": 1},
        event_id="loop_4",
    )

    assert ok is True
    assert lookup_calls == 1
    assert fake_kv.payload["collection_size"] == 8


# ── try_claim_loop_done ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_try_claim_loop_done_first_caller_wins():
    """First call sets loop_done_claimed=True and returns True."""
    cache = NATSKVCache()
    fake_kv = _FakeKV({"collection_size": 10, "completed_count": 10, "scheduled_count": 10})
    cache._kv = fake_kv

    result = await cache.try_claim_loop_done("exec1", "fetch_step", event_id="ev1")

    assert result is True
    assert fake_kv.payload["loop_done_claimed"] is True
    assert "loop_done_claimed_at" in fake_kv.payload


@pytest.mark.asyncio
async def test_try_claim_loop_done_second_caller_blocked():
    """Second call sees loop_done_claimed=True and returns False without CAS."""
    cache = NATSKVCache()
    fake_kv = _FakeKV({
        "collection_size": 10,
        "completed_count": 10,
        "loop_done_claimed": True,
        "loop_done_claimed_at": "2026-01-01T00:00:00Z",
    })
    cache._kv = fake_kv
    initial_revision = fake_kv.revision

    result = await cache.try_claim_loop_done("exec1", "fetch_step", event_id="ev1")

    assert result is False
    assert fake_kv.revision == initial_revision  # no write happened


@pytest.mark.asyncio
async def test_try_claim_loop_done_key_not_found():
    """Missing NATS key returns False without raising."""
    cache = NATSKVCache()

    class _MissingKV:
        async def get(self, _key):
            raise NatsKeyNotFoundError()

    cache._kv = _MissingKV()

    result = await cache.try_claim_loop_done("exec1", "fetch_step", event_id="ev1")

    assert result is False


@pytest.mark.asyncio
async def test_try_claim_loop_done_retries_on_concurrent_write():
    """CAS conflict on first attempt is retried and succeeds on second."""
    cache = NATSKVCache()
    call_count = 0

    class _RacingKV:
        def __init__(self):
            self.payload = {"collection_size": 5, "completed_count": 5}
            self.revision = 1

        async def get(self, _key):
            return _FakeKVEntry(self.payload, self.revision)

        async def update(self, _key, value, last):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("wrong last sequence")
            assert last == self.revision
            self.payload = json.loads(value.decode("utf-8"))
            self.revision += 1
            return self.revision

    cache._kv = _RacingKV()

    result = await cache.try_claim_loop_done("exec1", "fetch_step", event_id="ev1")

    assert result is True
    assert call_count == 2  # first attempt raced, second succeeded
