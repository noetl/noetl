import json
from pathlib import Path

from scripts.check_replay_validation_bundle import main
from scripts.package_replay_validation_artifacts import build_artifact_index


def _bundle(tmp_path: Path) -> tuple[Path, Path]:
    replay = tmp_path / "replay.json"
    replay.write_text("{}")
    report = tmp_path / "validation-report.json"
    report.write_text("{}")
    index = tmp_path / "artifact-index.json"
    manifest = tmp_path / "validation.json"
    manifest.write_text(
        json.dumps(
            {
                "matched": True,
                "started_at": "2026-05-20T00:00:00Z",
                "finished_at": "2026-05-20T00:00:01Z",
                "replay": str(replay),
                "artifacts": {
                    "replay": str(replay),
                    "live_rows": None,
                    "live_checksums": None,
                    "report": str(report),
                    "artifact_index": str(index),
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
                    "artifact_index_output": str(index),
                },
                "steps": [
                    {
                        "name": "fetch",
                        "command": ["python", "scripts/fetch_replay_state_report.py"],
                        "returncode": 0,
                        "duration_seconds": 0.1,
                        "stdout": "{}",
                        "stderr": "",
                    },
                    {
                        "name": "state_integrity",
                        "command": ["python", "scripts/check_replay_state_report.py"],
                        "returncode": 0,
                        "duration_seconds": 0.1,
                        "stdout": "{}",
                        "stderr": "",
                    },
                    {"name": "live_rows_export", "skipped": True},
                    {"name": "live_rows_integrity", "skipped": True},
                    {"name": "live_checksums", "skipped": True},
                    {"name": "projection_parity", "skipped": True},
                    {"name": "payload_resolution", "skipped": True},
                    {
                        "name": "artifact_index",
                        "command": ["python", "scripts/package_replay_validation_artifacts.py"],
                        "returncode": 0,
                        "duration_seconds": 0.1,
                        "stdout": "{}",
                        "stderr": "",
                    },
                ],
            }
        )
    )
    index.write_text(
        json.dumps(
            build_artifact_index(manifest_path=manifest, output_path=index),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return manifest, index


def test_check_replay_validation_bundle_accepts_manifest_referenced_index(
    tmp_path: Path,
    capsys,
):
    manifest, index = _bundle(tmp_path)

    assert main(["--manifest", str(manifest)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["artifact_index"] == str(index)


def test_check_replay_validation_bundle_accepts_explicit_matching_index(
    tmp_path: Path,
    capsys,
):
    manifest, index = _bundle(tmp_path)

    assert main(["--manifest", str(manifest), "--artifact-index", str(index)]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_check_replay_validation_bundle_rejects_different_explicit_index(
    tmp_path: Path,
    capsys,
):
    manifest, _index = _bundle(tmp_path)
    other = tmp_path / "other-index.json"
    other.write_text("{}")

    assert main(["--manifest", str(manifest), "--artifact-index", str(other)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["reason"] == "artifact index argument differs from manifest reference"
        for failure in output["failures"]
    )


def test_check_replay_validation_bundle_rejects_index_drift(tmp_path: Path, capsys):
    manifest, _index = _bundle(tmp_path)
    (tmp_path / "validation-report.json").write_text('{"mutated": true}')

    assert main(["--manifest", str(manifest)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(failure["field"] == "manifest" for failure in output["failures"])
    assert any(failure["field"] == "artifact_index" for failure in output["failures"])


def test_check_replay_validation_bundle_rejects_missing_index_reference(
    tmp_path: Path,
    capsys,
):
    manifest, _index = _bundle(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["artifacts"]["artifact_index"] = None
    payload["steps"] = [step for step in payload["steps"] if step["name"] != "artifact_index"]
    manifest.write_text(json.dumps(payload))

    assert main(["--manifest", str(manifest)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["field"] == "artifacts.artifact_index"
        for failure in output["failures"]
    )
