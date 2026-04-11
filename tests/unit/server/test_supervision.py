import pytest

import noetl.server.api.supervision as supervision_module


class _SupervisorCache:
    def __init__(self):
        self.command_issued_calls = []
        self.command_terminal_calls = []
        self.loop_iteration_state_calls = []

    async def register_command_issued(self, *args, **kwargs):
        self.command_issued_calls.append((args, kwargs))
        return True

    async def mark_command_terminal(self, *args, **kwargs):
        self.command_terminal_calls.append((args, kwargs))
        return True

    async def set_loop_iteration_state(
        self,
        execution_id,
        step_name,
        iteration_index,
        state,
        *,
        event_id=None,
    ):
        self.loop_iteration_state_calls.append(
            {
                "execution_id": execution_id,
                "step_name": step_name,
                "iteration_index": iteration_index,
                "state": state,
                "event_id": event_id,
            }
        )
        return True


@pytest.mark.asyncio
async def test_supervise_persisted_event_preserves_loop_result_pointer_without_terminalizing(monkeypatch):
    cache = _SupervisorCache()

    async def fake_get_nats_cache():
        return cache

    monkeypatch.setattr(supervision_module, "get_nats_cache", fake_get_nats_cache)

    await supervision_module.supervise_persisted_event(
        "exec-1",
        "fetch_assessments:task_sequence",
        "call.done",
        payload={
            "command_id": "cmd-1",
            "loop_event_id": "loop-epoch-1",
            "loop_iteration_index": 7,
            "response": {
                "_ref": {
                    "kind": "result_ref",
                    "ref": "noetl://execution/exec-1/result/fetch_assessments.task_sequence/abc123",
                    "store": "kv",
                }
            },
        },
        meta={
            "command_id": "cmd-1",
            "__loop_epoch_id": "loop-epoch-1",
            "loop_iteration_index": 7,
        },
        event_id=901,
    )

    assert len(cache.command_terminal_calls) == 1
    assert len(cache.loop_iteration_state_calls) == 1

    loop_call = cache.loop_iteration_state_calls[0]
    assert loop_call["execution_id"] == "exec-1"
    assert loop_call["step_name"] == "fetch_assessments"
    assert loop_call["iteration_index"] == 7
    assert loop_call["event_id"] == "loop-epoch-1"
    assert loop_call["state"]["last_event_name"] == "call.done"
    assert loop_call["state"]["last_event_id"] == 901
    assert loop_call["state"]["command_id"] == "cmd-1"
    assert loop_call["state"]["result_pointer"]["ref"] == (
        "noetl://execution/exec-1/result/fetch_assessments.task_sequence/abc123"
    )
    assert "status" not in loop_call["state"]
    assert "terminal_event_name" not in loop_call["state"]


@pytest.mark.asyncio
async def test_supervise_command_issued_records_loop_issue_metadata(monkeypatch):
    cache = _SupervisorCache()

    async def fake_get_nats_cache():
        return cache

    monkeypatch.setattr(supervision_module, "get_nats_cache", fake_get_nats_cache)

    await supervision_module.supervise_command_issued(
        "exec-2",
        "cmd-2",
        "fetch_assessments:task_sequence",
        event_id=902,
        meta={
            "loop_step": "fetch_assessments",
            "__loop_epoch_id": "loop-epoch-2",
            "loop_iteration_index": 4,
        },
    )

    assert len(cache.command_issued_calls) == 1
    assert len(cache.loop_iteration_state_calls) == 1

    loop_call = cache.loop_iteration_state_calls[0]
    assert loop_call["step_name"] == "fetch_assessments"
    assert loop_call["iteration_index"] == 4
    assert loop_call["event_id"] == "loop-epoch-2"
    assert loop_call["state"]["status"] == "ISSUED"
    assert loop_call["state"]["last_event_name"] == "command.issued"
    assert loop_call["state"]["last_event_id"] == 902
    assert "issued_at" in loop_call["state"]


@pytest.mark.asyncio
async def test_supervise_persisted_event_records_loop_start_metadata(monkeypatch):
    cache = _SupervisorCache()

    async def fake_get_nats_cache():
        return cache

    monkeypatch.setattr(supervision_module, "get_nats_cache", fake_get_nats_cache)

    await supervision_module.supervise_persisted_event(
        "exec-3",
        "fetch_assessments:task_sequence",
        "command.started",
        payload={"command_id": "cmd-3"},
        meta={
            "command_id": "cmd-3",
            "__loop_epoch_id": "loop-epoch-3",
            "loop_iteration_index": 5,
        },
        event_id=903,
    )

    assert len(cache.command_terminal_calls) == 0
    assert len(cache.loop_iteration_state_calls) == 1

    loop_call = cache.loop_iteration_state_calls[0]
    assert loop_call["step_name"] == "fetch_assessments"
    assert loop_call["iteration_index"] == 5
    assert loop_call["state"]["status"] == "STARTED"
    assert loop_call["state"]["last_event_name"] == "command.started"
    assert loop_call["state"]["last_event_id"] == 903
    assert "started_at" in loop_call["state"]
