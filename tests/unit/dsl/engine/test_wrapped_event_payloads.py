import pytest

import noetl.core.dsl.engine.executor as engine_module
from noetl.core.dsl.engine.executor import ControlFlowEngine, ExecutionState, PlaybookRepo, StateStore
from noetl.core.dsl.engine.models import Event
from noetl.core.dsl.engine.parser import DSLParser


def _build_engine(playbook_yaml: str, execution_id: str):
    parser = DSLParser()
    playbook = parser.parse(playbook_yaml)
    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)
    state = ExecutionState(execution_id, playbook, payload={})
    return engine, state_store, state


@pytest.mark.asyncio
async def test_wrapped_call_done_renders_follow_up_step_from_unwrapped_result(monkeypatch):
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
      input: {}
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
      input:
        performance_rating: "{{ extract.performance_rating }}"
      code: |
        result = {"seen": performance_rating}
        """,
        "99101",
    )
    await state_store.save_state(state)

    async def fake_load_state(_id, *args, **kwargs):
        return state
    monkeypatch.setattr(state_store, "load_state", fake_load_state)

    commands = await engine.handle_event(
        Event(
            execution_id="99101",
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
    assert commands[0].tool.config["input"]["performance_rating"] == 4.0


@pytest.mark.asyncio
async def test_wrapped_task_sequence_call_done_syncs_ctx_for_follow_up_step(monkeypatch):
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
      input: {}
      code: |
        result = {"user_id": 999}
      spec:
        policy:
          rules:
            - else:
                then:
                  do: continue
                  set:
                    ctx.test_user_id: "{{ output.data.user_id }}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: verify

  - step: verify
    tool:
      kind: python
      input:
        user_id: "{{ ctx.test_user_id }}"
      code: |
        result = {"user_id": user_id}
""",
        "99102",
    )
    await state_store.save_state(state)

    async def fake_load_state(_id, *args, **kwargs):
        return state
    monkeypatch.setattr(state_store, "load_state", fake_load_state)

    commands = await engine.handle_event(
        Event(
            execution_id="99102",
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
    assert commands[0].tool.config["input"]["user_id"] == "999"


@pytest.mark.asyncio
async def test_reference_only_call_done_resolves_result_ref_for_follow_up_step(monkeypatch):
    engine, state_store, state = _build_engine(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: wrapped_reference_result

workflow:
  - step: validate_results
    tool:
      kind: postgres
      query: SELECT 1;
    next:
      spec:
        mode: exclusive
      arcs:
        - step: check_results

  - step: check_results
    tool:
      kind: python
      input:
        stats: "{{ validate_results.data.command_0.rows }}"
      code: |
        result = {"stats": stats}
""",
        "99103",
    )
    await state_store.save_state(state)

    async def fake_load_state(_id, *args, **kwargs):
        return state
    monkeypatch.setattr(state_store, "load_state", fake_load_state)

    async def fake_resolve(ref):
        assert ref["ref"] == "noetl://execution/123/result/validate_results/abcd1234"
        return {
            "command_0": {
                "rows": [{"total_patients": 500}],
            }
        }

    monkeypatch.setattr(engine_module.default_store, "resolve", fake_resolve)

    commands = await engine.handle_event(
        Event(
            execution_id = "99103",
            step="validate_results",
            name="call.done",
            payload={
                "result": {
                    "status": "completed",
                    "reference": {
                        "type": "nats",
                        "store": "kv",
                        "locator": "noetl://execution/123/result/validate_results/abcd1234",
                    },
                }
            },
        ),
        already_persisted=True,
    )

    assert len(commands) == 1
    assert commands[0].step == "check_results"
    assert commands[0].tool.config["input"]["stats"] == [{"total_patients": 500}]
