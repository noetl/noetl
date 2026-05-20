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


class _FailingProjectionStore(_MemoryProjectionStore):
    async def save_projection(self, record):
        raise RuntimeError("projection write failed")


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
    assert set(first.state["projection_checksums"]) == {
        "execution",
        "stages",
        "frames",
        "commands",
        "business_objects",
        "loops",
    }
    assert first.checksum == first.state["checksum"]
    assert first.meta["projector"] == "replay_state"
    assert first.meta["projection_checksums"] == first.state["projection_checksums"]
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
    assert snapshot["events_unowned_total"] == 1
    assert snapshot["events_unshardable_total"] == 0
    assert snapshot["projection_records_total"] == 1
    assert snapshot["projection_stale_records_total"] == 0
    assert snapshot["last_projection_source_event_id"] == 20


@pytest.mark.asyncio
async def test_nats_projector_worker_counts_stale_projection_writes():
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

    assert (
        await worker.handle_notification(
            {
                "event": {
                    "event_id": 30,
                    "stream_version": 3,
                    "tenant_id": "tenant-a",
                    "organization_id": "org-a",
                    "execution_id": 7,
                    "event_type": "workflow.completed",
                }
            }
        )
        == "ack"
    )
    assert (
        await worker.handle_notification(
            {
                "event": {
                    "event_id": 20,
                    "stream_version": 1,
                    "tenant_id": "tenant-a",
                    "organization_id": "org-a",
                    "execution_id": 7,
                    "event_type": "execution.started",
                }
            }
        )
        == "ack"
    )

    snapshot = metrics.snapshot()
    assert snapshot["notifications_total"] == 2
    assert snapshot["events_owned_total"] == 2
    assert snapshot["projection_records_total"] == 1
    assert snapshot["projection_stale_records_total"] == 1
    assert store.records["execution/7/all"].version == 3


@pytest.mark.asyncio
async def test_nats_projector_worker_counts_projection_errors():
    from noetl.core.projector.metrics import ProjectorMetrics
    from noetl.core.projector.nats_worker import NATSProjectorWorker, ProjectorWorkerSettings

    metrics = ProjectorMetrics()
    worker = NATSProjectorWorker(
        projection_store=_FailingProjectionStore(),
        settings=ProjectorWorkerSettings(shard_count=1),
        metrics=metrics,
    )

    with pytest.raises(RuntimeError, match="projection write failed"):
        await worker.handle_notification(
            {
                "event": {
                    "event_id": 40,
                    "stream_version": 1,
                    "tenant_id": "tenant-a",
                    "organization_id": "org-a",
                    "execution_id": 7,
                    "event_type": "workflow.completed",
                }
            }
        )

    snapshot = metrics.snapshot()
    assert snapshot["errors_total"] == 1
    assert snapshot["projection_errors_total"] == 1
    assert snapshot["decode_errors_total"] == 0


@pytest.mark.asyncio
async def test_nats_projector_worker_does_not_count_same_execution_batch_as_stale():
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

    assert (
        await worker.handle_notification(
            {
                "events": [
                    {
                        "event_id": 20,
                        "stream_version": 1,
                        "tenant_id": "tenant-a",
                        "organization_id": "org-a",
                        "execution_id": 7,
                        "event_type": "execution.started",
                    },
                    {
                        "event_id": 21,
                        "stream_version": 2,
                        "tenant_id": "tenant-a",
                        "organization_id": "org-a",
                        "execution_id": 7,
                        "event_type": "workflow.completed",
                    },
                ]
            }
        )
        == "ack"
    )

    snapshot = metrics.snapshot()
    assert snapshot["events_owned_total"] == 2
    assert snapshot["projection_records_total"] == 1
    assert snapshot["projection_stale_records_total"] == 0


def test_projector_notification_decoder_accepts_json_and_arrow_feather():
    from noetl.core.projector.nats_worker import decode_projector_notification
    from noetl.core.storage.arrow_ipc import rows_to_arrow_feather

    json_payload = b'{"event_id": 20, "execution_id": 7, "event_type": "workflow.completed"}'
    assert decode_projector_notification(json_payload)["event_id"] == 20

    arrow_payload, _schema_digest, row_count = rows_to_arrow_feather(
        [
            {
                "event_id": 21,
                "execution_id": 7,
                "event_type": "frame.committed",
                "status": "COMPLETED",
            }
        ]
    )

    assert row_count == 1
    decoded = decode_projector_notification(arrow_payload)
    assert decoded["event_id"] == 21
    assert decoded["event_type"] == "frame.committed"


def test_projector_notification_decoder_wraps_arrow_batches():
    from noetl.core.projector.nats_worker import decode_projector_notification
    from noetl.core.storage.arrow_ipc import rows_to_arrow_feather

    arrow_payload, _schema_digest, row_count = rows_to_arrow_feather(
        [
            {"event_id": 21, "execution_id": 7, "event_type": "frame.dispatched"},
            {"event_id": 22, "execution_id": 7, "event_type": "frame.committed"},
        ]
    )

    assert row_count == 2
    decoded = decode_projector_notification(arrow_payload)
    assert [event["event_id"] for event in decoded["events"]] == [21, 22]


def test_nats_projector_worker_records_decode_errors():
    from noetl.core.projector.metrics import ProjectorMetrics
    from noetl.core.projector.nats_worker import NATSProjectorWorker, ProjectorWorkerSettings

    metrics = ProjectorMetrics()
    worker = NATSProjectorWorker(
        projection_store=_MemoryProjectionStore(),
        settings=ProjectorWorkerSettings(),
        metrics=metrics,
    )

    with pytest.raises(Exception):
        worker._decode_notification(b"not-json-or-arrow")

    snapshot = metrics.snapshot()
    assert snapshot["errors_total"] == 1
    assert snapshot["decode_errors_total"] == 1
    assert snapshot["projection_errors_total"] == 0
    assert snapshot["last_error_unixtime"] > 0


