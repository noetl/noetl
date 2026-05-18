"""
Tests for the command-table-first runtime command reaper.

The reaper scans ``noetl.command`` directly for non-terminal commands whose
execution is still live, and republishes the original NATS notification.
It must never duplicate the claim policy: the claim endpoint and
``decide_reclaim_for_existing_claim`` arbitrate the reclaim.

These tests cover both the historical orphaned-/stranded-recovery contract
and the regression for the PFT v2 stall (execution 626611573817082718)
where ``fetch_mds_details:task_sequence`` commands sat in CLAIMED/RUNNING
on a dead worker and there was no active reaper to republish them.
"""

from __future__ import annotations

import pytest

import noetl.server.command_reaper as command_reaper


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.query = None
        self.params = None

    async def execute(self, query, params):
        self.query = query
        self.params = params

    async def fetchall(self):
        return self._rows


class _FakeCursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, row_factory=None):
        return _FakeCursorCtx(self._cursor)


class _FakeConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _patch_pool(monkeypatch, cursor):
    conn = _FakeConn(cursor)

    def _fake_get_bg_pool_connection(*_args, **_kwargs):
        return _FakeConnCtx(conn)

    monkeypatch.setattr(command_reaper, "get_bg_pool_connection", _fake_get_bg_pool_connection)


@pytest.mark.asyncio
async def test_find_stale_active_commands_scans_command_table_and_filters_terminal_executions(
    monkeypatch,
):
    rows = [
        {
            "event_id": 626615919199912327,
            "execution_id": 626611573817082718,
            "command_id": "626611573817082718:fetch_mds_details:0",
            "step": "fetch_mds_details",
        }
    ]
    cursor = _FakeCursor(rows)
    _patch_pool(monkeypatch, cursor)

    result = await command_reaper._find_stale_active_commands(
        stale_seconds=90.0,
        healthy_hard_timeout_seconds=1800.0,
        max_commands=50,
    )

    assert result == rows

    sql = cursor.query
    # Primary scan is against noetl.command, not the event log.
    assert "FROM noetl.command c" in sql
    # Heartbeat join with noetl.runtime worker pool.
    assert "LEFT JOIN noetl.runtime r" in sql
    assert "r.kind = 'worker_pool'" in sql
    # Status filter targets active non-terminal rows.
    assert "c.status = ANY(%s)" in sql
    # Stale worker / hard-timeout predicate.
    assert "r.heartbeat" in sql
    assert "c.claimed_at" in sql
    # Execution-terminal exclusion via noetl.event.
    assert "FROM noetl.event et" in sql
    assert "et.event_type = ANY(%s)" in sql
    # Bounded result set.
    assert "LIMIT %s" in sql

    assert cursor.params == (
        list(command_reaper._ACTIVE_COMMAND_STATUSES),
        90.0,
        1800.0,
        command_reaper._TERMINAL_EXECUTION_EVENT_TYPES,
        50,
    )


@pytest.mark.asyncio
async def test_find_stale_active_commands_returns_claimed_task_sequence_regression(
    monkeypatch,
):
    """Regression for PFT v2 execution 626611573817082718.

    The reaper must surface CLAIMED ``fetch_mds_details:task_sequence``
    rows so the existing claim policy can take them back when the
    notification is republished.
    """
    rows = [
        {
            "event_id": 626615919199912335,
            "execution_id": 626611573817082718,
            "command_id": "626611573817082718:fetch_mds_details:task_sequence:1",
            "step": "fetch_mds_details:task_sequence",
        },
        {
            "event_id": 626615919199912337,
            "execution_id": 626611573817082718,
            "command_id": "626611573817082718:fetch_mds_details:task_sequence:2",
            "step": "fetch_mds_details:task_sequence",
        },
        {
            "event_id": 626615919199912339,
            "execution_id": 626611573817082718,
            "command_id": "626611573817082718:fetch_mds_details:task_sequence:3",
            "step": "fetch_mds_details:task_sequence",
        },
    ]
    cursor = _FakeCursor(rows)
    _patch_pool(monkeypatch, cursor)

    result = await command_reaper._find_stale_active_commands(
        stale_seconds=60.0,
        healthy_hard_timeout_seconds=1800.0,
        max_commands=10,
    )

    assert [r["event_id"] for r in result] == [
        626615919199912335,
        626615919199912337,
        626615919199912339,
    ]
    assert {r["step"] for r in result} == {"fetch_mds_details:task_sequence"}


