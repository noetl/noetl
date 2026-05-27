from datetime import datetime, timezone

import pytest


class _Cursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    async def execute(self, query, params=None):
        self.executed.append((query, params))

    async def fetchall(self):
        return self.rows


class _CursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self, **_kwargs):
        return _CursorCtx(self._cursor)

    async def commit(self):
        self.commits += 1


class _ConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_normalize_outbox_payload_serializes_datetimes():
    from noetl.core.outbox import normalize_outbox_payload

    payload = normalize_outbox_payload(
        {
            "event_id": 1,
            "execution_id": 7,
            "event_time": datetime(2026, 5, 18, 20, 0, tzinfo=timezone.utc),
        }
    )

    assert payload["event_time"] == "2026-05-18 20:00:00+00:00"


@pytest.mark.asyncio
async def test_enqueue_outbox_uses_caller_transaction_cursor():
    from psycopg.types.json import Json

    from noetl.core.outbox import enqueue_outbox

    cursor = _Cursor()

    await enqueue_outbox(
        cursor,
        {
            "event_id": 101,
            "execution_id": 7,
            "event_type": "workflow.completed",
        },
        subject="noetl.events.default.default.7.0",
    )

    query, params = cursor.executed[0]
    assert "INSERT INTO noetl.outbox" in query
    assert params[:3] == (7, 101, "noetl.events.default.default.7.0")
    assert isinstance(params[3], Json)
    assert bytes(params[4]).startswith(b"ARROW1")


@pytest.mark.asyncio
async def test_publish_outbox_batch_publishes_and_marks(monkeypatch):
    import noetl.core.outbox as outbox

    claim_rows = [
        {
            "outbox_id": 1,
            "event_id": 101,
            "execution_id": 7,
            "payload": {"event_id": 101, "execution_id": 7, "event_type": "workflow.completed"},
            "attempts": 1,
        }
    ]
    published = []
    marked = []

    class Publisher:
        async def publish_event(self, event):
            published.append(event)

    async def fake_claim(*, limit):
        assert limit == 10
        return claim_rows

    async def fake_mark(outbox_id):
        marked.append(outbox_id)

    monkeypatch.setattr(outbox, "claim_outbox_batch", fake_claim)
    monkeypatch.setattr(outbox, "mark_outbox_published", fake_mark)

    count = await outbox.publish_outbox_batch(limit=10, publisher=Publisher())

    assert count == 1
    assert published == [claim_rows[0]["payload"]]
    assert marked == [1]


@pytest.mark.asyncio
async def test_publish_outbox_batch_publishes_json_even_when_payload_bytes_present(monkeypatch):
    """Regression test: outbox rows that carry both ``payload`` (JSONB) and
    ``payload_bytes`` (arrow-feather) must be published over NATS as JSON, not
    as raw arrow-feather bytes.

    The gateway (``src/playbook_state.rs``) uses ``serde_json::from_slice`` to
    parse NATS payloads.  Publishing arrow-feather bytes caused 438 parse failures
    in production and zero ``playbook/state`` SSE frames reaching the SPA.

    Fix: ``publish_outbox_batch`` always calls ``publish_event(payload)`` which
    JSON-encodes the JSONB column.  The arrow-feather bytes remain in the DB for
    direct-table readers; they are never sent over NATS.
    """
    import json

    import noetl.core.outbox as outbox

    event_payload = {"event_id": 101, "execution_id": 7, "event_type": "playbook.completed"}
    claim_rows = [
        {
            "outbox_id": 1,
            "event_id": 101,
            "execution_id": 7,
            "subject": "noetl.events.default.default.7.0",
            "payload": event_payload,
            "payload_bytes": b"ARROW1...",  # arrow-feather bytes must NOT go to NATS
            "attempts": 1,
        }
    ]
    published = []
    marked = []

    class Publisher:
        async def _publish_event_payload(self, subject, payload):  # pragma: no cover
            raise AssertionError(
                "arrow-feather path must not be used for NATS publish; "
                f"received subject={subject!r} payload_prefix={payload[:8]!r}"
            )

        async def publish_event(self, event):
            published.append(event)

    async def fake_claim(*, limit):
        return claim_rows

    async def fake_mark(outbox_id):
        marked.append(outbox_id)

    monkeypatch.setattr(outbox, "claim_outbox_batch", fake_claim)
    monkeypatch.setattr(outbox, "mark_outbox_published", fake_mark)

    count = await outbox.publish_outbox_batch(limit=10, publisher=Publisher())

    assert count == 1
    assert marked == [1]

    # Verify the published payload round-trips through JSON (it is JSON-serialisable).
    assert len(published) == 1
    assert json.dumps(published[0])  # must not raise
    assert published[0].get("event_type") == "playbook.completed"


@pytest.mark.asyncio
async def test_claim_outbox_batch_marks_rows_in_flight(monkeypatch):
    import noetl.core.outbox as outbox

    cursor = _Cursor(rows=[{"outbox_id": 1, "event_id": 101, "payload": {"event_id": 101}}])
    conn = _Conn(cursor)

    monkeypatch.setattr(outbox, "get_pool_connection", lambda: _ConnCtx(conn))

    rows = await outbox.claim_outbox_batch(limit=5)

    assert rows == [{"outbox_id": 1, "event_id": 101, "payload": {"event_id": 101}}]
    assert conn.commits == 1
    assert "FOR UPDATE SKIP LOCKED" in cursor.executed[0][0]
