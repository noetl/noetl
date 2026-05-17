from __future__ import annotations

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
