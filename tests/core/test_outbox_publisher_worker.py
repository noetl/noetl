from __future__ import annotations

import pytest


def test_load_outbox_publisher_settings_from_env(monkeypatch):
    from noetl.outbox.worker import load_outbox_publisher_settings

    monkeypatch.setenv("NOETL_OUTBOX_PUBLISHER_BATCH_SIZE", "25")
    monkeypatch.setenv("NOETL_OUTBOX_PUBLISHER_IDLE_SLEEP_SECONDS", "0.2")
    monkeypatch.setenv("NOETL_OUTBOX_PUBLISHER_ERROR_SLEEP_SECONDS", "2.5")
    monkeypatch.setenv("NOETL_OUTBOX_PUBLISHER_ONCE", "true")

    settings = load_outbox_publisher_settings()

    assert settings.batch_size == 25
    assert settings.idle_sleep_seconds == 0.2
    assert settings.error_sleep_seconds == 2.5
    assert settings.once is True


@pytest.mark.asyncio
async def test_run_outbox_publisher_once_initializes_publishes_and_closes(monkeypatch):
    import noetl.outbox.worker as worker

    calls = []

    async def init_pool(conninfo):
        calls.append(("init", conninfo))

    async def close_pool():
        calls.append(("close", None))

    async def ensure_schema():
        calls.append(("ensure", None))

    async def publish_batch(*, limit):
        calls.append(("publish", limit))
        return 3

    monkeypatch.setattr(worker, "get_pgdb_connection", lambda: "dbname=noetl")
    monkeypatch.setattr(worker, "init_pool", init_pool)
    monkeypatch.setattr(worker, "close_pool", close_pool)
    monkeypatch.setattr(worker, "ensure_outbox_schema", ensure_schema)
    monkeypatch.setattr(worker, "publish_outbox_batch", publish_batch)

    await worker.run_outbox_publisher(
        worker.OutboxPublisherSettings(batch_size=7, once=True)
    )

    assert calls == [
        ("init", "dbname=noetl"),
        ("ensure", None),
        ("publish", 7),
        ("close", None),
    ]


@pytest.mark.asyncio
async def test_run_outbox_publisher_sleeps_when_idle_then_handles_cancel(monkeypatch):
    import asyncio

    import noetl.outbox.worker as worker

    calls = []

    async def init_pool(conninfo):  # noqa: ARG001
        calls.append("init")

    async def close_pool():
        calls.append("close")

    async def ensure_schema():
        calls.append("ensure")

    async def publish_batch(*, limit):  # noqa: ARG001
        calls.append("publish")
        return 0

    async def sleep(seconds):  # noqa: ARG001
        calls.append("sleep")
        raise asyncio.CancelledError()

    monkeypatch.setattr(worker, "get_pgdb_connection", lambda: "dbname=noetl")
    monkeypatch.setattr(worker, "init_pool", init_pool)
    monkeypatch.setattr(worker, "close_pool", close_pool)
    monkeypatch.setattr(worker, "ensure_outbox_schema", ensure_schema)
    monkeypatch.setattr(worker, "publish_outbox_batch", publish_batch)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_outbox_publisher(worker.OutboxPublisherSettings())

    assert calls == ["init", "ensure", "publish", "sleep", "close"]

