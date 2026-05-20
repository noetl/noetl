import json
from pathlib import Path

from scripts.check_replay_validation_manifest import main


def _manifest(tmp_path: Path) -> dict:
    replay = tmp_path / "replay.json"
    replay.write_text("{}")
    return {
        "matched": True,
        "started_at": "2026-05-20T00:00:00Z",
        "finished_at": "2026-05-20T00:00:01Z",
        "replay": str(replay),
        "artifacts": {
            "replay": str(replay),
            "live_rows": None,
            "live_checksums": None,
            "report": None,
        },
        "config": {
            "base_url": "http://noetl.example",
            "execution_id": 123,
            "tenant_id": "tenant-a",
            "organization_id": "org-a",
            "projection": "all",
            "limit": 100000,
            "as_of_event_id": None,
            "as_of_position": None,
            "as_of_time": None,
            "resolve_payloads": False,
            "live_checksums": None,
            "live_rows": None,
            "export_live_rows_postgres": False,
        },
        "steps": [
            {
                "name": "fetch",
                "command": ["python", "scripts/fetch_replay_state_report.py"],
                "returncode": 0,
                "duration_seconds": 0.1,
                "stdout": "{}",
                "stderr": "",
                "stdout_json": {},
            },
            {
                "name": "state_integrity",
                "command": ["python", "scripts/check_replay_state_report.py"],
                "returncode": 0,
                "duration_seconds": 0.1,
                "stdout": "{}",
                "stderr": "",
            },
            {
                "name": "live_rows_export",
                "skipped": True,
            },
            {"name": "projection_parity", "skipped": True},
            {"name": "payload_resolution", "skipped": True},
        ],
    }


def test_check_replay_validation_manifest_accepts_success(tmp_path: Path, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest(tmp_path)))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_check_replay_validation_manifest_rejects_failed_by_default(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    manifest["matched"] = False
    manifest["steps"][1]["returncode"] = 1
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert {"matched", "steps[1].returncode"} <= fields


def test_check_replay_validation_manifest_can_allow_failed(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    manifest["matched"] = False
    manifest["steps"][1]["returncode"] = 1
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--allow-failed"]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_check_replay_validation_manifest_rejects_bad_step_order(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    manifest["steps"] = list(reversed(manifest["steps"]))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any("required step fetch" in failure["reason"] for failure in output["failures"])


def test_check_replay_validation_manifest_rejects_missing_artifact(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    manifest["artifacts"]["replay"] = str(tmp_path / "missing.json")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["failures"][0]["field"] == "artifacts.replay"


def test_check_replay_validation_manifest_checks_live_rows_artifact(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    live_rows = tmp_path / "live-rows.json"
    live_rows.write_text("{}")
    manifest["artifacts"]["live_rows"] = str(live_rows)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_check_replay_validation_manifest_rejects_multiple_live_inputs(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    manifest["config"]["live_checksums"] = "live.json"
    manifest["config"]["live_rows"] = "rows.json"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert "config.live_checksums" in {failure["field"] for failure in output["failures"]}
