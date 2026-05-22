from unittest.mock import patch

from noetl.core.dsl.engine.parser import DSLParser
from noetl.core.dsl.engine.planner import (
    PlannedFanout,
    PlannedReduce,
    FanoutReducePlan,
    build_fanout_reduce_plan,
    validate_fanout_reduce_plan,
)


def test_planner_detects_inclusive_fanout_and_shared_reduce():
    playbook = DSLParser().parse(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: fanout_reduce

workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: inclusive
      arcs:
        - step: branch_a
        - step: branch_b

  - step: branch_a
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: join

  - step: branch_b
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: join

  - step: join
    tool:
      kind: python
      code: "def main(): return {}"
"""
    )

    plan = build_fanout_reduce_plan(playbook)

    assert len(plan.fanouts) == 1
    assert plan.fanouts[0].step == "start"
    assert plan.fanouts[0].arcs == ("branch_a", "branch_b")
    assert plan.fanouts[0].reduce_steps == ("join",)
    assert len(plan.reduces) == 1
    assert plan.reduces[0].step == "join"
    assert plan.reduces[0].upstream_steps == ("branch_a", "branch_b")


def test_planner_keeps_exclusive_router_out_of_fanouts():
    playbook = DSLParser().parse(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: exclusive_router

workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: branch_a
        - step: branch_b

  - step: branch_a
    tool:
      kind: python
      code: "def main(): return {}"

  - step: branch_b
    tool:
      kind: python
      code: "def main(): return {}"
"""
    )

    plan = build_fanout_reduce_plan(playbook)

    assert plan.fanouts == ()
    assert plan.reduces == ()


def test_planner_is_deterministic_for_duplicate_arcs_and_missing_targets():
    playbook = DSLParser().parse(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: duplicate_arcs

workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: inclusive
      arcs:
        - step: branch_b
        - step: branch_a
        - step: branch_b
        - step: missing_step

  - step: branch_a
    tool:
      kind: python
      code: "def main(): return {}"

  - step: branch_b
    tool:
      kind: python
      code: "def main(): return {}"
"""
    )

    plan = build_fanout_reduce_plan(playbook)

    assert len(plan.fanouts) == 1
    assert plan.fanouts[0].arcs == ("branch_b", "branch_a")
    assert plan.reduces == ()


# ---------------------------------------------------------------------------
# Phase 6: validate_fanout_reduce_plan — register-time advisory warnings
# ---------------------------------------------------------------------------


def test_validate_fanout_reduce_plan_returns_empty_for_clean_playbook():
    """Linear / well-formed playbook → no warnings."""
    playbook = DSLParser().parse(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: clean
workflow:
  - step: start
    tool: { kind: python, code: "def main(): return {}" }
    next:
      spec: { mode: inclusive }
      arcs:
        - step: branch_a
        - step: branch_b
  - step: branch_a
    tool: { kind: python, code: "def main(): return {}" }
    next:
      spec: { mode: exclusive }
      arcs:
        - step: join
  - step: branch_b
    tool: { kind: python, code: "def main(): return {}" }
    next:
      spec: { mode: exclusive }
      arcs:
        - step: join
  - step: join
    tool: { kind: python, code: "def main(): return {}" }
"""
    )
    assert validate_fanout_reduce_plan(playbook) == []


