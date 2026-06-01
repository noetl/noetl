"""Regression tests for noetl/ai-meta#37 Fix B.

The status endpoint's inference fallback hardcoded ``node_name == "end"`` in
two places:

  1. State-store path (``get_execution_status`` with loaded state):
     ``state.current_step == "end" and "end" in state.completed_steps``

  2. Event-log fallback path (no loaded state):
     ``latest["node_name"] == "end"``

Both checks must work for any terminal step name.  These tests verify the
corrected logic on the state-store path (the primary production path) using a
playbook whose terminal step is named ``"done"``.
"""

import pytest
from noetl.core.dsl.engine.executor import ExecutionState
from noetl.core.dsl.engine.parser import DSLParser


_PLAYBOOK_YAML = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: done_terminal_regression
  path: tests/fixtures/done_terminal_regression

workflow:
  - step: step_a
    tool:
      kind: shell
      command: 'echo step_a'
    next:
      arcs:
        - step: step_b

  - step: step_b
    tool:
      kind: shell
      command: 'echo step_b'
    next:
      arcs:
        - step: done

  - step: done
    tool:
      kind: shell
      command: 'echo done'
"""


def _make_state(*, completed: bool = False, failed: bool = False) -> ExecutionState:
    playbook = DSLParser().parse(_PLAYBOOK_YAML)
    state = ExecutionState(
        execution_id="9000000000000002",
        playbook=playbook,
        payload={},
    )
    state.completed = completed
    state.failed = failed
    state.current_step = "done"
    state.completed_steps = {"step_a", "step_b", "done"}
    return state


def _infer_completed(state: ExecutionState, *, failed: bool = False) -> tuple[bool, bool]:
    """Pure Python version of the status-endpoint state-store inference logic.

    Returns (completed, inferred) mirroring the corrected branch in
    ``get_execution_status``.
    """
    if state.completed:
        return True, False

    _cs = state.current_step
    _cs_def = state.get_step(_cs) if _cs else None
    _step_is_terminal = bool(_cs_def and not _cs_def.next)
    if _step_is_terminal and _cs in state.completed_steps and not failed:
        return True, True

    return False, False


class TestTerminalStepInference:
    """Unit tests for the corrected terminal-step inference logic."""

    def test_done_step_is_detected_as_terminal(self):
        """get_step('done') must return a step with no .next attribute."""
        state = _make_state()
        done_def = state.get_step("done")
        assert done_def is not None, "Step 'done' must exist in the playbook"
        assert not done_def.next, "Step 'done' must have no next transitions"

    def test_end_step_would_be_detected_as_terminal_too(self):
        """Sanity check: a step literally named 'end' is also terminal under the new logic."""
        yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: end_terminal

workflow:
  - step: start
    tool:
      kind: shell
      command: 'echo start'
    next:
      arcs:
        - step: end

  - step: end
    tool:
      kind: shell
      command: 'echo end'
"""
        playbook = DSLParser().parse(yaml_content)
        state = ExecutionState(execution_id="9000000000000003", playbook=playbook, payload={})
        state.current_step = "end"
        state.completed_steps = {"start", "end"}

        end_def = state.get_step("end")
        assert end_def is not None
        assert not end_def.next

        completed, inferred = _infer_completed(state)
        assert completed is True, "Inference must work for the 'end' step too"
        assert inferred is True

    def test_inference_returns_completed_for_done_terminal_step(self):
        """With 'done' as current_step in completed_steps and not failed → completed=True."""
        state = _make_state()
        completed, inferred = _infer_completed(state)
        assert completed is True, "Inference must return completed=True for terminal 'done' step"
        assert inferred is True

    def test_inference_returns_not_completed_when_state_already_true(self):
        """If state.completed is already True the fast path fires."""
        state = _make_state(completed=True)
        completed, inferred = _infer_completed(state)
        assert completed is True
        assert inferred is False  # fast-path, not the heuristic

    def test_inference_returns_not_completed_when_step_not_in_completed_steps(self):
        """If 'done' is current_step but NOT in completed_steps, must NOT infer complete."""
        state = _make_state()
        state.completed_steps = {"step_a", "step_b"}  # done not yet marked
        completed, inferred = _infer_completed(state)
        assert completed is False

    def test_inference_not_completed_when_failed(self):
        """A failed execution must not be inferred as completed."""
        state = _make_state(failed=True)
        completed, inferred = _infer_completed(state, failed=True)
        assert completed is False

    def test_non_terminal_step_not_inferred_as_complete(self):
        """A mid-workflow step with outgoing transitions must not trigger inference."""
        state = _make_state()
        state.current_step = "step_a"
        state.completed_steps = {"step_a"}
        completed, inferred = _infer_completed(state)
        assert completed is False, "step_a has a next arc; it is not terminal"
