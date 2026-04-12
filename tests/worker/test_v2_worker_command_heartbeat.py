import asyncio

import pytest

from noetl.worker.nats_worker import V2Worker


@pytest.mark.asyncio
async def test_command_heartbeat_loop_emits_periodic_events(monkeypatch):
    worker = V2Worker(worker_id="test-worker")
    worker._running = True
    worker._command_heartbeat_interval_seconds = 0.01
    worker._command_heartbeat_timeout_seconds = 0.01
    worker._command_heartbeat_max_retries = 1

    emitted: list[dict] = []

    async def _fake_emit_event(**kwargs):
        emitted.append(kwargs)
        return True

    monkeypatch.setattr(worker, "_emit_event", _fake_emit_event)

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        worker._command_heartbeat_loop(
            server_url="http://server",
            execution_id=101,
            step="run_step",
            command_id="cmd-101",
            stop_event=stop_event,
        )
    )

    await asyncio.sleep(0.035)
    stop_event.set()
    await task

    assert len(emitted) >= 2
    assert all(evt["name"] == "command.heartbeat" for evt in emitted)
    assert all(evt["payload"]["command_id"] == "cmd-101" for evt in emitted)


@pytest.mark.asyncio
async def test_command_heartbeat_loop_stops_without_emitting_when_already_stopped(monkeypatch):
    worker = V2Worker(worker_id="test-worker")
    worker._running = True
    worker._command_heartbeat_interval_seconds = 0.01

    async def _fail_if_called(**_kwargs):
        raise AssertionError("heartbeat event should not be emitted")

    monkeypatch.setattr(worker, "_emit_event", _fail_if_called)

    stop_event = asyncio.Event()
    stop_event.set()

    await worker._command_heartbeat_loop(
        server_url="http://server",
        execution_id=102,
        step="run_step",
        command_id="cmd-102",
        stop_event=stop_event,
    )
