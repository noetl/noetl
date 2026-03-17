from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import noetl.server.api.v2 as v2_api


def _clear_cache() -> None:
    v2_api._active_claim_cache_by_event.clear()
    v2_api._active_claim_cache_by_command.clear()
    v2_api._active_claim_cache_last_prune_monotonic = 0.0


@pytest.mark.asyncio
async def test_claim_command_uses_cache_fast_path_without_db(monkeypatch):
    _clear_cache()
    v2_api._active_claim_cache_set(77, "cmd-77", "worker-a")

    def _unexpected_get_pool_connection(*_args, **_kwargs):
        raise AssertionError("DB should not be called when cache fast-path applies")

    monkeypatch.setattr(v2_api, "get_pool_connection", _unexpected_get_pool_connection)

    with pytest.raises(HTTPException) as exc:
        await v2_api.claim_command(77, v2_api.ClaimRequest(worker_id="worker-b"))

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "active_claim"
    assert exc.value.detail["claim_policy"] == "cache_fast_path"
    assert exc.value.detail["worker_id"] == "worker-a"
    assert exc.value.headers["Retry-After"] == str(max(1, v2_api._CLAIM_ACTIVE_RETRY_AFTER_SECONDS))
    _clear_cache()


@pytest.mark.asyncio
async def test_handle_event_invalidates_claim_cache_on_terminal_event(monkeypatch):
    _clear_cache()
    v2_api._active_claim_cache_set(91, "cmd-91", "worker-a")

    class _CursorCtx:
        def __init__(self, cursor):
            self._cursor = cursor

        async def __aenter__(self):
            return self._cursor

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Cursor:
        async def execute(self, *_args, **_kwargs):
            return None

        async def fetchone(self):
            return {"catalog_id": 10}

    class _Conn:
        def cursor(self, row_factory=None):
            return _CursorCtx(_Cursor())

        async def commit(self):
            return None

    class _ConnCtx:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        state_store = SimpleNamespace(evict_completed=lambda *_args, **_kwargs: None)

        async def handle_event(self, *_args, **_kwargs):
            return []

    class _Publisher:
        async def publish_command(self, **_kwargs):
            raise AssertionError("No command publications expected for terminal event")

    async def _next_snowflake_id(_cur):
        return 101

    def _get_pool_connection(*_args, **_kwargs):
        return _ConnCtx()

    async def _get_nats_publisher():
        return _Publisher()

    monkeypatch.setattr(v2_api, "get_pool_connection", _get_pool_connection)
    monkeypatch.setattr(v2_api, "_next_snowflake_id", _next_snowflake_id)
    monkeypatch.setattr(v2_api, "get_engine", lambda: _Engine())
    monkeypatch.setattr(v2_api, "get_nats_publisher", _get_nats_publisher)

    req = v2_api.EventRequest(
        execution_id="42",
        step="end",
        name="command.completed",
        payload={"command_id": "cmd-91"},
        meta={"command_id": "cmd-91"},
        worker_id="worker-a",
    )

    response = await v2_api.handle_event(req)

    assert response.status == "ok"
    assert response.event_id == 101
    assert "cmd-91" not in v2_api._active_claim_cache_by_command
    assert 91 not in v2_api._active_claim_cache_by_event
    _clear_cache()


def test_active_claim_cache_set_replaces_old_links():
    _clear_cache()
    v2_api._active_claim_cache_set(1, "cmd-1", "worker-a")
    v2_api._active_claim_cache_set(1, "cmd-2", "worker-b")
    assert "cmd-1" not in v2_api._active_claim_cache_by_command
    assert v2_api._active_claim_cache_by_event[1].command_id == "cmd-2"

    v2_api._active_claim_cache_set(2, "cmd-2", "worker-c")
    assert 1 not in v2_api._active_claim_cache_by_event
    assert v2_api._active_claim_cache_by_command["cmd-2"].event_id == 2
    _clear_cache()


def test_active_claim_cache_invalidate_command_id_preserves_remapped_event_entry():
    _clear_cache()
    now = 100.0
    old_entry = v2_api._ActiveClaimCacheEntry(
        event_id=33,
        command_id="cmd-old",
        worker_id="worker-a",
        expires_at_monotonic=now + 30.0,
        updated_at_monotonic=now,
    )
    new_entry = v2_api._ActiveClaimCacheEntry(
        event_id=33,
        command_id="cmd-new",
        worker_id="worker-b",
        expires_at_monotonic=now + 30.0,
        updated_at_monotonic=now + 1.0,
    )
    v2_api._active_claim_cache_by_event[33] = new_entry
    v2_api._active_claim_cache_by_command["cmd-old"] = old_entry
    v2_api._active_claim_cache_by_command["cmd-new"] = new_entry

    v2_api._active_claim_cache_invalidate(command_id="cmd-old")

    assert 33 in v2_api._active_claim_cache_by_event
    assert v2_api._active_claim_cache_by_event[33] is new_entry
    assert "cmd-old" not in v2_api._active_claim_cache_by_command
    assert v2_api._active_claim_cache_by_command["cmd-new"] is new_entry
    _clear_cache()


def test_active_claim_cache_get_drops_expired_entry_even_between_prune_cycles(monkeypatch):
    _clear_cache()
    v2_api._active_claim_cache_set(44, "cmd-44", "worker-a")
    cached = v2_api._active_claim_cache_by_event[44]

    # Simulate entry expiry while prune cadence would otherwise defer a full scan.
    monkeypatch.setattr(v2_api, "_ACTIVE_CLAIMS_CACHE_PRUNE_INTERVAL_SECONDS", 600.0)
    cached.expires_at_monotonic = 1.0
    monkeypatch.setattr(v2_api.time, "monotonic", lambda: 5.0)

    assert v2_api._active_claim_cache_get(44) is None
    assert 44 not in v2_api._active_claim_cache_by_event
    assert "cmd-44" not in v2_api._active_claim_cache_by_command
    _clear_cache()
