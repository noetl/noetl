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
    assert output["artifacts"]["replay"].endswith("replay-123.json")
    assert output["artifacts"]["live_rows"] is None
    assert output["artifacts"]["report"].endswith("manifest.json")
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
    assert output["artifacts"]["live_rows"] == str(live_rows_path)
    assert output["artifacts"]["live_checksums"].endswith("live-checksums-123.json")


def test_run_replay_validation_can_export_live_rows_from_postgres(monkeypatch, tmp_path: Path, capsys):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        if any(str(part).endswith("export_live_projection_rows_postgres.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"rows": {"execution": []}}))
        if any(str(part).endswith("build_live_projection_checksums.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)

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
                "--export-live-rows-postgres",
                "--postgres-dsn",
                "postgresql://example",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )

    assert any("scripts/export_live_projection_rows_postgres.py" in call for call in calls)
    export_call = next(
        call for call in calls if "scripts/export_live_projection_rows_postgres.py" in call
    )
    assert "--dsn" in export_call
    assert "postgresql://example" in export_call
    output = json.loads(capsys.readouterr().out)
    assert output["config"]["export_live_rows_postgres"] is True
    assert output["artifacts"]["live_rows"].endswith("live-rows-123.json")
    assert output["artifacts"]["live_checksums"].endswith("live-checksums-123.json")
    assert [step["name"] for step in output["steps"][:5]] == [
        "fetch",
        "state_integrity",
        "live_rows_export",
        "live_rows_integrity",
        "live_checksums",
    ]


def test_run_replay_validation_can_write_artifact_index(monkeypatch, tmp_path: Path, capsys):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        if any(str(part).endswith("package_replay_validation_artifacts.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"schema_version": 1, "matched": True, "artifacts": []}))
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)
    manifest = tmp_path / "validation.json"
    artifact_index = tmp_path / "artifact-index.json"

    assert (
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--output-dir",
                str(tmp_path),
                "--report-output",
                str(manifest),
                "--artifact-index-output",
                str(artifact_index),
            ]
        )
        == 0
    )

    assert artifact_index.exists()
    assert any("scripts/package_replay_validation_artifacts.py" in call for call in calls)
    manifest_payload = json.loads(manifest.read_text())
    assert manifest_payload["artifacts"]["artifact_index"] == str(artifact_index)
    assert json.loads(capsys.readouterr().out)["artifacts"]["artifact_index"] == str(artifact_index)


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
                "--export-live-rows-postgres",
                "--output-dir",
                str(tmp_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")


def test_run_replay_validation_rejects_postgres_dsn_without_export(tmp_path: Path):
    try:
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--postgres-dsn",
                "postgresql://example",
                "--output-dir",
                str(tmp_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")


def test_run_replay_validation_rejects_artifact_index_without_manifest(tmp_path: Path):
    try:
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--artifact-index-output",
                str(tmp_path / "artifact-index.json"),
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
