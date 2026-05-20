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
    assert loop.frame_policy.row_concurrency == 1
    assert loop.frame_policy.process == "row"


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
            "row_concurrency": 4,
            "process": "frame",
        },
        },
    )

    assert loop.frame_policy.max_rows == 50
    assert loop.frame_policy.max_seconds == 10
    assert loop.frame_policy.max_bytes == 1024
    assert loop.frame_policy.lease_seconds == 45
    assert loop.frame_policy.heartbeat_seconds == 5
    assert loop.frame_policy.row_concurrency == 4
    assert loop.frame_policy.process == "frame"


def test_cursor_loop_accepts_templated_max_in_flight():
    from noetl.core.dsl.engine.models.workflow import CursorSpec, Loop, LoopSpec

    loop = Loop(
        cursor=CursorSpec(kind="postgres", auth="pg", claim="select 1"),
        iterator="row",
        spec=LoopSpec(mode="cursor", max_in_flight="{{ workload.pft_http_concurrency }}"),
    )

    assert loop.spec.max_in_flight == "{{ workload.pft_http_concurrency }}"


def test_templated_max_in_flight_resolves_against_workload_context():
    from jinja2 import Environment

    from noetl.core.dsl.engine.executor.transitions import TransitionMixin
    from noetl.core.dsl.engine.models.workflow import CursorSpec, Loop, Step

    class DummyTransitions(TransitionMixin):
        jinja_env = Environment()

    step = Step(
        step="fetch_patients",
        loop=Loop(
            cursor=CursorSpec(kind="postgres", auth="pg", claim="select 1"),
            iterator="row",
            spec={"mode": "cursor", "max_in_flight": "{{ workload.pft_http_concurrency }}"},
        ),
    )

    assert DummyTransitions()._get_loop_max_in_flight(
        step,
        {"workload": {"pft_http_concurrency": 8}},
    ) == 8


def test_templated_max_in_flight_rejects_non_positive_rendered_value():
    from jinja2 import Environment

    from noetl.core.dsl.engine.executor.transitions import TransitionMixin
    from noetl.core.dsl.engine.models.workflow import CursorSpec, Loop, Step

    class DummyTransitions(TransitionMixin):
        jinja_env = Environment()

    step = Step(
        step="fetch_patients",
        loop=Loop(
            cursor=CursorSpec(kind="postgres", auth="pg", claim="select 1"),
            iterator="row",
            spec={"mode": "cursor", "max_in_flight": "{{ workload.pft_http_concurrency }}"},
        ),
    )

    with pytest.raises(ValueError, match="positive integer"):
        DummyTransitions()._get_loop_max_in_flight(
            step,
            {"workload": {"pft_http_concurrency": 0}},
        )


def test_parser_validation_allows_renderable_max_in_flight():
    from noetl.core.dsl.engine.parser.validation import ParserValidationMixin

    class Validator(ParserValidationMixin):
        pass

    Validator()._validate_loop_v10(
        {
            "cursor": {"kind": "postgres", "auth": "pg", "claim": "select 1"},
            "iterator": "row",
            "spec": {"mode": "cursor", "max_in_flight": "{{ workload.pft_http_concurrency }}"},
        },
        "fetch_patients",
    )


def test_parser_accepts_cursor_loop_with_renderable_max_in_flight():
    from noetl.core.dsl.engine.parser import DSLParser

    playbook = DSLParser().parse(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: templated-cursor-concurrency
workload:
  pft_http_concurrency: 8
workflow:
  - step: fetch_patients
    loop:
      cursor:
        kind: postgres
        auth: pg
        claim: select 1
      iterator: row
      spec:
        mode: cursor
        max_in_flight: "{{ workload.pft_http_concurrency }}"
    tool:
      kind: noop
"""
    )

    step = playbook.workflow[0]
    assert step.loop.spec.max_in_flight == "{{ workload.pft_http_concurrency }}"


def test_parser_validation_rejects_loop_with_both_collection_and_cursor():
    from noetl.core.dsl.engine.parser.validation import ParserValidationMixin

    class Validator(ParserValidationMixin):
        pass

    with pytest.raises(ValueError, match="either 'in' or 'cursor'"):
        Validator()._validate_loop_v10(
            {
                "in": "{{ workload.items }}",
                "cursor": {"kind": "postgres", "auth": "pg", "claim": "select 1"},
                "iterator": "row",
                "spec": {"mode": "cursor", "max_in_flight": 2},
            },
            "fetch_patients",
        )


def test_frame_policy_rejects_non_positive_bounds():
    from noetl.core.dsl.engine.models.workflow import FramePolicy

    with pytest.raises(ValueError):
        FramePolicy(max_rows=0)

    with pytest.raises(ValueError):
        FramePolicy(max_seconds=0)
