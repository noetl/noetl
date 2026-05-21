import json
from pathlib import Path

import pytest

from scripts.check_replay_validation_manifest import main
from scripts.package_replay_validation_artifacts import build_artifact_index


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
            "projector_summaries": [],
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
            "live_checksums": None,
            "live_rows": None,
            "export_live_rows_postgres": False,
            "projector_summary": [],
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
            {
                "name": "live_rows_integrity",
                "skipped": True,
            },
            {
                "name": "live_checksums",
                "skipped": True,
            },
            {"name": "projection_parity", "skipped": True},
            {"name": "payload_resolution", "skipped": True},
        ],
    }


def _write_manifest_with_artifact_index(tmp_path: Path) -> Path:
    manifest = _manifest(tmp_path)
    report = tmp_path / "validation-report.json"
    report.write_text("{}")
    index_path = tmp_path / "artifact-index.json"
    manifest["artifacts"]["report"] = str(report)
    manifest["artifacts"]["artifact_index"] = str(index_path)
    manifest["steps"].append(
        {
            "name": "artifact_index",
            "command": ["python", "scripts/package_replay_validation_artifacts.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        }
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    index_path.write_text(
        json.dumps(build_artifact_index(manifest_path=path), indent=2, sort_keys=True)
        + "\n"
    )
    return path


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


def test_check_replay_validation_manifest_requires_live_rows_integrity(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    live_rows = tmp_path / "live-rows.json"
    live_rows.write_text("{}")
    manifest["artifacts"]["live_rows"] = str(live_rows)
    manifest["steps"] = [
        step for step in manifest["steps"] if step["name"] != "live_rows_integrity"
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any("live_rows_integrity" in failure["reason"] for failure in output["failures"])


def test_check_replay_validation_manifest_requires_live_rows_integrity_before_checksums(
    tmp_path: Path,
    capsys,
):
    manifest = _manifest(tmp_path)
    manifest["config"]["live_rows"] = "live-rows.json"
    live_integrity = next(step for step in manifest["steps"] if step["name"] == "live_rows_integrity")
    manifest["steps"] = [
        step for step in manifest["steps"] if step["name"] != "live_rows_integrity"
    ]
    manifest["steps"].append(live_integrity)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any("before live_checksums" in failure["reason"] for failure in output["failures"])


def test_check_replay_validation_manifest_rejects_multiple_live_inputs(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    manifest["config"]["live_checksums"] = "live.json"
    manifest["config"]["live_rows"] = "rows.json"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert "config.live_checksums" in {failure["field"] for failure in output["failures"]}


def test_check_replay_validation_manifest_validates_artifact_index(tmp_path: Path, capsys):
    path = _write_manifest_with_artifact_index(tmp_path)

    assert main(["--manifest", str(path), "--check-artifacts"]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_check_replay_validation_manifest_rejects_artifact_index_drift(tmp_path: Path, capsys):
    path = _write_manifest_with_artifact_index(tmp_path)
    (tmp_path / "validation-report.json").write_text('{"mutated": true}')

    assert main(["--manifest", str(path), "--check-artifacts"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["field"] == "artifacts.artifact_index"
        and failure["reason"] == "artifact index validation failed"
        for failure in output["failures"]
    )


def test_check_replay_validation_manifest_rejects_artifact_index_for_other_manifest(
    tmp_path: Path,
    capsys,
):
    path = _write_manifest_with_artifact_index(tmp_path)
    index_path = tmp_path / "artifact-index.json"
    index = json.loads(index_path.read_text())
    other_manifest = tmp_path / "other-manifest.json"
    other_manifest.write_text("{}")
    index["manifest"] = str(other_manifest)
    index_path.write_text(json.dumps(index))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["field"] == "artifacts.artifact_index"
        and failure["reason"] == "artifact index points at a different manifest"
        for failure in output["failures"]
    )


@pytest.mark.parametrize(
    ("artifact_field", "role", "filename", "integrity_step"),
    [
        (
            "projector_summaries",
            "projector_summary_1",
            "projector-summary.json",
            "projector_summary_1_integrity",
        ),
        (
            "worker_metrics",
            "worker_metrics_1",
            "worker.prom",
            "worker_metrics_1_integrity",
        ),
        (
            "storage_backend_registry",
            "storage_backend_registry",
            "storage-phase5-report.json",
            "storage_backend_registry_integrity",
        ),
        (
            "fanout_reduce_planner",
            "fanout_reduce_planner",
            "fanout-phase6-report.json",
            "fanout_reduce_planner_integrity",
        ),
    ],
)
def test_check_replay_validation_manifest_requires_indexed_phase_artifact_roles(
    tmp_path: Path,
    capsys,
    artifact_field: str,
    role: str,
    filename: str,
    integrity_step: str,
):
    manifest = _manifest(tmp_path)
    artifact = tmp_path / filename
    artifact.write_text("{}")
    report = tmp_path / "validation-report.json"
    report.write_text("{}")
    index_path = tmp_path / "artifact-index.json"
    manifest["artifacts"]["report"] = str(report)
    manifest["artifacts"]["artifact_index"] = str(index_path)
    manifest["artifacts"][artifact_field] = [{"role": role, "path": str(artifact)}]
    manifest["steps"].append(
        {
            "name": integrity_step,
            "command": ["python", "scripts/check_phase_artifact.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        }
    )
    manifest["steps"].append(
        {
            "name": "artifact_index",
            "command": ["python", "scripts/package_replay_validation_artifacts.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        }
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    index_path.write_text(
        json.dumps(build_artifact_index(manifest_path=path, output_path=index_path))
        + "\n"
    )

    assert main(["--manifest", str(path), "--check-artifacts"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["field"] == "artifacts.artifact_index"
        and failure["reason"] == "artifact index missing phase artifact roles"
        and failure["roles"] == [role]
        for failure in output["failures"]
    )


def test_check_replay_validation_manifest_requires_artifact_index_step(tmp_path: Path, capsys):
    path = _write_manifest_with_artifact_index(tmp_path)
    manifest = json.loads(path.read_text())
    manifest["steps"] = [step for step in manifest["steps"] if step["name"] != "artifact_index"]
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any("artifact_index step" in failure["reason"] for failure in output["failures"])


def test_check_replay_validation_manifest_requires_artifact_index_step_last(
    tmp_path: Path,
    capsys,
):
    path = _write_manifest_with_artifact_index(tmp_path)
    manifest = json.loads(path.read_text())
    artifact_step = manifest["steps"].pop()
    manifest["steps"].insert(1, artifact_step)
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any("artifact_index step must be last" in failure["reason"] for failure in output["failures"])


def test_check_replay_validation_manifest_rejects_orphan_artifact_index_step(
    tmp_path: Path,
    capsys,
):
    manifest = _manifest(tmp_path)
    manifest["steps"].append({"name": "artifact_index", "skipped": True})
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert "artifacts.artifact_index" in {failure["field"] for failure in output["failures"]}


def test_check_replay_validation_manifest_accepts_projector_summary_artifact(
    tmp_path: Path,
    capsys,
):
    manifest = _manifest(tmp_path)
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")
    manifest["artifacts"]["projector_summaries"] = [
        {"role": "projector_summary_1", "path": str(summary)}
    ]
    manifest["steps"].append(
        {
            "name": "projector_summary_1_integrity",
            "command": ["python", "scripts/check_projector_metrics_summary.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        }
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_check_replay_validation_manifest_requires_projector_summary_integrity(
    tmp_path: Path,
    capsys,
):
    manifest = _manifest(tmp_path)
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")
    manifest["artifacts"]["projector_summaries"] = [
        {"role": "projector_summary_1", "path": str(summary)}
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any("projector summary artifacts" in failure["reason"] for failure in output["failures"])


def test_check_replay_validation_manifest_rejects_bad_projector_summary_artifact(
    tmp_path: Path,
    capsys,
):
    manifest = _manifest(tmp_path)
    manifest["artifacts"]["projector_summaries"] = [
        {"role": "", "path": str(tmp_path / "missing-summary.json")}
    ]
    manifest["steps"].append(
        {
            "name": "projector_summary_1_integrity",
            "command": ["python", "scripts/check_projector_metrics_summary.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        }
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert main(["--manifest", str(path), "--check-artifacts"]) == 1
    output = json.loads(capsys.readouterr().out)
    fields = {failure["field"] for failure in output["failures"]}
    assert "artifacts.projector_summaries[0].role" in fields
    assert "artifacts.projector_summaries[0].path" in fields
