from types import SimpleNamespace

import pytest

from noetl.core.messaging.nats_client import NATSCommandSubscriber


def _consumer_info(max_ack_pending: int):
    return SimpleNamespace(config=SimpleNamespace(max_ack_pending=max_ack_pending))


class _FakeJetStream:
    def __init__(self, consumer_info_results=None, add_consumer_error=None):
        self._consumer_info_results = list(consumer_info_results or [])
        self._add_consumer_error = add_consumer_error
        self.add_consumer_calls = []
        self.delete_consumer_calls = []

    async def consumer_info(self, stream, consumer):
        if self._consumer_info_results:
            next_result = self._consumer_info_results.pop(0)
            if isinstance(next_result, Exception):
                raise next_result
            return next_result
        raise RuntimeError(f"consumer not found: {stream}/{consumer}")

    async def add_consumer(self, stream, config):
        self.add_consumer_calls.append((stream, config))
        if self._add_consumer_error:
            error = self._add_consumer_error
            self._add_consumer_error = None
            raise error

    async def delete_consumer(self, stream, consumer):
        self.delete_consumer_calls.append((stream, consumer))


@pytest.mark.asyncio
async def test_ensure_consumer_creates_when_missing():
    subscriber = NATSCommandSubscriber(
        consumer_name="test-consumer",
        stream_name="NOETL_COMMANDS",
        max_ack_pending=64,
        max_inflight=1,
    )
    fake_js = _FakeJetStream(consumer_info_results=[RuntimeError("consumer not found")])
    subscriber._js = fake_js

    await subscriber._ensure_consumer()

    assert len(fake_js.add_consumer_calls) == 1
    _, config = fake_js.add_consumer_calls[0]
    assert config.max_ack_pending == 64
    assert fake_js.delete_consumer_calls == []


@pytest.mark.asyncio
async def test_ensure_consumer_recreates_when_ack_pending_mismatch():
    subscriber = NATSCommandSubscriber(
        consumer_name="test-consumer",
        stream_name="NOETL_COMMANDS",
        max_ack_pending=64,
        max_inflight=1,
    )
    fake_js = _FakeJetStream(consumer_info_results=[_consumer_info(1000)])
    subscriber._js = fake_js

    await subscriber._ensure_consumer()

    assert fake_js.delete_consumer_calls == [("NOETL_COMMANDS", "test-consumer")]
    assert len(fake_js.add_consumer_calls) == 1
    _, config = fake_js.add_consumer_calls[0]
    assert config.max_ack_pending == 64


@pytest.mark.asyncio
async def test_add_consumer_tolerates_race_when_existing_consumer_matches_config():
    subscriber = NATSCommandSubscriber(
        consumer_name="test-consumer",
        stream_name="NOETL_COMMANDS",
        max_ack_pending=64,
        max_inflight=1,
    )
    fake_js = _FakeJetStream(
        consumer_info_results=[
            RuntimeError("consumer not found"),
            _consumer_info(64),
        ],
        add_consumer_error=RuntimeError("consumer already exists"),
    )
    subscriber._js = fake_js

    await subscriber._ensure_consumer()

    assert len(fake_js.add_consumer_calls) == 1
    _, config = fake_js.add_consumer_calls[0]
    assert config.max_ack_pending == 64
    assert fake_js.delete_consumer_calls == []
