from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


class _MemoryProjectionStore:
    def __init__(self):
        self.records = {}

    async def save_projection(self, record):
        current = self.records.get(record.projection_id)
        if current and current.version > record.version:
            return False
        self.records[record.projection_id] = record
        return True

    async def load_projection(self, projection_id):
        return self.records.get(projection_id)

    async def save_snapshot(self, snapshot):  # pragma: no cover - protocol stub
        return True

    async def load_snapshot(self, aggregate_id, *, aggregate_type=None):  # pragma: no cover - protocol stub
        return None


class _SchemaLimitedProjectionStore(_MemoryProjectionStore):
    async def ensure_schema(self):
        from psycopg import errors as pg_errors

        raise pg_errors.InsufficientPrivilege("must be owner of table projection")


@pytest.mark.asyncio
async def test_replay_state_projector_writes_grouped_projection_records():
    from noetl.core.projector import ReplayStateProjector

    store = _MemoryProjectionStore()
    projector = ReplayStateProjector(store)

    written = await projector.project(
        [
            {
                "event_id": 10,
                "stream_version": 2,
                "tenant_id": "tenant-a",
                "organization_id": "org-a",
                "execution_id": 7,
                "event_type": "frame.committed",
                "aggregate_type": "frame",
                "aggregate_id": "frame/1",
                "result": {"status": "COMPLETED", "row_count": 2},
            },
            {
                "event_id": 9,
                "stream_version": 1,
                "tenant_id": "tenant-a",
                "organization_id": "org-a",
                "execution_id": 7,
                "event_type": "execution.started",
                "result": {"status": "RUNNING"},
            },
            {
                "event_id": 11,
                "stream_version": 1,
                "tenant_id": "tenant-b",
                "organization_id": "org-b",
                "execution_id": 8,
                "event_type": "execution.completed",
                "result": {"status": "COMPLETED"},
            },
        ]
    )

    assert len(written) == 2
    first = store.records["execution/7/all"]
    assert first.tenant_id == "tenant-a"
    assert first.organization_id == "org-a"
    assert first.version == 2
    assert first.source_event_id == 10
    assert first.state["frames"]["1"]["status"] == "COMPLETED"
    assert first.checksum == first.state["checksum"]
    assert first.meta["projector"] == "replay_state"
    assert first.meta["source_event_id"] == 10


