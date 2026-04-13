import time

import pytest
from fastapi import HTTPException

import noetl.server.api.core as v2_api


def _reset_outage_state() -> None:
    v2_api._db_unavailable_failure_streak = 0
    v2_api._db_unavailable_backoff_until_monotonic = 0.0


class _FailConnCtx:
    async def __aenter__(self):
        raise RuntimeError("server conn crashed?")

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_claim_command_short_circuits_when_db_backoff_active(monkeypatch):
    _reset_outage_state()
    v2_api._db_unavailable_failure_streak = 2
    v2_api._db_unavailable_backoff_until_monotonic = time.monotonic() + 5.0

    def _unexpected_get_pool_connection(*_args, **_kwargs):
        raise AssertionError("DB access should be short-circuited during outage backoff")

    monkeypatch.setattr(v2_api, "get_pool_connection", _unexpected_get_pool_connection)

    with pytest.raises(HTTPException) as exc:
        await v2_api.claim_command(101, v2_api.ClaimRequest(worker_id="worker-a"))

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "db_unavailable"
    assert int(exc.value.headers["Retry-After"]) >= 1
    _reset_outage_state()


@pytest.mark.asyncio
async def test_claim_command_maps_db_outage_errors_to_503(monkeypatch):
    _reset_outage_state()

    def _fail_get_pool_connection(*_args, **_kwargs):
        return _FailConnCtx()

    monkeypatch.setattr(v2_api, "get_pool_connection", _fail_get_pool_connection)

    with pytest.raises(HTTPException) as exc:
        await v2_api.claim_command(102, v2_api.ClaimRequest(worker_id="worker-a"))

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "db_unavailable"
    assert int(exc.value.headers["Retry-After"]) >= 1
    assert v2_api._db_unavailable_failure_streak >= 1
    _reset_outage_state()


@pytest.mark.asyncio
async def test_handle_event_maps_db_outage_errors_to_503(monkeypatch):
    _reset_outage_state()

    def _fail_get_pool_connection(*_args, **_kwargs):
        return _FailConnCtx()

    monkeypatch.setattr(v2_api, "get_pool_connection", _fail_get_pool_connection)

    req = v2_api.EventRequest(
        execution_id = "42",
        step="step-a",
        name="call.done",
        payload={"status": "ok"},
    )

    with pytest.raises(HTTPException) as exc:
        await v2_api.handle_event(req)

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "db_unavailable"
    assert int(exc.value.headers["Retry-After"]) >= 1
    _reset_outage_state()
