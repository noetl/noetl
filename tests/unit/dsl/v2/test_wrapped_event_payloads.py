import pytest

from noetl.core.dsl.v2.engine import ControlFlowEngine, ExecutionState, PlaybookRepo, StateStore
from noetl.core.dsl.v2.models import Event
from noetl.core.dsl.v2.parser import DSLParser


def _build_engine(playbook_yaml: str, execution_id: str):
    parser = DSLParser()
    playbook = parser.parse(playbook_yaml)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)
    state = ExecutionState(execution_id, playbook, payload={})
    return engine, state_store, state


@pytest.mark.asyncio
async def test_wrapped_call_done_renders_follow_up_step_from_unwrapped_result():
    engine, state_store, state = _build_engine(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: wrapped_result_render

workflow:
  - step: extract
    tool:
      kind: python
      args: {}
      code: |
        result = {"performance_rating": 4.0}
    next:
      spec:
        mode: exclusive
      arcs:
        - step: score

  - step: score
    tool:
      kind: python
      args:
        performance_rating: "{{ extract.performance_rating }}"
      code: |
        result = {"seen": performance_rating}
""",
        "exec-wrapped-score",
    )
    await state_store.save_state(state)

    commands = await engine.handle_event(
        Event(
            execution_id="exec-wrapped-score",
            step="extract",
            name="call.done",
            payload={
                "kind": "data",
                "data": {
                    "response": {
                        "performance_rating": 4.0,
                    }
                },
            },
        ),
        already_persisted=True,
    )

    assert len(commands) == 1
    assert commands[0].step == "score"
    assert commands[0].tool.config["args"]["performance_rating"] == 4.0


@pytest.mark.asyncio
async def test_wrapped_task_sequence_call_done_syncs_ctx_for_follow_up_step():
    engine, state_store, state = _build_engine(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: wrapped_task_sequence_ctx

workflow:
  - step: create
    tool:
      kind: python
      args: {}
      code: |
        result = {"user_id": 999}
      spec:
        policy:
          rules:
            - else:
                then:
                  do: continue
                  set_ctx:
                    test_user_id: "{{ outcome.result.user_id }}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: verify

  - step: verify
    tool:
      kind: python
      args:
        user_id: "{{ ctx.test_user_id }}"
      code: |
        result = {"user_id": user_id}
""",
        "exec-wrapped-task-seq",
    )
    await state_store.save_state(state)

    commands = await engine.handle_event(
        Event(
            execution_id="exec-wrapped-task-seq",
            step="create:task_sequence",
            name="call.done",
            payload={
                "kind": "data",
                "data": {
                    "response": {
                        "ctx": {
                            "test_user_id": "999",
                        },
                        "_prev": {
                            "user_id": 999,
                        },
                        "status": "ok",
                        "results": {
                            "create_task": {
                                "user_id": 999,
                            }
                        },
                    }
                },
            },
        ),
        already_persisted=True,
    )

    assert len(commands) == 1
    assert commands[0].step == "verify"
    assert commands[0].tool.config["args"]["user_id"] == "999"
