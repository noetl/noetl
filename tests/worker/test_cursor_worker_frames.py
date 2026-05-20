from __future__ import annotations

import asyncio
import threading
import time

import pytest
from jinja2 import Environment


class _FakeCursorDriver:
    kind = "frame_test"

    def __init__(self, rows):
        self.rows = list(rows)
        self.claim_contexts = []

    async def open(self, auth, spec):
        return self

    async def claim(self, handle, context):
        self.claim_contexts.append(dict(context))
        if not self.rows:
            return None
        return self.rows.pop(0)

    async def close(self, handle):
        return None


class _FakeStore:
    def __init__(self):
        self.puts = []

    async def put_ipc_bytes(self, **kwargs):
        from noetl.core.storage import Scope, StoreTier, TempRef, TempRefMeta

        self.puts.append(kwargs)
        return TempRef.create(
            execution_id=kwargs["execution_id"],
            name=kwargs["name"],
            store=kwargs.get("store") or StoreTier.KV,
            scope=kwargs.get("scope") or Scope.EXECUTION,
            meta=TempRefMeta(
                content_type=kwargs["media_type"],
                media_type=kwargs["media_type"],
                bytes=len(kwargs["data_bytes"]),
                schema_digest=kwargs["schema_digest"],
                row_count=kwargs["row_count"],
                encoding="binary",
            ),
        )


class _FakeBatchCursorDriver(_FakeCursorDriver):
    kind = "frame_batch_test"

    def __init__(self, rows):
        super().__init__(rows)
        self.claim_many_contexts = []

    async def claim_many(self, handle, context, max_rows):
        self.claim_many_contexts.append({"context": dict(context), "max_rows": max_rows})
        claimed = self.rows[:max_rows]
        self.rows = self.rows[max_rows:]
        return claimed


class _FakeResponse:
    def raise_for_status(self):
        return None


class _FakeAsyncClient:
    calls = []

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json):
        self.calls.append({"url": url, "json": json, "timeout": self.timeout})
        return _FakeResponse()


class _FakeSyncClient:
    calls = []

    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def post(self, url, json):
        self.calls.append({"url": url, "json": json, "timeout": self.timeout})
        return _FakeResponse()


def test_worker_locality_hint_uses_topology_env(monkeypatch):
    from noetl.worker import cursor_worker

    monkeypatch.setenv("NOETL_NODE_ID", "node-a")
    monkeypatch.setenv("NOETL_CLUSTER_ID", "cluster-a")
    monkeypatch.setenv("NOETL_REGION", "us-central1")
    monkeypatch.setenv("NOETL_ZONE", "us-central1-a")
    monkeypatch.setenv("NOETL_WORKER_POOL_NAME", "worker-cpu-01")
    monkeypatch.setenv("NOETL_WORKER_POOL_RUNTIME", "cpu")

    assert cursor_worker._worker_locality_hint() == {
        "node_id": "node-a",
        "cluster_id": "cluster-a",
        "region": "us-central1",
        "zone": "us-central1-a",
        "worker_pool": "worker-cpu-01",
        "runtime": "cpu",
    }


@pytest.mark.asyncio
async def test_start_runtime_frame_emits_running_heartbeat(monkeypatch):
    from noetl.worker import cursor_worker

    _FakeAsyncClient.calls = []
    monkeypatch.setattr(cursor_worker.httpx, "AsyncClient", _FakeAsyncClient)

    await cursor_worker._start_runtime_frame(
        context={"server_url": "http://runtime"},
        runtime_frame={"frame_id": 9},
        worker_slot_id="slot-1",
        lease_seconds=45,
    )

    assert _FakeAsyncClient.calls == [
        {
            "url": "http://runtime/api/frames/9/heartbeat",
            "json": {
                "worker_id": "slot-1",
                "status": "RUNNING",
                "lease_seconds": 45,
            },
            "timeout": 30.0,
        }
    ]


