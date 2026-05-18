import pytest


class _FakeCursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []
        self.executemany_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, query, params=None):
        self.executed.append((query, params))

    async def executemany(self, query, params):
        self.executemany_calls.append((query, params))

    async def fetchone(self):
        if self.rows:
            return self.rows.pop(0)
        return None


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def cursor(self, **_kwargs):
        return self._cursor

    async def commit(self):
        self.commit_count += 1


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


@pytest.mark.asyncio
async def test_batch_status_event_is_mirrored_after_commit(monkeypatch):
    from noetl.server.api.core import batch

    mirrored = []
    cursor = _FakeCursor()
    conn = _FakeConnection(cursor)

    async def fake_next_snowflake_id(_cur):
        return 101

    async def fake_mirror(events):
        mirrored.extend(events)

    monkeypatch.setattr(batch, "get_pool_connection", lambda: conn)
    monkeypatch.setattr(batch, "_next_snowflake_id", fake_next_snowflake_id)
    monkeypatch.setattr(batch, "_mirror_batch_events", fake_mirror)

    await batch._persist_batch_status_event(
        execution_id=7,
        catalog_id=5,
        request_id="req-1",
        worker_id="worker-1",
        idempotency_key="idem-1",
        event_type="batch.completed",
        status="COMPLETED",
        payload={"request_id": "req-1", "commands_generated": 2},
    )

    assert conn.commit_count == 1
    assert mirrored[0]["event_id"] == 101
    assert mirrored[0]["event_type"] == "batch.completed"
    assert mirrored[0]["node_name"] == "events.batch"
    assert mirrored[0]["meta"]["batch_request_id"] == "req-1"


@pytest.mark.asyncio
async def test_batch_acceptance_mirrors_item_and_acceptance_events(monkeypatch):
    from noetl.server.api.core import batch
    from noetl.server.api.core.models import BatchEventRequest

    mirrored = []
    cursor = _FakeCursor(rows=[{"catalog_id": 5}, None])
    conn = _FakeConnection(cursor)
    snowflakes = iter([1000, 1001, 1002])

    async def fake_next_snowflake_id(_cur):
        return next(snowflakes)

    async def fake_mirror(events):
        mirrored.extend(events)

    monkeypatch.setattr(batch, "get_pool_connection", lambda: conn)
    monkeypatch.setattr(batch, "_next_snowflake_id", fake_next_snowflake_id)
    monkeypatch.setattr(batch, "_mirror_batch_events", fake_mirror)

    result = await batch._persist_batch_acceptance(
        BatchEventRequest(
            execution_id="7",
            worker_id="worker-1",
            events=[
                {
                    "step": "fetch_mds",
                    "name": "command.completed",
                    "payload": {"result": {"reference": {"uri": "s3://bucket/key"}}, "command_id": 900},
                    "meta": {"stage_id": "stage-1", "frame_id": "frame-1"},
                    "actionable": False,
                    "informative": True,
                }
            ],
        ),
        idempotency_key="idem-1",
    )

    assert conn.commit_count == 1
    assert result.duplicate is False
    assert [event["event_type"] for event in mirrored] == ["command.completed", "batch.accepted"]
    assert mirrored[0]["command_id"] == 900
    assert mirrored[0]["stage_id"] == "stage-1"
    assert mirrored[0]["frame_id"] == "frame-1"
    assert mirrored[1]["node_name"] == "events.batch"


@pytest.mark.asyncio
async def test_batch_mirror_envelopes_feed_replay_state_projector(monkeypatch):
    from noetl.core.projector.nats_worker import NATSProjectorWorker, ProjectorWorkerSettings
    from noetl.server.api.core import batch
    from noetl.server.api.core.models import BatchEventRequest

    mirrored = []
    cursor = _FakeCursor(rows=[{"catalog_id": 5}, None])
    conn = _FakeConnection(cursor)
    snowflakes = iter([2000, 2001, 2002])

    async def fake_next_snowflake_id(_cur):
        return next(snowflakes)

    async def fake_mirror(events):
        mirrored.extend(events)

    monkeypatch.setattr(batch, "get_pool_connection", lambda: conn)
    monkeypatch.setattr(batch, "_next_snowflake_id", fake_next_snowflake_id)
    monkeypatch.setattr(batch, "_mirror_batch_events", fake_mirror)

    await batch._persist_batch_acceptance(
        BatchEventRequest(
            execution_id="7",
            worker_id="worker-1",
            events=[
                {
                    "step": "fetch_mds",
                    "name": "command.completed",
                    "payload": {"result": {"reference": {"uri": "s3://bucket/mds"}}, "command_id": 900},
                    "meta": {
                        "stage_id": "stage-1",
                        "frame_id": "frame-1",
                        "loop_event_id": "loop-1",
                    },
                    "actionable": False,
                    "informative": True,
                }
            ],
        ),
        idempotency_key="idem-1",
    )

    store = _MemoryProjectionStore()
    worker = NATSProjectorWorker(
        projection_store=store,
        settings=ProjectorWorkerSettings(shard_count=1),
    )

    assert await worker.handle_notification({"events": mirrored}) == "ack"

    record = store.records["execution/7/all"]
    assert record.source_event_id == 2002
    assert record.state["frames"]["frame-1"]["status"] == "COMPLETED"
    assert record.state["frames"]["frame-1"]["command_id"] == "900"
    assert record.state["frames"]["frame-1"]["stage_id"] == "stage-1"
    assert record.state["loops"]["loop-1"]["done"] == 1
