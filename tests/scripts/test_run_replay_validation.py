import json
from pathlib import Path

from scripts import run_replay_validation


def test_run_replay_validation_fetches_and_runs_selected_gates(monkeypatch, tmp_path: Path, capsys):
    calls = []

    def _run(command):
        calls.append(command)
        if "fetch_replay_state_report.py" in command:
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        return 0, json.dumps({"ok": True}), ""

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
            ]
        )
        == 0
    )

    assert len(calls) == 3
    assert "scripts/fetch_replay_state_report.py" in calls[0]
    assert "--resolve-payloads" in calls[0]
    assert "scripts/check_replay_parity_report.py" in calls[1]
    assert "scripts/check_replay_payload_resolution_report.py" in calls[2]
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["replay"].endswith("replay-123.json")


def test_run_replay_validation_stops_on_gate_failure(monkeypatch, tmp_path: Path, capsys):
    def _run(command):
        if "fetch_replay_state_report.py" in command:
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("{}")
            return 0, "", ""
        return 1, "", "failed"

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
