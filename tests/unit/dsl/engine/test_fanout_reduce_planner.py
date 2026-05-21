from noetl.core.dsl.engine.parser import DSLParser
from noetl.core.dsl.engine.planner import build_fanout_reduce_plan


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
