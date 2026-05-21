import json
from pathlib import Path

from scripts import run_projector_phase2_validation


def test_run_projector_phase2_validation_runs_replay_then_phase_gate(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if "scripts/run_replay_validation.py" in command:
            manifest_path = Path(command[command.index("--report-output") + 1])
            artifact_index_path = Path(command[command.index("--artifact-index-output") + 1])
            manifest_path.write_text(json.dumps({"matched": True}))
            artifact_index_path.write_text(json.dumps({"matched": True}))
        return 0, json.dumps({"matched": True}), "", 0.01

    monkeypatch.setattr(run_projector_phase2_validation, "_run", _run)
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")

    assert (
        run_projector_phase2_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--projector-summary",
                str(summary),
                "--live-checksums",
                str(tmp_path / "live.json"),
                "--require-projection-parity",
                "--output-dir",
                str(tmp_path),
                "--report-output",
                str(tmp_path / "phase2-report.json"),
            ]
        )
        == 0
    )

    replay_call = calls[0]
    assert "scripts/run_replay_validation.py" in replay_call
    assert "--projector-summary" in replay_call
    assert str(summary) in replay_call
    assert "--artifact-index-output" in replay_call
    phase_gate_call = calls[1]
    assert "scripts/check_projector_phase2_evidence.py" in phase_gate_call
    assert "--require-projection-parity" in phase_gate_call
    bundle_gate_call = calls[2]
    assert "scripts/check_replay_validation_bundle.py" in bundle_gate_call
    assert "--artifact-index" in bundle_gate_call
    assert "--require-projector-phase2" in bundle_gate_call
    assert "--require-projection-parity" in bundle_gate_call
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["artifacts"]["manifest"].endswith("phase2-replay-validation-123.json")
    assert output["steps"][0]["name"] == "replay_validation"
    assert output["steps"][1]["name"] == "phase2_evidence"
    assert output["steps"][2]["name"] == "bundle_evidence"


def test_run_projector_phase2_validation_captures_log_prefixed_step_json(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if "scripts/run_replay_validation.py" in command:
            manifest_path = Path(command[command.index("--report-output") + 1])
            artifact_index_path = Path(command[command.index("--artifact-index-output") + 1])
            manifest_path.write_text(json.dumps({"matched": True}))
            artifact_index_path.write_text(json.dumps({"matched": True}))
        return 0, 'INFO gate emitted a preface\n{"matched": true}\n', "", 0.01

    monkeypatch.setattr(run_projector_phase2_validation, "_run", _run)
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")

    assert (
        run_projector_phase2_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--projector-summary",
                str(summary),
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["steps"][0]["stdout_json"] == {"matched": True}
    assert output["steps"][1]["stdout_json"] == {"matched": True}
    assert output["steps"][2]["stdout_json"] == {"matched": True}


def test_run_projector_phase2_validation_passes_projector_summary_urls(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if "scripts/run_replay_validation.py" in command:
            manifest_path = Path(command[command.index("--report-output") + 1])
            artifact_index_path = Path(command[command.index("--artifact-index-output") + 1])
            manifest_path.write_text(json.dumps({"matched": True}))
            artifact_index_path.write_text(json.dumps({"matched": True}))
        return 0, json.dumps({"matched": True}), "", 0.01

    monkeypatch.setattr(run_projector_phase2_validation, "_run", _run)

    assert (
        run_projector_phase2_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--projector-summary-url",
                "projector-0=http://projector-0.example:9090",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )

    assert "--projector-summary-url" in calls[0]
    assert "projector-0=http://projector-0.example:9090" in calls[0]
    output = json.loads(capsys.readouterr().out)
    assert output["config"]["projector_summary_url"] == [
        "projector-0=http://projector-0.example:9090"
    ]


def test_run_projector_phase2_validation_stops_when_phase_gate_fails(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if "scripts/run_replay_validation.py" in command:
            manifest_path = Path(command[command.index("--report-output") + 1])
            artifact_index_path = Path(command[command.index("--artifact-index-output") + 1])
            manifest_path.write_text(json.dumps({"matched": True}))
            artifact_index_path.write_text(json.dumps({"matched": True}))
            return 0, json.dumps({"matched": True}), "", 0.01
        if "scripts/check_projector_phase2_evidence.py" in command:
            return 1, json.dumps({"matched": False}), "phase failed", 0.01
        return 0, json.dumps({"matched": True}), "", 0.01

    monkeypatch.setattr(run_projector_phase2_validation, "_run", _run)
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")

    assert (
        run_projector_phase2_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--projector-summary",
                str(summary),
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 1
    )

    assert len(calls) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    assert output["steps"][-1]["name"] == "phase2_evidence"
    assert output["steps"][-1]["stderr"] == "phase failed"


def test_run_projector_phase2_validation_fails_when_bundle_gate_fails(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if "scripts/run_replay_validation.py" in command:
            manifest_path = Path(command[command.index("--report-output") + 1])
            artifact_index_path = Path(command[command.index("--artifact-index-output") + 1])
            manifest_path.write_text(json.dumps({"matched": True}))
            artifact_index_path.write_text(json.dumps({"matched": True}))
            return 0, json.dumps({"matched": True}), "", 0.01
        if "scripts/check_replay_validation_bundle.py" in command:
            return 1, json.dumps({"matched": False}), "bundle failed", 0.01
        return 0, json.dumps({"matched": True}), "", 0.01

    monkeypatch.setattr(run_projector_phase2_validation, "_run", _run)
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")

    assert (
        run_projector_phase2_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--projector-summary",
                str(summary),
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 1
    )

    assert len(calls) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    assert output["steps"][-1]["name"] == "bundle_evidence"
    assert output["steps"][-1]["stderr"] == "bundle failed"


def test_run_projector_phase2_validation_stops_when_replay_validation_fails(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        return 2, "", "failed", 0.01

    monkeypatch.setattr(run_projector_phase2_validation, "_run", _run)
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")

    assert (
        run_projector_phase2_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--projector-summary",
                str(summary),
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 2
    )

    assert len(calls) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    assert output["steps"][0]["stderr"] == "failed"


def test_run_projector_phase2_validation_fails_when_replay_artifacts_are_missing(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        return 0, json.dumps({"matched": True}), "", 0.01

    monkeypatch.setattr(run_projector_phase2_validation, "_run", _run)
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")

    assert (
        run_projector_phase2_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--projector-summary",
                str(summary),
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 1
    )

    assert len(calls) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    assert output["steps"][-1]["name"] == "replay_validation_artifacts"
    assert output["steps"][-1]["stderr"].startswith(
        "replay validation did not create required artifacts:"
    )


def test_run_projector_phase2_validation_requires_projector_evidence(tmp_path: Path):
    try:
        run_projector_phase2_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--output-dir",
                str(tmp_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")
