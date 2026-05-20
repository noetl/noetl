import json
from pathlib import Path


def test_golden_replay_corpus_checksum_is_stable():
    from noetl.core.replay import default_upcaster_registry
    from noetl.server.api.replay import (
        fold_replay_state,
        replay_projection_checksum_bundle,
    )

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
    assert state["stages"]["10"]["opened_event_id"] == 2
    assert state["stages"]["10"]["closed_event_id"] == 6
    assert state["frames"]["100"]["row_count"] == 50
    assert state["frames"]["100"]["claimed_event_id"] == 3
    assert state["frames"]["100"]["terminal_event_id"] == 5
    assert state["frames"]["100"]["output_ref"]["sha256"] == "golden"
    assert state["commands"] == {}
    assert state["business_objects"] == {}
    assert state["checksum"] == "af23cf75931cf94a536184f58301592a2ee227cc52dadead2bf051cb100b85fb"
    assert state["projection_checksums"] == {
        "business_objects": "ebbff5b72abdea9d0b0d43ec2d3886826f04b313f48535e210120869c16d1a13",
        "commands": "a9c3a7631d2a488d1a25c667c554f206b08ddd4ed9f3f6b3c9a4bec2e7f3bd84",
        "execution": "8b15e0b97eb3ee60e69d01229f250aa5347ca3322c7258586f4900d01c62c6f8",
        "frames": "2ee5a2db92349c9546b04ad39ccbe52351f37e0de5b56532e7ebfb617ef645ec",
        "loops": "68c1d1020e5737344e10a59610494db939837977ba662211649a238d5d30561b",
        "stages": "8a97fc5a5d69672bc627c064c8c672b49814c6e64ace3096fe4f2fe144ad0cdc",
    }
    assert replay_projection_checksum_bundle(state) == state["projection_checksums"]
