import importlib.util
import sys
from pathlib import Path

import pytest

from noetl.core.ehdb_adapter import (
    EHDB_HELPER_BIN_ENV,
    EHDB_LOCAL_REFERENCE_SUMMARY_FIELDS,
)
from noetl.core.ehdb_contract import (
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_LOCAL_REFERENCE_LOG_ENV,
    EHDB_MODE_ENV,
    EhdbClientRole,
)
from noetl.core.ehdb_readiness import (
    EHDB_READINESS_TIMEOUT_ENV,
    EhdbControlPlaneGuardError,
    EhdbReadinessOutcome,
    assert_data_plane_read_allowed,
    evaluate_ehdb_readiness,
    render_ehdb_readiness_metrics,
    reset_ehdb_readiness_metrics,
)


@pytest.fixture(autouse=True)
def _clean_metrics():
    reset_ehdb_readiness_metrics()
    yield
    reset_ehdb_readiness_metrics()


# --------------------------------------------------------------------------
# Disabled = strict no-op (byte-identical behaviour)
# --------------------------------------------------------------------------


def test_disabled_is_noop_and_records_no_metrics():
    result = evaluate_ehdb_readiness({})

    assert result.outcome is EhdbReadinessOutcome.DISABLED
    assert result.ready is True
    assert result.degraded is False
    assert result.performed_read is False
    assert result.counts == {}
    # No metric recorded → /metrics render is empty (byte-identical).
    assert render_ehdb_readiness_metrics() == []


def test_disabled_ignores_role_and_log_env():
    result = evaluate_ehdb_readiness(
        {
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/should-not-be-read.jsonl",
        }
    )

    assert result.outcome is EhdbReadinessOutcome.DISABLED
    assert render_ehdb_readiness_metrics() == []


# --------------------------------------------------------------------------
# Enabled worker/playbook local-reference read
# --------------------------------------------------------------------------


def test_enabled_worker_reads_bounded_summary(tmp_path):
    log_path = tmp_path / "ehdb.jsonl"
    log_path.write_text("", encoding="utf-8")
    helper = _summary_helper(tmp_path, transaction_count=3)

    result = evaluate_ehdb_readiness(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
            EHDB_HELPER_BIN_ENV: str(helper),
            "PATH": "/usr/bin",
        }
    )

    assert result.outcome is EhdbReadinessOutcome.READY
    assert result.ready is True
    assert result.performed_read is True
    assert result.role is EhdbClientRole.WORKER
    assert result.counts["transaction_count"] == 3
    assert result.log_path == str(log_path)


def test_enabled_playbook_empty_summary_reports_empty(tmp_path):
    log_path = tmp_path / "ehdb.jsonl"
    log_path.write_text("", encoding="utf-8")
    helper = _summary_helper(tmp_path, transaction_count=0)

    result = evaluate_ehdb_readiness(
        {
            EHDB_ENABLED_ENV: "1",
            EHDB_MODE_ENV: "local_reference",
            EHDB_CLIENT_ROLE_ENV: "playbook",
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
            EHDB_HELPER_BIN_ENV: str(helper),
            "PATH": "/usr/bin",
        }
    )

    assert result.outcome is EhdbReadinessOutcome.EMPTY
    assert result.ready is True
    assert result.role is EhdbClientRole.PLAYBOOK
    assert all(value == 0 for value in result.counts.values())


def test_enabled_system_role_reads_summary(tmp_path):
    log_path = tmp_path / "ehdb.jsonl"
    log_path.write_text("", encoding="utf-8")
    helper = _summary_helper(tmp_path, transaction_count=2)

    result = evaluate_ehdb_readiness(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "system",
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
            EHDB_HELPER_BIN_ENV: str(helper),
            "PATH": "/usr/bin",
        }
    )

    assert result.outcome is EhdbReadinessOutcome.READY
    assert result.role is EhdbClientRole.SYSTEM


# --------------------------------------------------------------------------
# Control-plane roles never perform a data-plane read
# --------------------------------------------------------------------------


def test_control_plane_role_performs_no_read():
    result = evaluate_ehdb_readiness(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "control_plane",
            EHDB_CLIENT_ROLE_ENV: "gateway",
        }
    )

    assert result.outcome is EhdbReadinessOutcome.CONTROL_PLANE
    assert result.ready is True
    assert result.performed_read is False
    assert result.role is EhdbClientRole.GATEWAY
    assert result.log_path is None


@pytest.mark.parametrize("role", ["gateway", "api", "server"])
def test_control_plane_role_given_dataplane_env_is_guarded(role, tmp_path):
    log_path = tmp_path / "ehdb.jsonl"
    log_path.write_text("", encoding="utf-8")

    result = evaluate_ehdb_readiness(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "local_reference",
            EHDB_CLIENT_ROLE_ENV: role,
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
            EHDB_HELPER_BIN_ENV: "/should/never/run",
        }
    )

    assert result.outcome is EhdbReadinessOutcome.GUARD_REFUSED
    assert result.ready is False
    assert result.performed_read is False


def test_assert_data_plane_read_allowed_refuses_control_plane():
    for role in (EhdbClientRole.GATEWAY, EhdbClientRole.API, EhdbClientRole.SERVER):
        with pytest.raises(EhdbControlPlaneGuardError):
            assert_data_plane_read_allowed(role)


