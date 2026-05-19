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
async def test_publish_outbox_batch_uses_preencoded_bytes_when_subject_exists(monkeypatch):
    import noetl.core.outbox as outbox

    claim_rows = [
        {
            "outbox_id": 1,
            "event_id": 101,
            "execution_id": 7,
            "subject": "noetl.events.default.default.7.0",
            "payload": {"event_id": 101},
            "payload_bytes": b"ARROW1...",
            "attempts": 1,
        }
    ]
    sent = []
    marked = []

    class Publisher:
        async def ensure_connected(self):
            sent.append(("connected", None))

        async def _publish_event_payload(self, subject, payload):
            sent.append((subject, payload))

        async def publish_event(self, event):  # pragma: no cover - fallback must not run
            raise AssertionError(f"unexpected fallback publish: {event}")

    async def fake_claim(*, limit):
        return claim_rows

    async def fake_mark(outbox_id):
        marked.append(outbox_id)

    monkeypatch.setattr(outbox, "claim_outbox_batch", fake_claim)
    monkeypatch.setattr(outbox, "mark_outbox_published", fake_mark)

    count = await outbox.publish_outbox_batch(limit=10, publisher=Publisher())

    assert count == 1
    assert sent == [
        ("connected", None),
        ("noetl.events.default.default.7.0", b"ARROW1..."),
    ]
    assert marked == [1]


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