@pytest.mark.asyncio
async def test_find_stale_active_commands_returns_running_task_sequence_regression(
    monkeypatch,
):
    """Regression for the RUNNING leg of the same stall.

    Command 626615919199912327 was RUNNING on a worker that never emitted
    ``command.completed`` and never recovered. The reaper must surface it
    too — the CLAIMED filter alone is not enough.
    """
    rows = [
        {
            "event_id": 626615919199912327,
            "execution_id": 626611573817082718,
            "command_id": "626611573817082718:fetch_mds_details:task_sequence:0",
            "step": "fetch_mds_details:task_sequence",
        }
    ]
    cursor = _FakeCursor(rows)
    _patch_pool(monkeypatch, cursor)

    result = await command_reaper._find_stale_active_commands(
        stale_seconds=60.0,
        healthy_hard_timeout_seconds=1800.0,
        max_commands=10,
    )

    assert result == rows
    # Status filter must include both CLAIMED and RUNNING.
    assert "CLAIMED" in command_reaper._ACTIVE_COMMAND_STATUSES
    assert "RUNNING" in command_reaper._ACTIVE_COMMAND_STATUSES


@pytest.mark.asyncio
async def test_find_stranded_pending_commands_filters_non_pending_and_terminal_executions(
    monkeypatch,
):
    rows = [
        {
            "event_id": 700000000000000011,
            "execution_id": 700000000000000010,
            "command_id": "700000000000000010:start:0",
            "step": "start",
        }
    ]
    cursor = _FakeCursor(rows)
    _patch_pool(monkeypatch, cursor)

    result = await command_reaper._find_stranded_pending_commands(
        pending_retry_seconds=60.0,
        max_commands=25,
    )

    assert result == rows

    sql = cursor.query
    assert "FROM noetl.command c" in sql
    assert "c.status = 'PENDING'" in sql
    assert "c.created_at" in sql
    # Reaper must still exclude terminated executions.
    assert "FROM noetl.event et" in sql
    assert "et.event_type = ANY(%s)" in sql

    assert cursor.params == (
        60.0,
        command_reaper._TERMINAL_EXECUTION_EVENT_TYPES,
        25,
    )


@pytest.mark.asyncio
async def test_reap_orphaned_commands_once_republishes_orphaned_and_stranded(monkeypatch):
    orphaned = [
        {
            "event_id": 626615919199912327,
            "execution_id": 626611573817082718,
            "command_id": "626611573817082718:fetch_mds_details:task_sequence:0",
            "step": "fetch_mds_details:task_sequence",
        }
    ]
    stranded = [
        {
            "event_id": 700000000000000011,
            "execution_id": 700000000000000010,
            "command_id": "700000000000000010:start:0",
            "step": "start",
        }
    ]
    published = []

    class _Publisher:
        async def publish_command(self, **kwargs):
            published.append(kwargs)

    async def _fake_stale(**_kwargs):
        return orphaned

    async def _fake_stranded(**_kwargs):
        return stranded

    async def _fake_get_nats_publisher():
        return _Publisher()

    monkeypatch.setattr(command_reaper, "_find_stale_active_commands", _fake_stale)
    monkeypatch.setattr(command_reaper, "_find_stranded_pending_commands", _fake_stranded)
    monkeypatch.setattr(command_reaper, "_get_nats_publisher", _fake_get_nats_publisher)

    count = await command_reaper.reap_orphaned_commands_once(
        "http://server-noetl.noetl.svc.cluster.local:80"
    )

    assert count == 2
    assert [item["command_id"] for item in published] == [
        orphaned[0]["command_id"],
        stranded[0]["command_id"],
    ]
    # publish_command receives an int execution_id and event_id, str command_id+step.
    assert all(isinstance(item["execution_id"], int) for item in published)
    assert all(isinstance(item["event_id"], int) for item in published)
    assert all(isinstance(item["command_id"], str) for item in published)
    assert all(isinstance(item["step"], str) for item in published)


