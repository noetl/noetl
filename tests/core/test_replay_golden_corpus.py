import json
from pathlib import Path


def test_golden_replay_corpus_checksum_is_stable():
    from noetl.core.replay import default_upcaster_registry
    from noetl.server.api.replay import fold_replay_state

    events = json.loads(
        Path("tests/fixtures/replay/golden_execution_events.json").read_text()
    )

    state = fold_replay_state(
        default_upcaster_registry.upcast_events(events),
        tenant_id="default",
        organization_id="default",
        execution_id=9001,
        upcaster_registry_digest=default_upcaster_registry.digest(),
    )

    assert state["execution"]["status"] == "COMPLETED"
    assert state["stages"]["10"]["status"] == "COMPLETED"
    assert state["frames"]["100"]["row_count"] == 50
    assert state["frames"]["100"]["output_ref"]["sha256"] == "golden"
    assert state["checksum"] == "cb7a0ee1a70037623330e0348d081ebab1e70ecd11d53c018c87127193f30492"