@pytest.mark.asyncio
async def test_runtime_frame_heartbeat_loop_extends_lease_until_stopped(monkeypatch):
    from noetl.worker import cursor_worker

    _FakeAsyncClient.calls = []
    monkeypatch.setattr(cursor_worker.httpx, "AsyncClient", _FakeAsyncClient)

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        cursor_worker._runtime_frame_heartbeat_loop(
            context={"server_url": "http://runtime"},
            runtime_frame={"frame_id": 12},
            worker_slot_id="slot-2",
            lease_seconds=60,
            heartbeat_seconds=0.01,
            stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.25)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert len(_FakeAsyncClient.calls) >= 2
    assert all(call["url"] == "http://runtime/api/frames/12/heartbeat" for call in _FakeAsyncClient.calls)
    assert all(call["json"]["status"] == "RUNNING" for call in _FakeAsyncClient.calls)
    assert all(call["json"]["lease_seconds"] == 60 for call in _FakeAsyncClient.calls)


def test_runtime_frame_heartbeat_thread_extends_lease_until_stopped(monkeypatch):
    from noetl.worker import cursor_worker

    _FakeSyncClient.calls = []
    monkeypatch.setattr(cursor_worker.httpx, "Client", _FakeSyncClient)

    stop_event = threading.Event()
    thread = threading.Thread(
        target=cursor_worker._runtime_frame_heartbeat_thread,
        kwargs={
            "context": {"server_url": "http://runtime"},
            "runtime_frame": {"frame_id": 14},
            "worker_slot_id": "slot-4",
            "lease_seconds": 90,
            "heartbeat_seconds": 0.001,
            "stop_event": stop_event,
        },
    )
    thread.start()
    deadline = time.monotonic() + 1.0
    while len(_FakeSyncClient.calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    stop_event.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(_FakeSyncClient.calls) >= 2
    assert all(call["url"] == "http://runtime/api/frames/14/heartbeat" for call in _FakeSyncClient.calls)
    assert all(call["json"]["status"] == "RUNNING" for call in _FakeSyncClient.calls)
    assert all(call["json"]["lease_seconds"] == 90 for call in _FakeSyncClient.calls)


@pytest.mark.asyncio
async def test_cursor_worker_claims_and_serializes_bounded_frames(monkeypatch):
    from noetl.core.cursor_drivers import register_driver
    from noetl.core.storage import arrow_ipc_to_rows
    from noetl.worker import cursor_worker

    driver = _FakeCursorDriver(
        [
            {"id": 1, "status": "pending"},
            {"id": 2, "status": "pending"},
            {"id": 3, "status": "pending"},
        ]
    )
    register_driver(driver.kind, driver)
    fake_store = _FakeStore()
    monkeypatch.setattr(cursor_worker, "default_store", fake_store)
    monkeypatch.setattr(cursor_worker, "_frame_ipc_cache", lambda: None)
    async def fetch_credential(auth_key):
        return {"dsn": "memory"}

    monkeypatch.setattr(cursor_worker, "fetch_credential_by_key_async", fetch_credential)

    seen_iter = []

    async def tool_executor(kind, cfg, ctx):
        seen_iter.append(dict(ctx["iter"]["item"]))
        return {"status": "ok"}

    result = await cursor_worker.execute_cursor_worker(
        config={
            "cursor": {
                "kind": driver.kind,
                "auth": "pg",
                "claim": "select next",
                "options": {"max_iterations": 10},
            },
            "iterator": "item",
            "tasks": [{"name": "process_item", "kind": "noop"}],
            "frame_policy": {"max_rows": 2, "max_seconds": 30, "max_bytes": 4096},
        },
        context={"execution_id": 42},
        jinja_env=Environment(),
        tool_executor=tool_executor,
        render_template=lambda template, ctx: template,
        render_dict=lambda data, ctx: data,
        worker_slot_id="slot-1",
    )

    assert result["status"] == "ok"
    assert result["processed"] == 3
    assert result["frame_count"] == 2
    assert [frame["row_count"] for frame in result["frames"]] == [2, 1]
    assert result["frames"][0]["metrics"]["row_count"] == 2
    assert result["frames"][0]["metrics"]["rows"]["ok"] == 2
    assert result["frames"][0]["metrics"]["tasks"]["by_kind"]["noop"]["count"] == 2
    assert seen_iter == [
        {"id": 1, "status": "pending"},
        {"id": 2, "status": "pending"},
        {"id": 3, "status": "pending"},
    ]

    first_frame_rows = arrow_ipc_to_rows(fake_store.puts[0]["data_bytes"])
    assert first_frame_rows == [
        {"id": 1, "status": "pending"},
        {"id": 2, "status": "pending"},
    ]
    assert fake_store.puts[0]["row_count"] == 2
    assert fake_store.puts[0]["media_type"] == "application/vnd.apache.arrow.stream"
    assert driver.claim_contexts[0]["frame_index"] == 0
    assert driver.claim_contexts[1]["frame_row_index"] == 1


@pytest.mark.asyncio
async def test_cursor_worker_uses_batched_claim_path(monkeypatch):
    from noetl.core.cursor_drivers import register_driver
    from noetl.worker import cursor_worker

    driver = _FakeBatchCursorDriver(
        [
            {"id": 1, "status": "pending"},
            {"id": 2, "status": "pending"},
            {"id": 3, "status": "pending"},
        ]
    )
    register_driver(driver.kind, driver)
    fake_store = _FakeStore()
    monkeypatch.setattr(cursor_worker, "default_store", fake_store)
    monkeypatch.setattr(cursor_worker, "_frame_ipc_cache", lambda: None)

    async def fetch_credential(auth_key):
        return {"dsn": "memory"}

    monkeypatch.setattr(cursor_worker, "fetch_credential_by_key_async", fetch_credential)

    seen_indexes = []

    async def tool_executor(kind, cfg, ctx):
        seen_indexes.append(ctx["iter"]["item"]["id"])
        return {"status": "ok"}

    result = await cursor_worker.execute_cursor_worker(
        config={
            "cursor": {
                "kind": driver.kind,
                "auth": "pg",
                "claim": "select next limit {{ __frame_max_rows }}",
                "options": {"max_iterations": 10},
            },
            "iterator": "item",
            "tasks": [{"name": "process_item", "kind": "noop"}],
            "frame_policy": {"max_rows": 2, "max_seconds": 30, "max_bytes": 4096},
        },
        context={"execution_id": 42},
        jinja_env=Environment(),
        tool_executor=tool_executor,
        render_template=lambda template, ctx: template.replace("{{ __frame_max_rows }}", str(ctx["__frame_max_rows"])),
        render_dict=lambda data, ctx: data,
        worker_slot_id="slot-1",
    )

    assert result["status"] == "ok"
    assert result["processed"] == 3
    assert result["frame_count"] == 2
    assert seen_indexes == [1, 2, 3]
    assert driver.claim_contexts == []
    assert [call["max_rows"] for call in driver.claim_many_contexts] == [2, 2, 2]
    assert driver.claim_many_contexts[0]["context"]["max_rows"] == 2


@pytest.mark.asyncio
async def test_cursor_worker_processes_frame_rows_concurrently(monkeypatch):
    from noetl.core.cursor_drivers import register_driver
    from noetl.worker import cursor_worker

    driver = _FakeBatchCursorDriver(
        [
            {"id": 1, "status": "pending"},
            {"id": 2, "status": "pending"},
            {"id": 3, "status": "pending"},
            {"id": 4, "status": "pending"},
        ]
    )
    register_driver(driver.kind, driver)
    fake_store = _FakeStore()
    monkeypatch.setattr(cursor_worker, "default_store", fake_store)
    monkeypatch.setattr(cursor_worker, "_frame_ipc_cache", lambda: None)

    async def fetch_credential(auth_key):
        return {"dsn": "memory"}

    monkeypatch.setattr(cursor_worker, "fetch_credential_by_key_async", fetch_credential)

    seen_indexes = []

    async def tool_executor(kind, cfg, ctx):
        seen_indexes.append(ctx["iter"]["item"]["id"])
        await asyncio.sleep(0.05)
        return {"status": "ok"}

    started = time.monotonic()
    result = await cursor_worker.execute_cursor_worker(
        config={
            "cursor": {
                "kind": driver.kind,
                "auth": "pg",
                "claim": "select next limit {{ __frame_max_rows }}",
                "options": {"max_iterations": 10},
            },
            "iterator": "item",
            "tasks": [{"name": "process_item", "kind": "noop"}],
            "frame_policy": {
                "max_rows": 4,
                "max_seconds": 30,
                "max_bytes": 4096,
                "row_concurrency": 4,
            },
        },
        context={"execution_id": 42},
        jinja_env=Environment(),
        tool_executor=tool_executor,
        render_template=lambda template, ctx: template.replace("{{ __frame_max_rows }}", str(ctx["__frame_max_rows"])),
        render_dict=lambda data, ctx: data,
        worker_slot_id="slot-1",
    )
    elapsed = time.monotonic() - started

    assert result["status"] == "ok"
    assert result["processed"] == 4
    assert result["frame_count"] == 1
    assert sorted(seen_indexes) == [1, 2, 3, 4]
    assert result["frames"][0]["metrics"]["row_concurrency"] == 4
    assert result["frames"][0]["metrics"]["tasks"]["by_kind"]["noop"]["count"] == 4
    assert elapsed < 0.18


@pytest.mark.asyncio
async def test_cursor_worker_can_process_whole_frame_once(monkeypatch):
    from noetl.core.cursor_drivers import register_driver
    from noetl.worker import cursor_worker

    driver = _FakeBatchCursorDriver(
        [
            {"id": 1, "status": "pending"},
            {"id": 2, "status": "pending"},
            {"id": 3, "status": "pending"},
        ]
    )
    register_driver(driver.kind, driver)
    fake_store = _FakeStore()
    monkeypatch.setattr(cursor_worker, "default_store", fake_store)
    monkeypatch.setattr(cursor_worker, "_frame_ipc_cache", lambda: None)

    async def fetch_credential(auth_key):
        return {"dsn": "memory"}

    monkeypatch.setattr(cursor_worker, "fetch_credential_by_key_async", fetch_credential)

    seen_frames = []

    async def tool_executor(kind, cfg, ctx):
        seen_frames.append(
            {
                "frame_rows": list(ctx["frame"]["rows"]),
                "iter_rows": list(ctx["iter"]["item_rows"]),
                "iter_item": list(ctx["iter"]["item"]),
            }
        )
        return {"status": "ok"}

    result = await cursor_worker.execute_cursor_worker(
        config={
            "cursor": {
                "kind": driver.kind,
                "auth": "pg",
                "claim": "select next limit {{ __frame_max_rows }}",
                "options": {"max_iterations": 10},
            },
            "iterator": "item",
            "tasks": [{"name": "process_frame", "kind": "noop"}],
            "frame_policy": {
                "max_rows": 3,
                "max_seconds": 30,
                "max_bytes": 4096,
                "process": "frame",
            },
        },
        context={"execution_id": 42},
        jinja_env=Environment(),
        tool_executor=tool_executor,
        render_template=lambda template, ctx: template.replace("{{ __frame_max_rows }}", str(ctx["__frame_max_rows"])),
        render_dict=lambda data, ctx: data,
        worker_slot_id="slot-1",
    )

    assert result["status"] == "ok"
    assert result["processed"] == 3
    assert result["frame_count"] == 1
    assert len(seen_frames) == 1
    assert [row["id"] for row in seen_frames[0]["frame_rows"]] == [1, 2, 3]
    assert seen_frames[0]["iter_rows"] == seen_frames[0]["frame_rows"]
    assert seen_frames[0]["iter_item"] == seen_frames[0]["frame_rows"]
    assert result["frames"][0]["metrics"]["process"] == "frame"
    assert result["frames"][0]["metrics"]["rows"]["ok"] == 3
    assert result["frames"][0]["metrics"]["tasks"]["by_kind"]["noop"]["count"] == 1
