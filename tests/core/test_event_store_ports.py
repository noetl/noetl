from datetime import datetime, timezone

import pytest


def test_event_record_envelope_checksum_is_deterministic():
    from noetl.core.event_store import EventRecord

    record = EventRecord(
        event_type="frame.committed",
        stream_id="execution/1/stage/2",
        execution_id=1,
        aggregate_id="frame/3",
        aggregate_type="frame",
        payload_ref={"uri": "noetl://payloads/sha256/abc", "sha256": "abc"},
        result={"status": "COMPLETED"},
        meta={"row_count": 10},
        event_time=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )

    first = record.envelope(stream_version=7, event_id=100)
    second = record.envelope(stream_version=7, event_id=200)

    assert first["schema_name"] == "noetl.frame.committed"
    assert first["stream_version"] == 7
    assert first["envelope_checksum"] == second["envelope_checksum"]
    assert len(first["envelope_checksum"]) == 64


def test_expected_version_conflict_message_is_actionable():
    from noetl.core.event_store import ExpectedVersionConflict

    error = ExpectedVersionConflict(
        stream_id="execution/1",
        expected_version=2,
        actual_version=3,
    )

    assert "execution/1" in str(error)
    assert "expected version 2" in str(error)
    assert error.actual_version == 3


@pytest.mark.asyncio
async def test_postgres_event_store_append_rejects_expected_version_conflict(monkeypatch):
    from noetl.core.event_store import EventRecord, ExpectedVersionConflict, PostgresEventStore
    import noetl.core.event_store.postgres as postgres_module

    class Cursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, params=None):  # noqa: ARG002
            self.query = query

        async def fetchone(self):
            if "max(stream_version)" in self.query:
                return {"version": 3}
            return {"snowflake_id": 99}

    class Conn:
        def cursor(self, row_factory=None):  # noqa: ARG002
            return Cursor()

        async def commit(self):
            raise AssertionError("commit should not run after version conflict")

    class Ctx:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(postgres_module, "get_pool_connection", lambda: Ctx())

    store = PostgresEventStore()
    with pytest.raises(ExpectedVersionConflict):
        await store.append(
            "execution/1",
            [EventRecord(event_type="test.event", stream_id="execution/1")],
            expected_version=2,
        )
