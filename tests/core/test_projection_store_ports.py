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


@pytest.mark.asyncio
async def test_postgres_projection_store_query_projections_filters_and_limits(monkeypatch):
    from noetl.core.projection_store import PostgresProjectionStore, ProjectionQuery
    import noetl.core.projection_store.postgres as postgres_module

    class Cursor:
        def __init__(self):
            self.query = ""
            self.params = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, params=None):
            self.query = query
            self.params = list(params or [])

        async def fetchall(self):
            return [
                {
                    "projection_id": "execution/7/all",
                    "projection_type": "replay_state:all",
                    "tenant_id": "tenant-a",
                    "organization_id": "org-a",
                    "execution_id": 7,
                    "version": 12,
                    "source_event_id": 99,
                    "state": {"status": "COMPLETED"},
                    "checksum": "abc",
                    "meta": {"projector": "replay_state"},
                }
            ]

    class Conn:
        def __init__(self, cursor):
            self._cursor = cursor

        def cursor(self, row_factory=None):  # noqa: ARG002
            return self._cursor

    class Ctx:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    cursor = Cursor()
    monkeypatch.setattr(postgres_module, "get_pool_connection", lambda: Ctx(Conn(cursor)))

    records = await PostgresProjectionStore().query_projections(
        ProjectionQuery(
            tenant_id="tenant-a",
            organization_id="org-a",
            projection_type="replay_state:all",
            execution_id=7,
            limit=25,
        )
    )

    assert [record.projection_id for record in records] == ["execution/7/all"]
    assert "FROM noetl.projection" in cursor.query
    assert "tenant_id = %s" in cursor.query
    assert "organization_id = %s" in cursor.query
    assert "projection_type = %s" in cursor.query
    assert "execution_id = %s" in cursor.query
    assert cursor.params == ["tenant-a", "org-a", "replay_state:all", 7, 25]
