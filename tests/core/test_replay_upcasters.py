import pytest


def test_upcaster_registry_applies_sequential_versions():
    from noetl.core.replay import EventUpcasterRegistry

    registry = EventUpcasterRegistry()

    registry.register(
        "noetl.event",
        1,
        lambda event: {
            **event,
            "schema_version": 2,
            "meta": {**event.get("meta", {}), "v2": True},
        },
    )
    registry.register(
        "noetl.event",
        2,
        lambda event: {
            **event,
            "schema_version": 3,
            "meta": {**event.get("meta", {}), "v3": True},
        },
    )

    event = registry.upcast_event(
        {"event_id": 10, "schema_name": "noetl.event", "schema_version": 1, "meta": {}}
    )

    assert event["schema_version"] == 3
    assert event["meta"] == {"v2": True, "v3": True}


def test_upcaster_registry_rejects_non_advancing_upcaster():
    from noetl.core.replay import EventUpcasterRegistry

    registry = EventUpcasterRegistry()
    registry.register("noetl.event", 1, lambda event: event)

    with pytest.raises(ValueError, match="did not advance"):
        registry.upcast_event({"schema_name": "noetl.event", "schema_version": 1})


def test_upcaster_registry_defaults_legacy_schema_fields():
    from noetl.core.replay import EventUpcasterRegistry

    event = EventUpcasterRegistry().upcast_event({"event_id": 1})

    assert event["schema_name"] == "noetl.event"
    assert event["schema_version"] == 1


def test_upcaster_registry_digest_is_stable_for_registered_transitions():
    from noetl.core.replay import EventUpcasterRegistry

    def _advance(event):
        return {**event, "schema_version": int(event["schema_version"]) + 1}

    left = EventUpcasterRegistry()
    left.register("noetl.frame.committed", 2, _advance)
    left.register("noetl.event", 1, _advance)

    right = EventUpcasterRegistry()
    right.register("noetl.event", 1, _advance)
    right.register("noetl.frame.committed", 2, _advance)

    assert left.digest() == right.digest()
    assert len(left.digest()) == 64
