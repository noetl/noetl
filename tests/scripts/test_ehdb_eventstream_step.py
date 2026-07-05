"""Tests for the Phase D event-stream smoke + worker/playbook-local step CLI.

Both exercise the real ``ehdb-local-reference`` binary when it is discoverable
(built locally / bundled in the kind image) and skip otherwise, so the durable
drain roundtrip is genuine.
"""

import json

import pytest

from noetl.core.ehdb_adapter import discover_ehdb_helper_executable
from scripts.ehdb_eventstream_step import main as step_main
from scripts.smoke_ehdb_eventstream import run_smoke


def _binary_or_skip() -> str:
    binary = discover_ehdb_helper_executable({"PATH": ""})
    if binary is None:
        pytest.skip("ehdb-local-reference binary not built/discoverable")
    return binary


def test_run_smoke_drains_durable_consumer(tmp_path):
    binary = _binary_or_skip()
    payload = run_smoke(
        helper_bin=binary,
        log_path=tmp_path / "ehdb.jsonl",
        env={"PATH": "/usr/bin"},
    )
    assert payload["project_first"]["project"]["sequence"] == 1
    assert payload["project_second"]["project"]["sequence"] == 2
    assert payload["consume"]["consume"]["pending_count"] == 2
    assert payload["ack"]["ack"]["acked_sequence"] == 1
    assert payload["reconsume"]["consume"]["pending_count"] == 1


def _enable(monkeypatch, binary, log):
    monkeypatch.setenv("NOETL_EHDB_ENABLED", "true")
    monkeypatch.setenv("NOETL_EHDB_MODE", "local_reference")
    monkeypatch.setenv("NOETL_EHDB_CLIENT_ROLE", "worker")
    monkeypatch.setenv("NOETL_EHDB_LOCAL_REFERENCE_LOG", log)
    monkeypatch.setenv("NOETL_EHDB_HELPER_BIN", binary)


def test_step_project_consume_ack(tmp_path, capsys, monkeypatch):
    binary = _binary_or_skip()
    _enable(monkeypatch, binary, str(tmp_path / "ehdb.jsonl"))

    code = step_main(["project", "--stream", "trips", "--subject", "trips.made", "--payload", '{"x":1}'])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "projected"

    code = step_main(["consume", "--stream", "trips", "--consumer", "mat"])
    assert code == 0
    consumed = json.loads(capsys.readouterr().out)
    assert consumed["outcome"] == "consumed"
    assert consumed["consume"]["pending_count"] == 1

    code = step_main(["ack", "--stream", "trips", "--consumer", "mat", "--sequence", "1"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "acked"


def test_step_disabled_is_noop_exit_zero(capsys, monkeypatch):
    for key in (
        "NOETL_EHDB_ENABLED",
        "NOETL_EHDB_MODE",
        "NOETL_EHDB_CLIENT_ROLE",
        "NOETL_EHDB_LOCAL_REFERENCE_LOG",
    ):
        monkeypatch.delenv(key, raising=False)
    code = step_main(["consume", "--stream", "trips", "--consumer", "mat"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "disabled"


def test_step_control_plane_guard_exit_four(capsys, monkeypatch):
    monkeypatch.setenv("NOETL_EHDB_ENABLED", "true")
    monkeypatch.setenv("NOETL_EHDB_MODE", "control_plane")
    monkeypatch.setenv("NOETL_EHDB_CLIENT_ROLE", "gateway")
    code = step_main(["project", "--stream", "s", "--subject", "s.e", "--payload", "x"])
    assert code == 4
    assert json.loads(capsys.readouterr().out)["outcome"] == "guard_refused"
