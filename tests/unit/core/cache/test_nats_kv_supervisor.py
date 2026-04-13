import json
from datetime import datetime, timedelta, timezone

import pytest
from nats.js.errors import KeyNotFoundError as NatsKeyNotFoundError

from noetl.core.cache.nats_kv import NATSKVCache


class _FakeKVEntry:
    def __init__(self, payload: dict, revision: int):
        self.value = json.dumps(payload).encode("utf-8")
        self.revision = revision


class _MultiKeyKV:
    def __init__(self):
        self.payloads: dict[str, dict] = {}
        self.revisions: dict[str, int] = {}

    async def get(self, key: str):
        if key not in self.payloads:
            raise NatsKeyNotFoundError()
        return _FakeKVEntry(self.payloads[key], self.revisions[key])

    async def put(self, key: str, value: bytes):
        self.payloads[key] = json.loads(value.decode("utf-8"))
        self.revisions[key] = self.revisions.get(key, 0) + 1
        return self.revisions[key]

    async def update(self, key: str, value: bytes, last: int):
        current_revision = self.revisions.get(key)
        if current_revision != last:
            raise Exception("wrong last sequence")
        self.payloads[key] = json.loads(value.decode("utf-8"))
        self.revisions[key] = current_revision + 1
        return self.revisions[key]

    async def keys(self):
        return list(self.payloads.keys())


@pytest.mark.asyncio
async def test_register_command_issued_increments_pending_once():
    cache = NATSKVCache()
    cache._kv = _MultiKeyKV()

    ok_first = await cache.register_command_issued(
        "exec1",
        "cmd1",
        "step_a",
        command_event_id=101,
        meta={"loop_step": "step_a"},
    )
    ok_second = await cache.register_command_issued(
        "exec1",
        "cmd1",
        "step_a",
        command_event_id=101,
        meta={"loop_step": "step_a"},
    )

    execution_state = await cache.get_execution_state("exec1")
    pending_count = await cache.get_pending_command_count("exec1")

    assert ok_first is True
    assert ok_second is True
    assert execution_state is not None
    assert pending_count == 1
    assert execution_state["last_command_id"] == "cmd1"


@pytest.mark.asyncio
async def test_mark_command_terminal_decrements_pending_once():
    cache = NATSKVCache()
    cache._kv = _MultiKeyKV()

    await cache.register_command_issued("exec2", "cmd2", "step_b")

    ok_first = await cache.mark_command_terminal(
        "exec2",
        "cmd2",
        "COMPLETED",
        event_name="call.done",
        event_id=202,
        step_name="step_b",
    )
    ok_second = await cache.mark_command_terminal(
        "exec2",
        "cmd2",
        "COMPLETED",
        event_name="command.completed",
        event_id=203,
        step_name="step_b",
    )

    command_key = cache._make_key("exec2", "command:cmd2")
    command_state = cache._kv.payloads[command_key]

    assert ok_first is True
    assert ok_second is True
    assert await cache.get_pending_command_count("exec2") == 0
    assert command_state["status"] == "COMPLETED"
    assert command_state["terminal_event_name"] == "call.done"


@pytest.mark.asyncio
async def test_mark_loop_iteration_terminal_persists_pointer():
    cache = NATSKVCache()
    cache._kv = _MultiKeyKV()

    await cache.set_loop_iteration_state(
        "exec3",
        "loop_step",
        4,
        {"status": "ISSUED", "command_id": "cmd-4"},
        event_id="loop_epoch_1",
    )

    ok = await cache.mark_loop_iteration_terminal(
        "exec3",
        "loop_step",
        4,
        event_id="loop_epoch_1",
        command_id="cmd-4",
        status="COMPLETED",
        result_pointer={"kind": "result_ref", "ref": "noetl://execution/exec3/result/loop_step/4"},
        terminal_event_name="call.done",
        terminal_event_id=303,
    )

    state = await cache.get_loop_iteration_state(
        "exec3",
        "loop_step",
        4,
        event_id="loop_epoch_1",
    )

    assert ok is True
    assert state is not None
    assert state["status"] == "COMPLETED"
    assert state["terminal_event_name"] == "call.done"
    assert state["result_pointer"]["ref"] == "noetl://execution/exec3/result/loop_step/4"


@pytest.mark.asyncio
async def test_try_record_loop_iteration_terminal_is_idempotent_per_epoch_item():
    cache = NATSKVCache()
    cache._kv = _MultiKeyKV()

    await cache.set_loop_state(
        "exec4",
        "loop_step",
        {"collection_size": 5, "completed_count": 1, "scheduled_count": 2},
        event_id="loop_epoch_2",
    )
    await cache.set_loop_iteration_state(
        "exec4",
        "loop_step",
        2,
        {"status": "ISSUED", "command_id": "cmd-2"},
        event_id="loop_epoch_2",
    )

    first = await cache.try_record_loop_iteration_terminal(
        "exec4",
        "loop_step",
        2,
        event_id="loop_epoch_2",
        command_id="cmd-2",
        status="COMPLETED",
        terminal_event_name="call.done",
        terminal_event_id=404,
    )
    second = await cache.try_record_loop_iteration_terminal(
        "exec4",
        "loop_step",
        2,
        event_id="loop_epoch_2",
        command_id="cmd-2b",
        status="COMPLETED",
        terminal_event_name="call.done",
        terminal_event_id=405,
    )

    state = await cache.get_loop_iteration_state(
        "exec4",
        "loop_step",
        2,
        event_id="loop_epoch_2",
    )

    assert first is True
    assert second is False
    assert state is not None
    assert state["terminal_event_id"] == 404


