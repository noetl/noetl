from types import SimpleNamespace

import pytest

from noetl.core.messaging.nats_client import NATSCommandSubscriber
from noetl.core.config import WorkerSettings


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


# ---------------------------------------------------------------------------
# ack_wait lower-bound tests
# ---------------------------------------------------------------------------

def _make_worker_settings(**overrides) -> WorkerSettings:
    """Build a WorkerSettings with safe defaults, applying keyword overrides."""
    defaults = dict(
        NOETL_WORKER_POOL_RUNTIME="cpu",
        NOETL_SERVER_URL="http://localhost:8082",
        NOETL_WORKER_BASE_URL="http://queue-worker",
        NOETL_DEREGISTER_RETRIES="3",
        NOETL_DEREGISTER_BACKOFF="0.5",
        NOETL_DISABLE_METRICS="true",
        NOETL_WORKER_METRICS_INTERVAL="60",
        NOETL_WORKER_HEARTBEAT_INTERVAL="15",
        NOETL_HOST="localhost",
        NOETL_PORT="8082",
        NOETL_MAX_WORKERS="8",
        NATS_URL="nats://localhost:4222",
        NATS_USER="noetl",
        NATS_PASSWORD="noetl",
        NATS_STREAM="NOETL_COMMANDS",
        NATS_CONSUMER="noetl_worker_pool",
        NATS_SUBJECT="noetl.commands",
        NOETL_WORKER_NATS_FETCH_TIMEOUT_SECONDS="30",
        NOETL_WORKER_NATS_FETCH_HEARTBEAT_SECONDS="5",
        NOETL_WORKER_NATS_MAX_ACK_PENDING="64",
        NOETL_WORKER_NATS_MAX_DELIVER="1000",
        NOETL_WORKER_NATS_ACK_WAIT_SECONDS="300",
        NOETL_WORKER_NATS_ACK_WAIT_BUFFER_SECONDS="120",
        NOETL_KEYCHAIN_REFRESH_THRESHOLD="300",
        NOETL_WORKER_HTTP_TIMEOUT="120",
        NOETL_WORKER_EVENT_TIMEOUT="60",
        NOETL_WORKER_COMMAND_TIMEOUT_SECONDS="180",
        NOETL_WORKER_MAX_INFLIGHT_COMMANDS="8",
        NOETL_WORKER_MAX_INFLIGHT_DB_COMMANDS="4",
        NOETL_WORKER_THROTTLE_POLL_INTERVAL_SECONDS="0.2",
        NOETL_WORKER_POSTGRES_POOL_WAITING_THRESHOLD="2",
    )
    defaults.update(overrides)
    return WorkerSettings(**defaults)


def test_worker_settings_default_ack_wait_satisfies_lower_bound():
    """Default ack_wait (300s) must be >= command_timeout (180s) + buffer (120s)."""
    ws = _make_worker_settings()
    assert ws.nats_ack_wait_seconds >= ws.command_timeout_seconds + ws.nats_ack_wait_buffer_seconds


def test_worker_settings_ack_wait_too_short_raises():
    """ack_wait below command_timeout + buffer must be rejected at construction time."""
    with pytest.raises(ValueError, match="NOETL_WORKER_NATS_ACK_WAIT_SECONDS"):
        _make_worker_settings(
            NOETL_WORKER_COMMAND_TIMEOUT_SECONDS="180",
            NOETL_WORKER_NATS_ACK_WAIT_BUFFER_SECONDS="120",
            NOETL_WORKER_NATS_ACK_WAIT_SECONDS="299",  # 299 < 180+120=300
        )


def test_worker_settings_ack_wait_exact_lower_bound_is_accepted():
    """ack_wait exactly equal to command_timeout + buffer is valid."""
    ws = _make_worker_settings(
        NOETL_WORKER_COMMAND_TIMEOUT_SECONDS="180",
        NOETL_WORKER_NATS_ACK_WAIT_BUFFER_SECONDS="120",
        NOETL_WORKER_NATS_ACK_WAIT_SECONDS="300",
    )
    assert ws.nats_ack_wait_seconds == 300.0


def test_worker_settings_custom_ack_wait_above_lower_bound_is_accepted():
    """A user-specified ack_wait above the lower bound should be accepted."""
    ws = _make_worker_settings(
        NOETL_WORKER_COMMAND_TIMEOUT_SECONDS="180",
        NOETL_WORKER_NATS_ACK_WAIT_BUFFER_SECONDS="120",
        NOETL_WORKER_NATS_ACK_WAIT_SECONDS="600",
    )
    assert ws.nats_ack_wait_seconds == 600.0


@pytest.mark.asyncio
async def test_consumer_config_uses_configured_ack_wait():
    """_consumer_config() must use nats_ack_wait_seconds, not a hardcoded value."""
    subscriber = NATSCommandSubscriber(
        consumer_name="test-consumer",
        stream_name="NOETL_COMMANDS",
        max_ack_pending=64,
        max_inflight=1,
    )
    # Default ack_wait from settings (300s).
    config = subscriber._consumer_config()
    assert config.ack_wait == int(subscriber.ack_wait_seconds)


@pytest.mark.asyncio
async def test_consumer_config_ack_wait_exceeds_legacy_hardcoded_value():
    """Verify the fix: ack_wait must be > 30 (the previously hardcoded value)."""
    subscriber = NATSCommandSubscriber(
        consumer_name="test-consumer",
        stream_name="NOETL_COMMANDS",
        max_ack_pending=64,
        max_inflight=1,
    )
    config = subscriber._consumer_config()
    assert config.ack_wait > 30, (
        f"ack_wait={config.ack_wait} is not greater than the legacy hardcoded 30s; "
        "redelivery storms may occur under load"
    )
