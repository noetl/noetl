"""
Tests for dead-end detection under command deduplication races.

Regression coverage for:
  _evaluate_next_transitions_with_match returning any_matched instead of
  any_actionable_issued — a matched-but-deduplicated arc must NOT be treated
  as a dead-end transition.

Production evidence: execution 590113029212078805 on release 2.10.39 hit a false
dead-end at load_patients_for_conditions despite an unconditional fallback arc
to load_patients_for_medications.  The target step was already in issued_steps
from a concurrent call.done processor on a second pod, so command creation was
skipped and the old code returned ([], False) — incorrectly triggering workflow
completion.
"""

import pytest
import yaml

from noetl.core.dsl.engine.executor import ControlFlowEngine, ExecutionState, PlaybookRepo, StateStore
from noetl.core.dsl.engine.models import Event, NextRouter, Playbook


PLAYBOOK_WITH_UNCONDITIONAL_FALLBACK = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: dead_end_dedup_test

workflow:
  - step: step_a
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: step_b

  - step: step_b
    tool:
      kind: python
      code: "def main(): return {}"
"""

PLAYBOOK_WITH_CONDITIONAL_AND_FALLBACK = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: dead_end_dedup_conditional_test

workflow:
  - step: step_a
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: step_b
          when: "{{ ctx.row_count > 0 }}"
        - step: step_c

  - step: step_b
    tool:
      kind: python
      code: "def main(): return {}"

  - step: step_c
    tool:
      kind: python
      code: "def main(): return {}"
"""


@pytest.fixture
def engine():
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    return ControlFlowEngine(playbook_repo, state_store)


@pytest.mark.asyncio
async def test_matched_unconditional_arc_deduplicated_returns_any_matched_true(engine):
    """
    A second call.done processor finds step_b already in issued_steps.
    Command creation is skipped (deduplication), but any_matched must be True
    so dead-end detection does not prematurely complete the workflow.
    """
    playbook = Playbook(**yaml.safe_load(PLAYBOOK_WITH_UNCONDITIONAL_FALLBACK))
    state = ExecutionState("99007", playbook, payload={})
    # Simulate the first pod already issued step_b
    state.issued_steps.add("step_b")

    event = Event(
        execution_id = "99007",
        step="step_a",
        name="call.done",
        payload={},
    )
    step_def = state.get_step("step_a")
    commands, any_matched = await engine._evaluate_next_transitions_with_match(
        state, step_def, event
    )

    # No new command — deduplication fired
    assert commands == [], "Expected no commands when target step already issued"
    # But the arc DID match — this must NOT look like a dead-end
    assert any_matched is True, (
        "any_matched must be True for a matched-but-deduplicated arc; "
        "returning False would cause premature workflow completion"
    )


@pytest.mark.asyncio
async def test_matched_conditional_fallback_deduplicated_returns_any_matched_true(engine):
    """
    Unconditional fallback arc (step_c) matches when the conditional arc
    (step_b) does not.  If step_c is already issued, the result must still
    be any_matched=True.
    """
    playbook = Playbook(**yaml.safe_load(PLAYBOOK_WITH_CONDITIONAL_AND_FALLBACK))
    state = ExecutionState("99008", playbook, payload={})
    # row_count not set → conditional arc (step_b) will not match
    # step_c (unconditional fallback) matches but is already issued
    state.issued_steps.add("step_c")

    event = Event(
        execution_id = "99008",
        step="step_a",
        name="call.done",
        payload={},
    )
    step_def = state.get_step("step_a")
    commands, any_matched = await engine._evaluate_next_transitions_with_match(
        state, step_def, event
    )

    assert commands == [], "Expected no commands when fallback step already issued"
    assert any_matched is True, (
        "Unconditional fallback arc matched; any_matched must be True even when deduplicated"
    )


@pytest.mark.asyncio
async def test_missing_target_step_does_not_set_any_matched(engine):
    """
    If the playbook references a next step that does not exist, the arc
    condition match should NOT count — any_matched stays False so dead-end
    detection can fire correctly.
    """
    playbook = Playbook(**yaml.safe_load(PLAYBOOK_WITH_UNCONDITIONAL_FALLBACK))
    state = ExecutionState("99009", playbook, payload={})

    # Override next to point at a step that doesn't exist in the playbook
    step_def = state.get_step("step_a")
    assert step_def is not None
    step_def.next = NextRouter.model_validate(
        {"spec": {"mode": "exclusive"}, "arcs": [{"step": "nonexistent_step"}]}
    )

    event = Event(
        execution_id = "99009",
        step="step_a",
        name="call.done",
        payload={},
    )
    commands, any_matched = await engine._evaluate_next_transitions_with_match(
        state, step_def, event
    )

    assert commands == [], "Expected no commands for missing target step"
    assert any_matched is False, (
        "any_matched must be False when the target step does not exist; "
        "this allows dead-end detection to trigger correctly"
    )