@pytest.mark.asyncio
async def test_try_record_loop_iteration_terminal_returns_none_when_epoch_missing():
    cache = NATSKVCache()
    cache._kv = _MultiKeyKV()

    result = await cache.try_record_loop_iteration_terminal(
        "exec5",
        "loop_step",
        1,
        event_id="missing_epoch",
        command_id="cmd-x",
        status="COMPLETED",
        terminal_event_name="call.done",
    )

    assert result is None


@pytest.mark.asyncio
async def test_set_loop_iteration_state_preserves_terminal_status():
    cache = NATSKVCache()
    cache._kv = _MultiKeyKV()

    await cache.set_loop_iteration_state(
        "exec6",
        "loop_step",
        3,
        {
            "status": "COMPLETED",
            "terminal_event_name": "call.done",
            "terminal_event_id": 606,
        },
        event_id="loop_epoch_6",
    )

    ok = await cache.set_loop_iteration_state(
        "exec6",
        "loop_step",
        3,
        {
            "last_event_name": "call.done",
            "result_pointer": {"kind": "result_ref", "ref": "noetl://execution/exec6/result/loop_step/3"},
        },
        event_id="loop_epoch_6",
    )

    state = await cache.get_loop_iteration_state(
        "exec6",
        "loop_step",
        3,
        event_id="loop_epoch_6",
    )

    assert ok is True
    assert state is not None
    assert state["status"] == "COMPLETED"
    assert state["terminal_event_id"] == 606
    assert state["result_pointer"]["ref"] == "noetl://execution/exec6/result/loop_step/3"


@pytest.mark.asyncio
async def test_set_loop_iteration_state_preserves_terminal_status_against_late_started_update():
    cache = NATSKVCache()
    cache._kv = _MultiKeyKV()

    await cache.set_loop_iteration_state(
        "exec6b",
        "loop_step",
        3,
        {
            "status": "COMPLETED",
            "terminal_event_name": "call.done",
            "terminal_event_id": 607,
        },
        event_id="loop_epoch_6b",
    )

    ok = await cache.set_loop_iteration_state(
        "exec6b",
        "loop_step",
        3,
        {
            "status": "STARTED",
            "last_event_name": "command.started",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
        event_id="loop_epoch_6b",
    )

    state = await cache.get_loop_iteration_state(
        "exec6b",
        "loop_step",
        3,
        event_id="loop_epoch_6b",
    )

    assert ok is True
    assert state is not None
    assert state["status"] == "COMPLETED"
    assert state["terminal_event_id"] == 607


@pytest.mark.asyncio
async def test_count_observed_loop_iteration_terminals_uses_status_and_last_event():
    cache = NATSKVCache()
    cache._kv = _MultiKeyKV()

    await cache.set_loop_iteration_state(
        "exec7",
        "loop_step",
        0,
        {"status": "COMPLETED", "terminal_event_name": "call.done"},
        event_id="loop_epoch_7",
    )
    await cache.set_loop_iteration_state(
        "exec7",
        "loop_step",
        1,
        {"status": "ISSUED", "last_event_name": "call.done"},
        event_id="loop_epoch_7",
    )
    await cache.set_loop_iteration_state(
        "exec7",
        "loop_step",
        2,
        {"status": "ISSUED", "last_event_name": "command.started"},
        event_id="loop_epoch_7",
    )

    count = await cache.count_observed_loop_iteration_terminals(
        "exec7",
        "loop_step",
        event_id="loop_epoch_7",
    )

    assert count == 2


@pytest.mark.asyncio
async def test_find_supervisor_missing_and_orphaned_loop_iteration_indices():
    cache = NATSKVCache()
    cache._kv = _MultiKeyKV()

    old_issued_at = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    fresh_issued_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

    await cache.set_loop_iteration_state(
        "exec8",
        "loop_step",
        0,
        {
            "status": "ISSUED",
            "last_event_name": "command.issued",
            "issued_at": old_issued_at,
        },
        event_id="loop_epoch_8",
    )
    await cache.set_loop_iteration_state(
        "exec8",
        "loop_step",
        1,
        {
            "status": "STARTED",
            "last_event_name": "command.started",
            "issued_at": old_issued_at,
            "started_at": old_issued_at,
        },
        event_id="loop_epoch_8",
    )
    await cache.set_loop_iteration_state(
        "exec8",
        "loop_step",
        2,
        {
            "status": "ISSUED",
            "last_event_name": "call.done",
            "issued_at": old_issued_at,
        },
        event_id="loop_epoch_8",
    )
    await cache.set_loop_iteration_state(
        "exec8",
        "loop_step",
        3,
        {
            "status": "ISSUED",
            "last_event_name": "command.issued",
            "issued_at": fresh_issued_at,
        },
        event_id="loop_epoch_8",
    )

    missing = await cache.find_supervisor_missing_loop_iteration_indices(
        "exec8",
        "loop_step",
        event_id="loop_epoch_8",
        limit=10,
        min_age_seconds=10.0,
    )
    orphaned = await cache.find_supervisor_orphaned_loop_iteration_indices(
        "exec8",
        "loop_step",
        event_id="loop_epoch_8",
        limit=10,
    )

    assert missing == [0]
    assert orphaned == [0, 3]
