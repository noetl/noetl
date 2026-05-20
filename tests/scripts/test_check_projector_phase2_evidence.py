import json
from pathlib import Path

from scripts.check_projector_phase2_evidence import main


def _manifest(tmp_path: Path) -> dict:
    replay = tmp_path / "replay.json"
    replay.write_text("{}")
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")
    live = tmp_path / "live-checksums.json"
    live.write_text("{}")
    return {
        "matched": True,
        "started_at": "2026-05-20T00:00:00Z",
        "finished_at": "2026-05-20T00:00:01Z",
        "replay": str(replay),
        "artifacts": {
            "replay": str(replay),
            "live_rows": None,
            "live_checksums": str(live),
            "projector_summaries": [
                {"role": "projector_summary_1", "path": str(summary)}
            ],
            "report": None,
            "artifact_index": None,
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
            "live_checksums": str(live),
            "live_rows": None,
            "export_live_rows_postgres": False,
            "projector_summary": [str(summary)],
            "projector_summary_url": [],
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
            {
                "name": "projection_parity",
                "command": ["python", "scripts/check_replay_parity_report.py"],
                "returncode": 0,
                "duration_seconds": 0.1,
                "stdout": "{}",
                "stderr": "",
            },
            {"name": "payload_resolution", "skipped": True},
            {
                "name": "projector_summary_1_integrity",
                "command": ["python", "scripts/check_projector_metrics_summary.py"],
                "returncode": 0,
                "duration_seconds": 0.1,
                "stdout": "{}",
                "stderr": "",
            },
        ],
    }


def test_check_projector_phase2_evidence_accepts_projector_manifest(tmp_path: Path, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest(tmp_path)))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_check_projector_phase2_evidence_requires_projector_summary(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    manifest["artifacts"]["projector_summaries"] = []
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert "artifacts.projector_summaries" in {failure["field"] for failure in output["failures"]}


def test_check_projector_phase2_evidence_requires_integrity_step(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    manifest["steps"] = [
        step for step in manifest["steps"] if step["name"] != "projector_summary_1_integrity"
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any("projector summary integrity" in failure["reason"] for failure in output["failures"])


def test_check_projector_phase2_evidence_can_require_projection_parity(
    tmp_path: Path,
    capsys,
):
    manifest = _manifest(tmp_path)
    for step in manifest["steps"]:
        if step["name"] == "projection_parity":
            step.clear()
            step.update({"name": "projection_parity", "skipped": True})
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--require-projection-parity"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert "steps.projection_parity" in {failure["field"] for failure in output["failures"]}
