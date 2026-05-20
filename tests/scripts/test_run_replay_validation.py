import json
from pathlib import Path

from scripts import run_replay_validation


def test_run_replay_validation_fetches_and_runs_selected_gates(monkeypatch, tmp_path: Path, capsys):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)
    live_path = tmp_path / "live.json"
    live_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))

    assert (
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--tenant-id",
                "tenant-a",
                "--organization-id",
                "org-a",
                "--resolve-payloads",
                "--live-checksums",
                str(live_path),
                "--output-dir",
                str(tmp_path / "reports"),
                "--report-output",
                str(tmp_path / "reports" / "manifest.json"),
            ]
        )
        == 0
    )

    assert len(calls) == 4
    assert "scripts/fetch_replay_state_report.py" in calls[0]
    assert "--resolve-payloads" in calls[0]
    assert "scripts/check_replay_state_report.py" in calls[1]
    assert "scripts/check_replay_parity_report.py" in calls[2]
    assert "scripts/check_replay_payload_resolution_report.py" in calls[3]
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["replay"].endswith("replay-123.json")
    assert output["config"]["execution_id"] == 123
    assert output["steps"][0]["stdout_json"] == {"ok": True}
    assert output["steps"][0]["duration_seconds"] == 0.01
    manifest_path = tmp_path / "reports" / "manifest.json"
    assert json.loads(manifest_path.read_text())["matched"] is True


def test_run_replay_validation_stops_on_gate_failure(monkeypatch, tmp_path: Path, capsys):
    def _run(command):
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("{}")
            return 0, "", "", 0.01
        return 1, "", "failed", 0.02

    monkeypatch.setattr(run_replay_validation, "_run", _run)
    live_path = tmp_path / "live.json"
    live_path.write_text("{}")

    assert (
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--live-checksums",
                str(live_path),
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 1
    )
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    assert output["steps"][-1]["stderr"] == "failed"
    assert output["steps"][-1]["duration_seconds"] == 0.02


def test_run_replay_validation_builds_live_checksums_from_rows(monkeypatch, tmp_path: Path, capsys):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        if any(str(part).endswith("build_live_projection_checksums.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)
    live_rows_path = tmp_path / "live-rows.json"
    live_rows_path.write_text(json.dumps({"execution": []}))

    assert (
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--live-rows",
                str(live_rows_path),
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )

    assert any("scripts/build_live_projection_checksums.py" in call for call in calls)
    assert any("live-checksums-123.json" in str(part) for call in calls for part in call)
    output = json.loads(capsys.readouterr().out)
    assert output["config"]["live_rows"] == str(live_rows_path)


def test_run_replay_validation_rejects_multiple_cutoffs(tmp_path: Path):
    try:
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--as-of-event-id",
                "1",
                "--as-of-position",
                "1",
                "--output-dir",
                str(tmp_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")


def test_run_replay_validation_rejects_multiple_live_inputs(tmp_path: Path):
    try:
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--live-checksums",
                str(tmp_path / "live-checksums.json"),
                "--live-rows",
                str(tmp_path / "live-rows.json"),
                "--output-dir",
                str(tmp_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")


def test_run_replay_validation_fails_when_fetch_does_not_write_report(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    def _run(_command):
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)

    assert (
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 1
    )
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    assert output["steps"][-1]["name"] == "fetch_artifact"
