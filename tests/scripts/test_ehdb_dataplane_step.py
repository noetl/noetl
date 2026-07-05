"""Tests for the Phase C data-plane smoke + worker/playbook-local step CLI.

Both exercise the real ``ehdb-local-reference`` binary when it is discoverable
(built locally / bundled in the kind image) and skip otherwise, so the state
roundtrip is genuine.
"""

import json

import pytest

from noetl.core.ehdb_adapter import discover_ehdb_helper_executable
from scripts.ehdb_dataplane_step import main as step_main
from scripts.smoke_ehdb_dataplane import run_smoke


def _binary_or_skip() -> str:
    binary = discover_ehdb_helper_executable({"PATH": ""})
    if binary is None:
        pytest.skip("ehdb-local-reference binary not built/discoverable")
    return binary


def test_run_smoke_appends_and_reads_back(tmp_path):
    binary = _binary_or_skip()
    payload = run_smoke(
        helper_bin=binary,
        log_path=tmp_path / "ehdb.jsonl",
        env={"PATH": "/usr/bin"},
    )
    assert payload["append_first"]["append"]["sequence"] == 1
    assert payload["append_second"]["append"]["sequence"] == 2
    assert payload["read"]["read"]["record_count"] == 2


def test_step_append_then_read(tmp_path, capsys, monkeypatch):
    binary = _binary_or_skip()
    log = str(tmp_path / "ehdb.jsonl")
    monkeypatch.setenv("NOETL_EHDB_ENABLED", "true")
    monkeypatch.setenv("NOETL_EHDB_MODE", "local_reference")
    monkeypatch.setenv("NOETL_EHDB_CLIENT_ROLE", "worker")
    monkeypatch.setenv("NOETL_EHDB_LOCAL_REFERENCE_LOG", log)
    monkeypatch.setenv("NOETL_EHDB_HELPER_BIN", binary)

    code = step_main(["append", "--stream", "trips", "--subject", "trips.made", "--payload", '{"x":1}'])
    assert code == 0
    appended = json.loads(capsys.readouterr().out)
    assert appended["outcome"] == "appended"
    assert appended["append"]["sequence"] == 1

    code = step_main(["read", "--stream", "trips"])
    assert code == 0
    read = json.loads(capsys.readouterr().out)
    assert read["outcome"] == "read"
    assert read["read"]["records"][0]["payload"] == '{"x":1}'


def test_step_disabled_is_noop_exit_zero(capsys, monkeypatch):
    # No EHDB env → disabled no-op, exit 0, no binary needed.
    for key in (
        "NOETL_EHDB_ENABLED",
        "NOETL_EHDB_MODE",
        "NOETL_EHDB_CLIENT_ROLE",
        "NOETL_EHDB_LOCAL_REFERENCE_LOG",
    ):
        monkeypatch.delenv(key, raising=False)
    code = step_main(["read", "--stream", "trips"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "disabled"


def test_step_control_plane_guard_exit_four(capsys, monkeypatch):
    monkeypatch.setenv("NOETL_EHDB_ENABLED", "true")
    monkeypatch.setenv("NOETL_EHDB_MODE", "control_plane")
    monkeypatch.setenv("NOETL_EHDB_CLIENT_ROLE", "gateway")
    code = step_main(["append", "--stream", "s", "--subject", "s.e", "--payload", "x"])
    assert code == 4
    assert json.loads(capsys.readouterr().out)["outcome"] == "guard_refused"
