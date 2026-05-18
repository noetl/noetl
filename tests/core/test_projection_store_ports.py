from datetime import datetime, timezone

import pytest


def test_projection_checksum_is_deterministic():
    from noetl.core.projection_store import ProjectionRecord

    record = ProjectionRecord(
        projection_id="execution/1",
        projection_type="execution",
        version=7,
        state={
            "updated_at": datetime(2026, 5, 16, tzinfo=timezone.utc),
            "status": "COMPLETED",
        },
    )

    assert record.resolved_checksum() == record.resolved_checksum()
    assert len(record.resolved_checksum()) == 64


@pytest.mark.asyncio
async def test_postgres_projection_store_save_projection_reports_stale_noop(monkeypatch):
    from noetl.core.projection_store import PostgresProjectionStore, ProjectionRecord
    import noetl.core.projection_store.postgres as postgres_module

    class Cursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, params=None):  # noqa: ARG002
            self.query = query

        async def fetchone(self):
            return None

    class Conn:
        def cursor(self, row_factory=None):  # noqa: ARG002
            return Cursor()

        async def commit(self):
            self.committed = True

    class Ctx:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(postgres_module, "get_pool_connection", lambda: Ctx())

    changed = await PostgresProjectionStore().save_projection(
        ProjectionRecord(
            projection_id="execution/1",
            projection_type="execution",
            version=1,
            state={"status": "RUNNING"},
        )
    )

    assert changed is False