@pytest.mark.asyncio
async def test_replay_state_projector_respects_version_monotonic_store_writes():
    from noetl.core.projector import ReplayStateProjector

    store = _MemoryProjectionStore()
    projector = ReplayStateProjector(store)

    newer = await projector.project(
        [
            {
                "event_id": 12,
                "stream_version": 3,
                "tenant_id": "tenant-a",
                "organization_id": "org-a",
                "execution_id": 7,
                "event_type": "workflow.completed",
                "result": {"status": "COMPLETED"},
            }
        ]
    )
    stale = await projector.project(
        [
            {
                "event_id": 9,
                "stream_version": 1,
                "tenant_id": "tenant-a",
                "organization_id": "org-a",
                "execution_id": 7,
                "event_type": "execution.started",
                "result": {"status": "RUNNING"},
            }
        ]
    )

    assert len(newer) == 1
    assert stale == []
    record = store.records["execution/7/all"]
    assert record.version == 3
    assert record.state["execution"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_replay_state_projector_records_lag_checkpoint_metadata():
    from noetl.core.projector import ReplayStateProjector

    now = datetime.now(timezone.utc)
    store = _MemoryProjectionStore()
    projector = ReplayStateProjector(store)

    written = await projector.project(
        [
            {
                "event_id": 31,
                "stream_version": 4,
                "tenant_id": "tenant-a",
                "organization_id": "org-a",
                "execution_id": 9,
                "event_type": "workflow.completed",
                "event_time": (now - timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
            },
            {
                "event_id": 30,
                "stream_version": 3,
                "tenant_id": "tenant-a",
                "organization_id": "org-a",
                "execution_id": 9,
                "event_type": "execution.started",
                "event_time": now - timedelta(seconds=5),
            },
        ]
    )

    assert len(written) == 1
    meta = store.records["execution/9/all"].meta
    assert meta["event_count"] == 2
    assert meta["source_event_id"] == 31
    assert meta["event_time_watermark"].endswith("Z")
    assert meta["projected_at"].endswith("Z")
    assert isinstance(meta["projection_lag_ms"], int)
    assert meta["projection_lag_ms"] >= 0


@pytest.mark.asyncio
async def test_nats_projector_worker_projects_owned_event_batch():
    from noetl.core.projector.metrics import ProjectorMetrics
    from noetl.core.projector.nats_worker import NATSProjectorWorker, ProjectorWorkerSettings

    metrics = ProjectorMetrics()
    store = _MemoryProjectionStore()
    worker = NATSProjectorWorker(
        projection_store=store,
        settings=ProjectorWorkerSettings(
            shard_id="noetl-projector-1",
            consumer_name="noetl-projector-1",
            shard_count=2,
        ),
        metrics=metrics,
    )

    action = await worker.handle_notification(
        {
            "events": [
                {
                    "event_id": 20,
                    "stream_version": 1,
                    "tenant_id": "tenant-a",
                    "organization_id": "org-a",
                    "execution_id": 7,
                    "event_type": "workflow.completed",
                },
                {
                    "event_id": 21,
                    "stream_version": 1,
                    "tenant_id": "tenant-a",
                    "organization_id": "org-a",
                    "execution_id": 8,
                    "event_type": "workflow.completed",
                },
            ]
        }
    )

    assert action == "ack"
    assert set(store.records) == {"execution/7/all"}
    assert store.records["execution/7/all"].state["execution"]["status"] == "COMPLETED"
    snapshot = metrics.snapshot()
    assert snapshot["notifications_total"] == 1
    assert snapshot["events_extracted_total"] == 2
    assert snapshot["events_owned_total"] == 1
    assert snapshot["projection_records_total"] == 1


@pytest.mark.asyncio
async def test_nats_projector_worker_acks_empty_or_unowned_notifications():
    from noetl.core.projector.metrics import ProjectorMetrics
    from noetl.core.projector.nats_worker import NATSProjectorWorker, ProjectorWorkerSettings

    metrics = ProjectorMetrics()
    store = _MemoryProjectionStore()
    worker = NATSProjectorWorker(
        projection_store=store,
        settings=ProjectorWorkerSettings(
            shard_id="noetl-projector-0",
            consumer_name="noetl-projector-0",
            shard_count=2,
        ),
        metrics=metrics,
    )

    assert await worker.handle_notification({"event": {"execution_id": 7, "event_type": "workflow.completed"}}) == "ack"
    assert await worker.handle_notification({"event_id": 99}) == "ack"
    assert store.records == {}
    snapshot = metrics.snapshot()
    assert snapshot["notifications_total"] == 2
    assert snapshot["empty_or_unowned_notifications_total"] == 2


@pytest.mark.asyncio
async def test_nats_projector_worker_tolerates_projection_schema_permission(monkeypatch):
    from noetl.core.projector.nats_worker import NATSProjectorWorker, ProjectorWorkerSettings

    calls = []

    class FakeSubscriber:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs["consumer_name"]))

        async def connect(self):
            calls.append(("connect", None))

        async def subscribe(self, handler):
            calls.append(("subscribe", handler.__name__))

    monkeypatch.setattr("noetl.core.projector.nats_worker.NATSCommandSubscriber", FakeSubscriber)
    worker = NATSProjectorWorker(
        projection_store=_SchemaLimitedProjectionStore(),
        settings=ProjectorWorkerSettings(consumer_name="noetl-projector-0"),
    )

    await worker.start()

    assert calls == [
        ("init", "noetl-projector-0"),
        ("connect", None),
        ("subscribe", "handle_notification"),
    ]


@pytest.mark.asyncio
async def test_run_projector_worker_initializes_and_closes_db_pool(monkeypatch):
    import noetl.core.projector.nats_worker as module

    calls = []

    async def fake_init_pool(conninfo):
        calls.append(("init", conninfo))

    async def fake_close_pool():
        calls.append(("close", None))

    class FakeWorker:
        def __init__(self, *, settings):
            self.settings = settings
            from noetl.core.projector.metrics import ProjectorMetrics

            self.metrics = ProjectorMetrics()

        async def start(self):
            calls.append(("start", self.settings.shard_id))
            raise RuntimeError("stop projector test")

        async def close(self):
            calls.append(("worker_close", None))

    monkeypatch.setattr(module, "get_pgdb_connection", lambda: "dbname=noetl")
    monkeypatch.setattr(module, "init_pool", fake_init_pool)
    monkeypatch.setattr(module, "close_pool", fake_close_pool)
    monkeypatch.setattr(module, "NATSProjectorWorker", FakeWorker)

    with pytest.raises(RuntimeError, match="stop projector test"):
        await module.run_projector_worker(
            module.ProjectorWorkerSettings(shard_id="noetl-projector-0")
        )

    assert calls == [
        ("init", "dbname=noetl"),
        ("start", "noetl-projector-0"),
        ("worker_close", None),
        ("close", None),
    ]