def test_validate_fanout_reduce_plan_warns_when_fanout_has_no_reducer():
    """Inclusive-mode fan-out whose targets never converge → warning."""
    playbook = DSLParser().parse(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: fanout_no_join
workflow:
  - step: start
    tool: { kind: python, code: "def main(): return {}" }
    next:
      spec: { mode: inclusive }
      arcs:
        - step: branch_a
        - step: branch_b
  - step: branch_a
    tool: { kind: python, code: "def main(): return {}" }
  - step: branch_b
    tool: { kind: python, code: "def main(): return {}" }
"""
    )
    warnings = validate_fanout_reduce_plan(playbook)
    assert len(warnings) == 1
    assert warnings[0].startswith("[fanout_no_reducer]")
    assert "'start'" in warnings[0]


def test_validate_fanout_reduce_plan_warns_for_orphan_reducer():
    """Synthetic PlannedReduce with <2 upstream surfaces a warning.

    The planner itself never emits such entries; this test exercises the
    validator's defensive path so callers that construct plans by hand
    (tests, fixtures) get flagged.
    """
    synthetic_plan = FanoutReducePlan(
        fanouts=(),
        reduces=(PlannedReduce(step="alone", upstream_steps=("solo",)),),
    )

    with patch(
        "noetl.core.dsl.engine.planner.build_fanout_reduce_plan",
        return_value=synthetic_plan,
    ):
        warnings = validate_fanout_reduce_plan(playbook=object())  # type: ignore[arg-type]

    assert len(warnings) == 1
    assert warnings[0].startswith("[reducer_orphan]")
    assert "'alone'" in warnings[0]


def test_validate_fanout_reduce_plan_empty_plan_returns_no_warnings():
    """is_empty() short-circuits to []."""
    synthetic_plan = FanoutReducePlan()
    assert synthetic_plan.is_empty()
    with patch(
        "noetl.core.dsl.engine.planner.build_fanout_reduce_plan",
        return_value=synthetic_plan,
    ):
        assert validate_fanout_reduce_plan(playbook=object()) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Phase 6: ExecutionState caches the plan
# ---------------------------------------------------------------------------


def _minimal_playbook_with_fanout():
    return DSLParser().parse(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: cache_test
workflow:
  - step: start
    tool: { kind: python, code: "def main(): return {}" }
    next:
      spec: { mode: inclusive }
      arcs:
        - step: branch_a
        - step: branch_b
  - step: branch_a
    tool: { kind: python, code: "def main(): return {}" }
    next:
      spec: { mode: exclusive }
      arcs:
        - step: join
  - step: branch_b
    tool: { kind: python, code: "def main(): return {}" }
    next:
      spec: { mode: exclusive }
      arcs:
        - step: join
  - step: join
    tool: { kind: python, code: "def main(): return {}" }
"""
    )


def test_execution_state_caches_fanout_reduce_plan():
    """ExecutionState.fanout_reduce_plan runs the planner exactly once."""
    from noetl.core.dsl.engine.executor.state import ExecutionState
    import noetl.core.dsl.engine.executor.state as state_module

    playbook = _minimal_playbook_with_fanout()

    with patch.object(
        state_module,
        "build_fanout_reduce_plan",
        wraps=state_module.build_fanout_reduce_plan,
    ) as planner_spy:
        state = ExecutionState(
            execution_id="exec-1",
            playbook=playbook,
            payload={},
        )
        # No call until accessed
        assert planner_spy.call_count == 0

        first = state.fanout_reduce_plan
        second = state.fanout_reduce_plan
        third = state.fanout_reduce_plan

    # Each access returns the same object; planner ran once
    assert first is second is third
    assert planner_spy.call_count == 1

    # The cached plan is structurally correct
    assert len(first.fanouts) == 1
    assert first.fanouts[0].step == "start"
    assert len(first.reduces) == 1
    assert first.reduces[0].step == "join"


def test_execution_state_fanout_reduce_plan_for_linear_playbook():
    """A linear playbook (no fan-outs / reduces) returns an empty plan."""
    from noetl.core.dsl.engine.executor.state import ExecutionState

    playbook = DSLParser().parse(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: linear
workflow:
  - step: only_step
    tool: { kind: python, code: "def main(): return {}" }
"""
    )
    state = ExecutionState(
        execution_id="exec-2",
        playbook=playbook,
        payload={},
    )
    plan = state.fanout_reduce_plan
    assert plan.is_empty()
    # Repeat access returns the same (cached) empty plan
    assert state.fanout_reduce_plan is plan
