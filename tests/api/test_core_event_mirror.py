import pytest


@pytest.mark.asyncio
async def test_core_event_mirror_is_opt_in(monkeypatch):
    from noetl.server.api.core import events

    published = []

    class FakePublisher:
        async def publish_event(self, event):
            published.append(event)

    monkeypatch.setenv("NOETL_EVENT_MIRROR_ENABLED", "false")
    monkeypatch.setattr(events, "_event_mirror_publisher", FakePublisher())

    await events._mirror_events([{"event_id": 1, "event_type": "workflow.completed"}])

    assert published == []


@pytest.mark.asyncio
async def test_core_event_mirror_publishes_when_enabled(monkeypatch):
    from noetl.server.api.core import events

    published = []

    class FakePublisher:
        async def publish_event(self, event):
            published.append(event)

    monkeypatch.setenv("NOETL_EVENT_MIRROR_ENABLED", "true")
    monkeypatch.setattr(events, "_event_mirror_publisher", FakePublisher())

    await events._mirror_events([{"event_id": 1, "event_type": "workflow.completed"}])

    assert published == [{"event_id": 1, "event_type": "workflow.completed"}]


@pytest.mark.asyncio
async def test_core_event_outbox_enqueue_is_opt_in(monkeypatch):
    from noetl.server.api.core import events

    enqueued = []

    async def fake_enqueue(cur, event, *, subject=None):
        enqueued.append((cur, event, subject))

    monkeypatch.setenv("NOETL_EVENT_MIRROR_ENABLED", "false")
    monkeypatch.setattr(events, "enqueue_outbox", fake_enqueue)

    await events._enqueue_event_outbox("cursor", {"event_id": 1, "execution_id": 7})

    assert enqueued == []


@pytest.mark.asyncio
async def test_core_event_outbox_enqueue_uses_event_subject(monkeypatch):
    from noetl.server.api.core import events

    enqueued = []

    class FakeSubjectPublisher:
        def subject_for_event(self, event):
            return f"events.{event['execution_id']}"

    async def fake_enqueue(cur, event, *, subject=None):
        enqueued.append((cur, event, subject))

    monkeypatch.setenv("NOETL_EVENT_MIRROR_ENABLED", "true")
    monkeypatch.setattr(events, "_event_subject_publisher", FakeSubjectPublisher())
    monkeypatch.setattr(events, "enqueue_outbox", fake_enqueue)

    event = {"event_id": 1, "execution_id": 7}
    await events._enqueue_event_outbox("cursor", event)

    assert enqueued == [("cursor", event, "events.7")]


def test_core_event_mirror_envelope_preserves_lineage():
    from noetl.server.api.core import events

    envelope = events._command_issued_envelope(
        event_id=11,
        execution_id=7,
        catalog_id=5,
        command_id=13,
        step="fetch",
        tool_kind="http",
        context={"x": 1},
        meta={"stage_id": 17, "frame_id": 19},
        parent_event_id=3,
        parent_execution_id=None,
        stage_id=17,
        frame_id=19,
        created_at=None,
    )

    assert envelope["event_type"] == "command.issued"
    assert envelope["command_id"] == 13
    assert envelope["stage_id"] == 17
    assert envelope["frame_id"] == 19
    assert envelope["parent_event_id"] == 3
    assert envelope["context"] == {"x": 1}
