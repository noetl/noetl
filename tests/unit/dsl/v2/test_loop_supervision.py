import pytest

import noetl.core.dsl.v2.engine as engine_module
from noetl.core.dsl.v2.engine import ControlFlowEngine, ExecutionState, PlaybookRepo, StateStore
from noetl.core.dsl.v2.models import Command, Event, Playbook, ToolCall


class DuplicateLoopItemCache:
    def __init__(self):
        self.try_calls = []

    async def get_pending_command_count(self, execution_id):
        return 1

    async def get_loop_state(self, execution_id, step_name, event_id=None):
        return {
            "collection_size": 2,
            "completed_count": 1,
            "scheduled_count": 1,
            "event_id": event_id,
        }

    async def try_record_loop_iteration_terminal(
        self,
        execution_id,
        step_name,
        iteration_index,
        *,
        event_id=None,
        command_id=None,
        status="COMPLETED",
        terminal_event_name=None,
        terminal_event_id=None,
    ):
        self.try_calls.append(
            {
                "execution_id": execution_id,
                "step_name": step_name,
                "iteration_index": iteration_index,
                "event_id": event_id,
                "command_id": command_id,
                "status": status,
                "terminal_event_name": terminal_event_name,
            }
        )
        return False

    async def increment_loop_completed(self, *args, **kwargs):
        raise AssertionError("duplicate loop item should not increment completed count")

    async def try_claim_loop_done(self, *args, **kwargs):
        return False


class SupervisorCompletionCache:
    def __init__(self):
        self.set_loop_state_calls = []
        self.loop_done_claims = []

    async def get_pending_command_count(self, execution_id):
        return 0

    async def get_loop_state(self, execution_id, step_name, event_id=None):
        return {
            "collection_size": 2,
            "completed_count": 1,
            "scheduled_count": 2,
            "event_id": event_id,
        }

    async def count_observed_loop_iteration_terminals(
        self,
        execution_id,
        step_name,
        *,
        event_id=None,
    ):
        return 2

    async def set_loop_state(self, execution_id, step_name, state, event_id=None):
        self.set_loop_state_calls.append(
            {
                "execution_id": execution_id,
                "step_name": step_name,
                "state": dict(state),
                "event_id": event_id,
            }
        )
        return True

    async def try_claim_loop_done(self, execution_id, step_name, event_id=None):
        self.loop_done_claims.append(
            {
                "execution_id": execution_id,
                "step_name": step_name,
                "event_id": event_id,
            }
        )
        return True


@pytest.mark.asyncio
async def test_duplicate_loop_item_terminal_is_ignored_before_count_increment(monkeypatch):
    playbook = Playbook(
        **{
            "apiVersion": "noetl.io/v2",
            "kind": "Playbook",
            "metadata": {"name": "loop-supervision"},
            "workflow": [
                {
                    "step": "loop_step",
                    "tool": {"kind": "python", "code": "def main(**kwargs): return kwargs"},
                    "loop": {"in": "{{ items }}", "iterator": "item"},
                }
            ],
        }
    )

    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState("9601", playbook, payload={"items": [1, 2]})
    state.loop_state["loop_step"] = {
        "collection": [1, 2],
        "iterator": "item",
        "index": 1,
        "mode": "sequential",
        "completed": False,
        "results": [{"status": "completed"}],
        "failed_count": 0,
        "scheduled_count": 1,
        "aggregation_finalized": False,
        "event_id": "loop_epoch_1",
        "omitted_results_count": 0,
    }
    await state_store.save_state(state)

    cache = DuplicateLoopItemCache()

    async def fake_get_nats_cache():
        return cache

    async def fake_issue_loop_commands(*_args, **_kwargs):
        return [
            Command(
                execution_id="9601",
                step="loop_step",
                tool=ToolCall(kind="python", config={}),
                input={},
                render_context={},
            )
        ]

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_issue_loop_commands", fake_issue_loop_commands)

    event = Event(
        execution_id="9601",
        step="loop_step",
        name="call.done",
        payload={
            "response": {"status": "completed"},
            "loop_event_id": "loop_epoch_1",
            "loop_iteration_index": 0,
            "command_id": "cmd-dup",
        },
        meta={
            "__loop_epoch_id": "loop_epoch_1",
            "loop_iteration_index": 0,
            "command_id": "cmd-dup",
        },
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert len(commands) == 1
    assert len(state.loop_state["loop_step"]["results"]) == 1
    assert cache.try_calls
    assert cache.try_calls[0]["iteration_index"] == 0


@pytest.mark.asyncio
async def test_step_exit_completes_loop_from_supervisor_terminal_count(monkeypatch):
    playbook = Playbook(
        **{
            "apiVersion": "noetl.io/v2",
            "kind": "Playbook",
            "metadata": {"name": "loop-supervision-step-exit"},
            "workflow": [
                {
                    "step": "loop_step",
                    "tool": {"kind": "python", "code": "def main(**kwargs): return kwargs"},
                    "loop": {"in": "{{ items }}", "iterator": "item"},
                }
            ],
        }
    )

    playbook_repo = PlaybookRepo()
    state_store = StateStore(playbook_repo)
    engine = ControlFlowEngine(playbook_repo, state_store)

    state = ExecutionState("9602", playbook, payload={"items": [1, 2]})
    state.loop_state["loop_step"] = {
        "collection": [1, 2],
        "iterator": "item",
        "index": 2,
        "mode": "parallel",
        "completed": False,
        "results": [{"status": "completed"}, {"status": "completed"}],
        "failed_count": 0,
        "scheduled_count": 2,
        "aggregation_finalized": False,
        "event_id": "loop_epoch_2",
        "omitted_results_count": 0,
    }
    await state_store.save_state(state)

    cache = SupervisorCompletionCache()
    persisted_events = []

    async def fake_get_nats_cache():
        return cache

    async def fake_persist_event(event, state):
        persisted_events.append(event)
        state.last_event_id = 1001 + len(persisted_events)

    async def fake_issue_loop_commands(*_args, **_kwargs):
        raise AssertionError("loop should complete instead of issuing more commands")

    async def fake_eval_next(*_args, **_kwargs):
        return []

    monkeypatch.setattr(engine_module, "get_nats_cache", fake_get_nats_cache)
    monkeypatch.setattr(engine, "_persist_event", fake_persist_event)
    monkeypatch.setattr(engine, "_issue_loop_commands", fake_issue_loop_commands)
    monkeypatch.setattr(engine, "_evaluate_next_transitions", fake_eval_next)

    event = Event(
        execution_id="9602",
        step="loop_step",
        name="step.exit",
        payload={"status": "COMPLETED", "result": {"status": "completed"}},
    )

    commands = await engine.handle_event(event, already_persisted=True)

    assert commands == []
    assert cache.set_loop_state_calls
    assert cache.set_loop_state_calls[0]["state"]["completed_count"] == 2
    assert cache.loop_done_claims
    assert persisted_events
    assert persisted_events[0].name == "loop.done"
