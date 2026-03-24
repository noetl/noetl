from datetime import datetime, timedelta, timezone

import pytest

import noetl.server.auto_resume as auto_resume


@pytest.mark.asyncio
async def test_wait_for_dependencies_ready_retries_until_healthy(monkeypatch):
    monkeypatch.setattr(auto_resume, "_AUTO_RESUME_READINESS_TIMEOUT_SECONDS", 3.0)
    monkeypatch.setattr(auto_resume, "_AUTO_RESUME_READINESS_POLL_SECONDS", 1.0)

    attempts = {"count": 0}

    async def _fake_check():
        attempts["count"] += 1
        if attempts["count"] < 3:
            return False, {"postgres": "down", "nats": "down", "workers": "0"}
        return True, {"postgres": "ok", "nats": "ok", "workers": "1"}

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr(auto_resume, "_check_recovery_dependencies", _fake_check)
    monkeypatch.setattr(auto_resume.asyncio, "sleep", _fake_sleep)

    ready = await auto_resume._wait_for_dependencies_ready()
    assert ready is True
    assert attempts["count"] == 3
    assert sleep_calls == [1.0, 1.0]


@pytest.mark.asyncio
async def test_recover_interrupted_parent_execution_restart_mode(monkeypatch):
    candidate = {
        "execution_id": 42,
        "path": "tests/fixtures/playbooks/hello_world/hello_world",
        "catalog_id": 99,
        "result": {"kind": "data", "data": {"result": {"workload": {"a": 1}}}},
        "created_at": "2026-03-05T00:00:00Z",
    }
    monkeypatch.setattr(auto_resume, "get_recovery_candidates", lambda: _async_value([candidate]))
    monkeypatch.setattr(auto_resume, "get_execution_status", lambda _eid: _async_value("running"))
    monkeypatch.setattr(auto_resume, "_restart_execution", lambda _cand: _async_value("84"))

    calls = []

    async def _fake_mark(exec_id, reason, meta_extra=None, payload_extra=None):
        calls.append(
            {
                "exec_id": exec_id,
                "reason": reason,
                "meta_extra": meta_extra,
                "payload_extra": payload_extra,
            }
        )
        return True

    monkeypatch.setattr(auto_resume, "mark_execution_cancelled", _fake_mark)

    await auto_resume._recover_interrupted_parent_executions(mode="restart")

    assert len(calls) == 1
    assert calls[0]["exec_id"] == 42
    assert calls[0]["meta_extra"]["restarted_execution_id"] == "84"
    assert calls[0]["payload_extra"]["restarted_execution_id"] == "84"


@pytest.mark.asyncio
async def test_recover_interrupted_parent_execution_cancel_mode(monkeypatch):
    candidate = {
        "execution_id": 100,
        "path": "tests/fixtures/playbooks/hello_world/hello_world",
        "catalog_id": 1,
        "result": {},
        "created_at": "2026-03-05T00:00:00Z",
    }
    monkeypatch.setattr(auto_resume, "get_recovery_candidates", lambda: _async_value([candidate]))
    monkeypatch.setattr(auto_resume, "get_execution_status", lambda _eid: _async_value("running"))

    restarted = {"called": 0}

    async def _fake_restart(_candidate):
        restarted["called"] += 1
        return "new-id"

    monkeypatch.setattr(auto_resume, "_restart_execution", _fake_restart)

    cancelled = {"called": 0}

    async def _fake_mark(*_args, **_kwargs):
        cancelled["called"] += 1
        return True

    monkeypatch.setattr(auto_resume, "mark_execution_cancelled", _fake_mark)

    await auto_resume._recover_interrupted_parent_executions(mode="cancel")

    assert restarted["called"] == 0
    assert cancelled["called"] == 1


@pytest.mark.asyncio
async def test_recover_interrupted_parent_execution_skips_fresh_and_recovers_stale(monkeypatch):
    fresh_candidate = {
        "execution_id": 100,
        "path": "fresh",
        "catalog_id": 1,
        "result": {},
        "created_at": "2026-03-24T20:48:11Z",
        "latest_event_at": "2026-03-24T20:48:14Z",
        "latest_event_type": "command.issued",
    }
    stale_candidate = {
        "execution_id": 101,
        "path": "stale",
        "catalog_id": 1,
        "result": {},
        "created_at": "2026-03-24T20:00:00Z",
        "latest_event_at": "2026-03-24T20:05:00Z",
        "latest_event_type": "command.started",
    }
    monkeypatch.setattr(auto_resume, "_AUTO_RESUME_MAX_CANDIDATES", 1)
    monkeypatch.setattr(auto_resume, "_AUTO_RESUME_MIN_STALE_SECONDS", 180.0)
    monkeypatch.setattr(
        auto_resume,
        "get_recovery_candidates",
        lambda: _async_value([fresh_candidate, stale_candidate]),
    )
    monkeypatch.setattr(auto_resume, "get_execution_status", lambda _eid: _async_value("running"))
    monkeypatch.setattr(auto_resume, "_restart_execution", lambda _cand: _async_value("202"))

    cancelled = []

    async def _fake_mark(exec_id, reason, meta_extra=None, payload_extra=None):
        cancelled.append(exec_id)
        return True

    monkeypatch.setattr(auto_resume, "mark_execution_cancelled", _fake_mark)

    await auto_resume._recover_interrupted_parent_executions(mode="restart")

    assert cancelled == [101]


def test_should_recover_candidate_skips_pending_only_command_issued(monkeypatch):
    monkeypatch.setattr(auto_resume, "_AUTO_RESUME_MIN_STALE_SECONDS", 0.0)
    candidate = {
        "created_at": "2026-03-24T20:48:11Z",
        "latest_event_at": "2026-03-24T20:48:14Z",
        "latest_event_type": "command.issued",
    }

    should_recover = auto_resume._should_recover_candidate(
        candidate,
        now=datetime(2026, 3, 24, 21, 0, 0, tzinfo=timezone.utc),
    )

    assert should_recover is False


def test_should_recover_candidate_skips_recent_inflight_execution(monkeypatch):
    monkeypatch.setattr(auto_resume, "_AUTO_RESUME_MIN_STALE_SECONDS", 180.0)
    now = datetime(2026, 3, 24, 21, 0, 0, tzinfo=timezone.utc)
    candidate = {
        "created_at": (now - timedelta(seconds=120)).isoformat(),
        "latest_event_at": (now - timedelta(seconds=90)).isoformat(),
        "latest_event_type": "command.started",
    }

    should_recover = auto_resume._should_recover_candidate(candidate, now=now)

    assert should_recover is False


def test_should_recover_candidate_allows_stale_inflight_execution(monkeypatch):
    monkeypatch.setattr(auto_resume, "_AUTO_RESUME_MIN_STALE_SECONDS", 180.0)
    now = datetime(2026, 3, 24, 21, 0, 0, tzinfo=timezone.utc)
    candidate = {
        "created_at": (now - timedelta(minutes=10)).isoformat(),
        "latest_event_at": (now - timedelta(minutes=5)).isoformat(),
        "latest_event_type": "command.started",
    }

    should_recover = auto_resume._should_recover_candidate(candidate, now=now)

    assert should_recover is True


async def _async_value(value):
    return value