def test_projector_worker_settings_rejects_out_of_range_shard_id():
    from noetl.core.projector.nats_worker import ProjectorWorkerSettings

    with pytest.raises(ValueError, match="shard index must be less than shard_count"):
        ProjectorWorkerSettings(shard_id="noetl-projector-2", shard_count=2)


def test_projector_worker_settings_rejects_invalid_runtime_limits():
    from noetl.core.projector.nats_worker import ProjectorWorkerSettings

    with pytest.raises(ValueError, match="shard_count"):
        ProjectorWorkerSettings(shard_count=0)
    with pytest.raises(ValueError, match="max_inflight"):
        ProjectorWorkerSettings(max_inflight=0)
    with pytest.raises(ValueError, match="max_ack_pending"):
        ProjectorWorkerSettings(max_ack_pending=0)
    with pytest.raises(ValueError, match="fetch_timeout_seconds"):
        ProjectorWorkerSettings(fetch_timeout_seconds=0)
    with pytest.raises(ValueError, match="fetch_heartbeat_seconds"):
        ProjectorWorkerSettings(fetch_heartbeat_seconds=0)
    with pytest.raises(ValueError, match="metrics_port"):
        ProjectorWorkerSettings(metrics_port=0)


@pytest.mark.parametrize(
    ("env_name", "env_value", "error_match"),
    [
        ("NOETL_PROJECTOR_SHARD_COUNT", "0", "shard_count"),
        ("NOETL_PROJECTOR_MAX_INFLIGHT", "0", "max_inflight"),
        ("NOETL_PROJECTOR_NATS_MAX_ACK_PENDING", "0", "max_ack_pending"),
        ("NOETL_PROJECTOR_NATS_FETCH_TIMEOUT_SECONDS", "0", "fetch_timeout_seconds"),
        ("NOETL_PROJECTOR_NATS_FETCH_HEARTBEAT_SECONDS", "0", "fetch_heartbeat_seconds"),
        ("NOETL_PROJECTOR_METRICS_PORT", "0", "metrics_port"),
    ],
)
def test_load_projector_worker_settings_rejects_invalid_env_values(monkeypatch, env_name, env_value, error_match):
    from noetl.core.projector.nats_worker import load_projector_worker_settings

    monkeypatch.setenv(env_name, env_value)

    with pytest.raises(ValueError, match=error_match):
        load_projector_worker_settings()


def test_load_projector_worker_settings_rejects_env_shard_id_outside_count(monkeypatch):
    from noetl.core.projector.nats_worker import load_projector_worker_settings

    monkeypatch.setenv("NOETL_PROJECTOR_SHARD_ID", "noetl-projector-2")
    monkeypatch.setenv("NOETL_PROJECTOR_SHARD_COUNT", "2")

    with pytest.raises(ValueError, match="shard index must be less than shard_count"):
        load_projector_worker_settings()


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
    assert snapshot["events_unowned_total"] == 1
    assert snapshot["events_unshardable_total"] == 0


@pytest.mark.asyncio
async def test_nats_projector_worker_counts_unshardable_events():
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

    assert await worker.handle_notification({"event": {"event_type": "workflow.completed"}}) == "ack"
    assert store.records == {}
    snapshot = metrics.snapshot()
    assert snapshot["notifications_total"] == 1
    assert snapshot["events_extracted_total"] == 1
    assert snapshot["events_unowned_total"] == 0
    assert snapshot["events_unshardable_total"] == 1

    assert (
        await worker.handle_notification(
            {"event": {"execution_id": "not-an-int", "event_type": "workflow.completed"}}
        )
        == "ack"
    )
    snapshot = metrics.snapshot()
    assert snapshot["notifications_total"] == 2
    assert snapshot["events_extracted_total"] == 2
    assert snapshot["events_unshardable_total"] == 2


@pytest.mark.asyncio
async def test_nats_projector_worker_tolerates_projection_schema_permission(monkeypatch):
    from noetl.core.projector.nats_worker import NATSProjectorWorker, ProjectorWorkerSettings

    calls = []

    class FakeSubscriber:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs["consumer_name"]))
            assert callable(kwargs["message_decoder"])
            assert callable(kwargs["message_action_observer"])

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

    def fake_metrics_server(_metrics, *, host, port, labels):
        calls.append(("metrics", host, port, labels))

        class FakeMetricsServer:
            def shutdown(self):
                calls.append(("metrics_shutdown", None))

            def server_close(self):
                calls.append(("metrics_close", None))

        return FakeMetricsServer()

    monkeypatch.setattr(module, "start_projector_metrics_server", fake_metrics_server)

    with pytest.raises(RuntimeError, match="stop projector test"):
        await module.run_projector_worker(
            module.ProjectorWorkerSettings(
                shard_id="noetl-projector-1",
                consumer_name="consumer-a",
                shard_count=2,
                stream_name="NOETL_EVENTS",
                subject="noetl.events.>",
                metrics_host="127.0.0.1",
                metrics_port=9090,
            )
        )

    assert calls == [
        ("init", "dbname=noetl"),
        (
            "metrics",
            "127.0.0.1",
            9090,
            {
                "shard_id": "noetl-projector-1",
                "shard_index": "1",
                "shard_count": "2",
                "consumer": "consumer-a",
                "stream": "NOETL_EVENTS",
                "subject": "noetl.events.>",
            },
        ),
        ("start", "noetl-projector-1"),
        ("metrics_shutdown", None),
        ("metrics_close", None),
        ("worker_close", None),
        ("close", None),
    ]