def test_assert_data_plane_read_allowed_permits_data_plane():
    for role in (EhdbClientRole.WORKER, EhdbClientRole.PLAYBOOK, EhdbClientRole.SYSTEM):
        assert_data_plane_read_allowed(role) is None


# --------------------------------------------------------------------------
# Degraded / invalid outcomes
# --------------------------------------------------------------------------


def test_missing_helper_is_unavailable(tmp_path):
    log_path = tmp_path / "ehdb.jsonl"
    log_path.write_text("", encoding="utf-8")

    result = evaluate_ehdb_readiness(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
            EHDB_HELPER_BIN_ENV: str(tmp_path / "does-not-exist"),
            "PATH": "",
        }
    )

    assert result.outcome is EhdbReadinessOutcome.UNAVAILABLE
    assert result.ready is True
    assert result.degraded is True


def test_slow_helper_trips_bounded_timeout(tmp_path):
    log_path = tmp_path / "ehdb.jsonl"
    log_path.write_text("", encoding="utf-8")
    helper = _helper_script(tmp_path, "import time\ntime.sleep(2)\n")

    result = evaluate_ehdb_readiness(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
            EHDB_HELPER_BIN_ENV: str(helper),
            EHDB_READINESS_TIMEOUT_ENV: "0.1",
            "PATH": "/usr/bin",
        }
    )

    assert result.outcome is EhdbReadinessOutcome.TRUNCATED
    assert result.degraded is True


def test_invalid_mode_is_invalid_outcome():
    result = evaluate_ehdb_readiness(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "not-a-real-mode",
            EHDB_CLIENT_ROLE_ENV: "worker",
        }
    )

    assert result.outcome is EhdbReadinessOutcome.INVALID
    assert result.ready is False


# --------------------------------------------------------------------------
# Metrics + timeout clamping
# --------------------------------------------------------------------------


def test_metrics_render_after_enabled_check(tmp_path):
    log_path = tmp_path / "ehdb.jsonl"
    log_path.write_text("", encoding="utf-8")
    helper = _summary_helper(tmp_path, transaction_count=1)

    evaluate_ehdb_readiness(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
            EHDB_HELPER_BIN_ENV: str(helper),
            "PATH": "/usr/bin",
        }
    )

    lines = render_ehdb_readiness_metrics(labels={"worker_id": "w-1"})
    text = "\n".join(lines)
    assert 'noetl_ehdb_readiness_checks_total{outcome="ready",worker_id="w-1"} 1' in text
    assert 'noetl_ehdb_readiness_ready{worker_id="w-1"} 1' in text
    # No secret values / log path leak into metric text.
    assert str(log_path) not in text


def test_timeout_env_is_clamped(tmp_path):
    # A huge configured timeout is clamped; the helper still returns quickly.
    log_path = tmp_path / "ehdb.jsonl"
    log_path.write_text("", encoding="utf-8")
    helper = _summary_helper(tmp_path, transaction_count=1)

    result = evaluate_ehdb_readiness(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
            EHDB_HELPER_BIN_ENV: str(helper),
            EHDB_READINESS_TIMEOUT_ENV: "9999",
            "PATH": "/usr/bin",
        }
    )

    assert result.outcome is EhdbReadinessOutcome.READY


# --------------------------------------------------------------------------
# Preflight CLI exit codes
# --------------------------------------------------------------------------


def _load_preflight_module():
    path = (
        Path(__file__).resolve().parents[2] / "scripts" / "ehdb_readiness_preflight.py"
    )
    spec = importlib.util.spec_from_file_location("ehdb_readiness_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preflight_cli_disabled_exit_zero(monkeypatch, capsys):
    monkeypatch.delenv(EHDB_ENABLED_ENV, raising=False)
    module = _load_preflight_module()

    assert module.main([]) == 0
    assert '"outcome": "disabled"' in capsys.readouterr().out


def test_preflight_cli_guard_exit_four(monkeypatch, tmp_path):
    log_path = tmp_path / "ehdb.jsonl"
    log_path.write_text("", encoding="utf-8")
    monkeypatch.setenv(EHDB_ENABLED_ENV, "true")
    monkeypatch.setenv(EHDB_MODE_ENV, "local_reference")
    monkeypatch.setenv(EHDB_CLIENT_ROLE_ENV, "gateway")
    monkeypatch.setenv(EHDB_LOCAL_REFERENCE_LOG_ENV, str(log_path))
    module = _load_preflight_module()

    assert module.main([]) == 4


# --------------------------------------------------------------------------
# Helpers (mirror tests/core/test_ehdb_adapter.py)
# --------------------------------------------------------------------------


def _helper_script(tmp_path: Path, body: str, *, name: str = "ehdb-helper.py") -> Path:
    helper = tmp_path / name
    helper.write_text(f"#!{sys.executable}\n{body.lstrip()}", encoding="utf-8")
    helper.chmod(0o755)
    return helper


def _summary_helper(tmp_path: Path, *, transaction_count: int) -> Path:
    payload = {
        field: 0
        for field in EHDB_LOCAL_REFERENCE_SUMMARY_FIELDS
        if field != "log_path"
    }
    payload["transaction_count"] = transaction_count
    return _helper_script(
        tmp_path,
        f"""
import json
import sys

payload = {payload!r}
payload["log_path"] = sys.argv[3]
print(json.dumps(payload))
""",
    )
