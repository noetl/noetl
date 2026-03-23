import pytest

from noetl.core.messaging.nats_client import NATSCommandPublisher


class _FakeJetStream:
    def __init__(self, fail=False):
        self.fail = fail
        self.published = []

    async def publish(self, subject, payload):
        if self.fail:
            raise RuntimeError("publish failed")
        self.published.append((subject, payload))


class _FakeNC:
    def __init__(self):
        self.is_connected = True
        self.is_closed = False
        self.closed = False

    async def close(self):
        self.closed = True
        self.is_closed = True
        self.is_connected = False


@pytest.mark.asyncio
async def test_publish_command_reconnects_and_retries_after_failure(monkeypatch):
    publisher = NATSCommandPublisher(
        nats_url="nats://example",
        subject="commands",
        stream_name="NOETL_COMMANDS",
    )
    first_js = _FakeJetStream(fail=True)
    second_js = _FakeJetStream(fail=False)
    publisher._nc = _FakeNC()
    publisher._js = first_js

    ensure_calls = []

    async def _fake_ensure_connected(force=False):
        ensure_calls.append(force)
        if force:
            publisher._nc = _FakeNC()
            publisher._js = second_js

    monkeypatch.setattr(publisher, "ensure_connected", _fake_ensure_connected)

    await publisher.publish_command(
        execution_id=123,
        event_id=456,
        command_id="cmd-456",
        step="start",
        server_url="http://server",
    )

    assert ensure_calls == [False, True]
    assert len(second_js.published) == 1