@pytest.mark.asyncio
async def test_reap_orphaned_commands_once_skips_stranded_query_when_capacity_is_exhausted(
    monkeypatch,
):
    orphaned = [
        {
            "event_id": i,
            "execution_id": i,
            "command_id": f"{i}:step:{i}",
            "step": "step",
        }
        for i in range(100)
    ]
    published = []

    class _Publisher:
        async def publish_command(self, **kwargs):
            published.append(kwargs)

    async def _fake_stale(**_kwargs):
        return orphaned

    async def _fake_stranded(**_kwargs):
        raise AssertionError("Stranded query should be skipped when no remaining capacity")

    async def _fake_get_nats_publisher():
        return _Publisher()

    monkeypatch.setattr(command_reaper, "_REAPER_MAX_PER_RUN", 100)
    monkeypatch.setattr(command_reaper, "_find_stale_active_commands", _fake_stale)
    monkeypatch.setattr(command_reaper, "_find_stranded_pending_commands", _fake_stranded)
    monkeypatch.setattr(command_reaper, "_get_nats_publisher", _fake_get_nats_publisher)

    count = await command_reaper.reap_orphaned_commands_once(
        "http://server-noetl.noetl.svc.cluster.local:80"
    )

    assert count == 100
    assert len(published) == 100


@pytest.mark.asyncio
async def test_reap_orphaned_commands_once_returns_zero_when_nothing_to_recover(monkeypatch):
    async def _fake_stale(**_kwargs):
        return []

    async def _fake_stranded(**_kwargs):
        return []

    async def _fake_get_nats_publisher():  # pragma: no cover - should not be called
        raise AssertionError("NATS publisher must not be acquired when nothing to recover")

    monkeypatch.setattr(command_reaper, "_find_stale_active_commands", _fake_stale)
    monkeypatch.setattr(command_reaper, "_find_stranded_pending_commands", _fake_stranded)
    monkeypatch.setattr(command_reaper, "_get_nats_publisher", _fake_get_nats_publisher)

    count = await command_reaper.reap_orphaned_commands_once(
        "http://server-noetl.noetl.svc.cluster.local:80"
    )

    assert count == 0


@pytest.mark.asyncio
async def test_reap_orphaned_commands_once_continues_on_publish_error(monkeypatch):
    """One bad command must not abort the rest of the sweep."""
    orphaned = [
        {"event_id": 1, "execution_id": 1, "command_id": "1:a:0", "step": "a"},
        {"event_id": 2, "execution_id": 1, "command_id": "1:b:0", "step": "b"},
    ]
    published = []

    class _Publisher:
        async def publish_command(self, **kwargs):
            if kwargs["command_id"] == "1:a:0":
                raise RuntimeError("transient NATS failure")
            published.append(kwargs)

    async def _fake_stale(**_kwargs):
        return orphaned

    async def _fake_stranded(**_kwargs):
        return []

    async def _fake_get_nats_publisher():
        return _Publisher()

    monkeypatch.setattr(command_reaper, "_find_stale_active_commands", _fake_stale)
    monkeypatch.setattr(command_reaper, "_find_stranded_pending_commands", _fake_stranded)
    monkeypatch.setattr(command_reaper, "_get_nats_publisher", _fake_get_nats_publisher)

    count = await command_reaper.reap_orphaned_commands_once(
        "http://server-noetl.noetl.svc.cluster.local:80"
    )

    assert count == 1
    assert [item["command_id"] for item in published] == ["1:b:0"]


@pytest.mark.asyncio
async def test_run_command_reaper_skips_work_when_lease_not_acquired(monkeypatch):
    """Only the lease holder should sweep; followers must idle."""

    class _Lease:
        def __init__(self):
            self.calls = 0
            self.released = False

        async def try_acquire_or_renew(self):
            self.calls += 1

            class _State:
                acquired = False

            return _State()

        async def release(self):
            self.released = True

    async def _fake_reap(_server_url):
        raise AssertionError("reap_orphaned_commands_once must not run without the lease")

    monkeypatch.setattr(command_reaper, "_REAPER_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(command_reaper, "_REAPER_ENABLED", True)
    monkeypatch.setattr(command_reaper, "reap_orphaned_commands_once", _fake_reap)

    import asyncio

    stop_event = asyncio.Event()
    lease = _Lease()
    task = asyncio.create_task(
        command_reaper.run_command_reaper(
            stop_event=stop_event,
            server_url="http://server",
            lease=lease,
        )
    )
    await asyncio.sleep(0.05)
    stop_event.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert lease.calls >= 1
    assert lease.released is True
