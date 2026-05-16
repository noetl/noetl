import pytest


def test_cursor_loop_defaults_to_single_row_frame_policy():
    from noetl.core.dsl.engine.models.workflow import CursorSpec, Loop, LoopSpec

    loop = Loop(
        cursor=CursorSpec(kind="postgres", auth="pg", claim="select 1"),
        iterator="row",
        spec=LoopSpec(mode="cursor", max_in_flight=4),
    )

    assert loop.frame_policy.max_rows == 1
    assert loop.frame_policy.lease_seconds == 120.0


def test_cursor_loop_accepts_frame_policy_alias():
    from noetl.core.dsl.engine.models.workflow import CursorSpec, Loop

    loop = Loop(
        cursor=CursorSpec(kind="postgres", auth="pg", claim="select 1"),
        iterator="row",
        spec={
            "mode": "cursor",
            "max_in_flight": 4,
            "frame": {
                "max_rows": 50,
                "max_seconds": 10,
                "max_bytes": 1024,
                "lease_seconds": 45,
                "heartbeat_seconds": 5,
            },
        },
    )

    assert loop.frame_policy.max_rows == 50
    assert loop.frame_policy.max_seconds == 10
    assert loop.frame_policy.max_bytes == 1024
    assert loop.frame_policy.lease_seconds == 45
    assert loop.frame_policy.heartbeat_seconds == 5


def test_frame_policy_rejects_non_positive_bounds():
    from noetl.core.dsl.engine.models.workflow import FramePolicy

    with pytest.raises(ValueError):
        FramePolicy(max_rows=0)

    with pytest.raises(ValueError):
        FramePolicy(max_seconds=0)
