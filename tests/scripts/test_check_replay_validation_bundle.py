import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_replay_validation_bundle import main
from scripts.package_replay_validation_artifacts import build_artifact_index


def _bundle(tmp_path: Path) -> tuple[Path, Path]:
    replay = tmp_path / "replay.json"
    replay.write_text("{}")
    report = tmp_path / "validation-report.json"
    report.write_text("{}")
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")
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
                    "projector_summaries": [],
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
                    "projector_summary": [],
                    "projector_summary_url": [],
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


def _add_replay_fanout_phase6_evidence(manifest: Path, index: Path) -> None:
    payload = json.loads(manifest.read_text())
    replay = Path(payload["artifacts"]["replay"])
    replay.write_text(
        json.dumps(
            {
                "commands": {
                    "10": {
                        "command_id": "10",
                        "fanout_reduce": {
                            "planner_version": 1,
                            "fanout_step": "start",
                            "fanout_targets": ["a", "b"],
                            "target_step": "a",
                            "target_index": 0,
                            "reduce_steps": ["join"],
                        },
                    }
                }
            },
            indent=2,
            sort_keys=True,
        )
    )
    payload["config"]["check_replay_fanout_reduce"] = True
    payload["steps"].insert(
        -1,
        {
            "name": "replay_fanout_reduce_integrity",
            "command": ["python", "scripts/check_replay_fanout_reduce_report.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        },
    )
    manifest.write_text(json.dumps(payload))
    index.write_text(
        json.dumps(
            build_artifact_index(manifest_path=manifest, output_path=index),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _add_projector_phase2_evidence(manifest: Path, index: Path, tmp_path: Path) -> None:
    payload = json.loads(manifest.read_text())
    summary = tmp_path / "projector-summary.json"
    summary.write_text("{}")
    live_rows = tmp_path / "live-rows.json"
    live_rows.write_text("{}")
    live = tmp_path / "live-checksums.json"
    live.write_text("{}")
    payload["artifacts"]["live_rows"] = str(live_rows)
    payload["artifacts"]["live_checksums"] = str(live)
    payload["config"]["live_rows"] = str(live_rows)
    payload["artifacts"]["projector_summaries"] = [
        {"role": "projector_summary_1", "path": str(summary)}
    ]
    payload["config"]["live_checksums"] = None
    payload["config"]["projector_summary"] = [str(summary)]
    payload["steps"] = [
        step for step in payload["steps"] if step["name"] != "projection_parity"
    ]
    payload["steps"].insert(
        5,
        {
            "name": "projection_parity",
            "command": ["python", "scripts/check_replay_parity_report.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        },
    )
    payload["steps"].insert(
        -1,
        {
            "name": "projector_summary_1_integrity",
            "command": ["python", "scripts/check_projector_metrics_summary.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        },
    )
    manifest.write_text(json.dumps(payload))
    index.write_text(
        json.dumps(
            build_artifact_index(
                manifest_path=manifest,
                output_path=index,
                extra_artifacts=[("projector_summary_1", summary)],
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _worker_metrics_body() -> str:
    labels = '{node_id="node-a",worker_id="worker-a"}'
    return "\n".join(
        [
            f"noetl_storage_ipc_admit_attempts_total{labels} 1",
            f"noetl_storage_ipc_admit_success_total{labels} 1",
            f"noetl_storage_ipc_admit_failures_total{labels} 0",
            f"noetl_storage_ipc_read_attempts_total{labels} 2",
            f"noetl_storage_ipc_read_hits_total{labels} 1",
            f"noetl_storage_ipc_read_misses_total{labels} 1",
            f"noetl_storage_ipc_fallback_reads_total{labels} 1",
            f"noetl_storage_ipc_read_hit_ratio{labels} 0.5",
            "",
        ]
    )


def _add_worker_phase3_evidence(manifest: Path, index: Path, tmp_path: Path) -> None:
    payload = json.loads(manifest.read_text())
    metrics = tmp_path / "worker.prom"
    metrics.write_text(_worker_metrics_body())
    payload["artifacts"]["worker_metrics"] = [
        {"role": "worker_metrics_1", "path": str(metrics)}
    ]
    payload["config"]["worker_metrics"] = [str(metrics)]
    payload["config"]["worker_metrics_url"] = []
    payload["steps"].insert(
        -1,
        {
            "name": "worker_metrics_1_integrity",
            "command": ["python", "scripts/check_worker_ipc_metrics.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        },
    )
    manifest.write_text(json.dumps(payload))
    index.write_text(
        json.dumps(
            build_artifact_index(
                manifest_path=manifest,
                output_path=index,
                extra_artifacts=[("worker_metrics_1", metrics)],
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _storage_phase5_report() -> dict:
    return {
        "registered_backends": ["disk", "gcs", "kv", "memory", "s3"],
        "consumer_paths": {
            "result_store": True,
            "artifact_executor": True,
            "agent_disk_fallback": True,
        },
        "direct_backend_construction": {
            "matched": True,
            "unexpected": [],
        },
    }


def _fanout_phase6_report() -> dict:
    return {
        "planner_version": 1,
        "summary": {"playbooks": 1, "fanouts": 1, "reduces": 1},
        "playbooks": [
            {
                "path": "tests/fixtures/playbooks/fanout.yaml",
                "name": "fanout",
                "planner": {
                    "fanouts": [
                        {
                            "step": "start",
                            "arcs": ["a", "b"],
                            "reduce_steps": ["join"],
                        }
                    ],
                    "reduces": [
                        {
                            "step": "join",
                            "upstream_steps": ["a", "b"],
                        }
                    ],
                },
            }
        ],
    }


def _add_storage_phase5_evidence(manifest: Path, index: Path, tmp_path: Path) -> None:
    payload = json.loads(manifest.read_text())
    report = tmp_path / "storage-phase5-report.json"
    report.write_text(json.dumps(_storage_phase5_report(), indent=2, sort_keys=True))
    payload["artifacts"]["storage_backend_registry"] = [
        {"role": "storage_backend_registry", "path": str(report)}
    ]
    payload["config"]["storage_backend_registry_report"] = str(report)
    payload["steps"].insert(
        -1,
        {
            "name": "storage_backend_registry_report",
            "command": ["python", "scripts/build_storage_phase5_report.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        },
    )
    payload["steps"].insert(
        -1,
        {
            "name": "storage_backend_registry_integrity",
            "command": ["python", "scripts/check_storage_phase5_evidence.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        },
    )
    manifest.write_text(json.dumps(payload))
    index.write_text(
        json.dumps(
            build_artifact_index(
                manifest_path=manifest,
                output_path=index,
                extra_artifacts=[("storage_backend_registry", report)],
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _add_fanout_phase6_evidence(manifest: Path, index: Path, tmp_path: Path) -> None:
    payload = json.loads(manifest.read_text())
    report = tmp_path / "fanout-phase6-report.json"
    report.write_text(json.dumps(_fanout_phase6_report(), indent=2, sort_keys=True))
    payload["artifacts"]["fanout_reduce_planner"] = [
        {"role": "fanout_reduce_planner", "path": str(report)}
    ]
    payload["config"]["fanout_reduce_planner_report"] = str(report)
    payload["steps"].insert(
        -1,
        {
            "name": "fanout_reduce_planner_report",
            "command": ["python", "scripts/build_fanout_phase6_report.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        },
    )
    payload["steps"].insert(
        -1,
        {
            "name": "fanout_reduce_planner_integrity",
            "command": ["python", "scripts/check_fanout_phase6_evidence.py"],
            "returncode": 0,
            "duration_seconds": 0.1,
            "stdout": "{}",
            "stderr": "",
        },
    )
    manifest.write_text(json.dumps(payload))
    index.write_text(
        json.dumps(
            build_artifact_index(
                manifest_path=manifest,
                output_path=index,
                extra_artifacts=[("fanout_reduce_planner", report)],
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _drop_index_role(index: Path, role: str) -> None:
    payload = json.loads(index.read_text())
    payload["artifacts"] = [
        entry
        for entry in payload["artifacts"]
        if not (isinstance(entry, dict) and entry.get("role") == role)
    ]
    index.write_text(json.dumps(payload))


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


def test_check_replay_validation_bundle_accepts_projector_phase2_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, index = _bundle(tmp_path)
    _add_projector_phase2_evidence(manifest, index, tmp_path)

    assert (
        main(
            [
                "--manifest",
                str(manifest),
                "--require-projector-phase2",
                "--require-projection-parity",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["phase2_projector_result"]["matched"] is True


def test_check_replay_validation_bundle_rejects_missing_projector_phase2_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, _index = _bundle(tmp_path)

    assert main(["--manifest", str(manifest), "--require-projector-phase2"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["field"] == "phase2_projector_evidence"
        for failure in output["failures"]
    )


def test_check_replay_validation_bundle_requires_indexed_projector_phase2_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, index = _bundle(tmp_path)
    _add_projector_phase2_evidence(manifest, index, tmp_path)
    _drop_index_role(index, "projector_summary_1")

    assert main(["--manifest", str(manifest), "--require-projector-phase2"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["reason"] == "artifact index missing required phase evidence roles"
        and failure["roles"] == ["projector_summary_1"]
        for failure in output["failures"]
    )


def test_check_replay_validation_bundle_rejects_duplicate_projector_phase2_roles(
    tmp_path: Path,
    capsys,
):
    manifest, index = _bundle(tmp_path)
    _add_projector_phase2_evidence(manifest, index, tmp_path)
    payload = json.loads(manifest.read_text())
    payload["artifacts"]["projector_summaries"].append(
        dict(payload["artifacts"]["projector_summaries"][0])
    )
    manifest.write_text(json.dumps(payload))

    assert main(["--manifest", str(manifest), "--require-projector-phase2"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["field"] == "manifest"
        and any(
            nested_failure["reason"] == "artifact roles must be unique"
            and nested_failure["roles"] == ["projector_summary_1"]
            for nested_failure in failure.get("failures", [])
        )
        for failure in output["failures"]
    )


def test_check_replay_validation_bundle_accepts_worker_ipc_phase3_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, index = _bundle(tmp_path)
    _add_worker_phase3_evidence(manifest, index, tmp_path)

    assert main(["--manifest", str(manifest), "--require-worker-ipc-phase3"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["phase3_worker_ipc_result"]["matched"] is True


def test_check_replay_validation_bundle_accepts_worker_ipc_admission_only_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, index = _bundle(tmp_path)
    _add_worker_phase3_evidence(manifest, index, tmp_path)
    payload = json.loads(manifest.read_text())
    payload["config"]["worker_metrics_admission_only"] = True
    metrics_path = Path(payload["artifacts"]["worker_metrics"][0]["path"])
    metrics_path.write_text(
        _worker_metrics_body()
        .replace("noetl_storage_ipc_read_hits_total{node_id=\"node-a\",worker_id=\"worker-a\"} 1", "noetl_storage_ipc_read_hits_total{node_id=\"node-a\",worker_id=\"worker-a\"} 0")
        .replace("noetl_storage_ipc_fallback_reads_total{node_id=\"node-a\",worker_id=\"worker-a\"} 1", "noetl_storage_ipc_fallback_reads_total{node_id=\"node-a\",worker_id=\"worker-a\"} 0")
    )
    manifest.write_text(json.dumps(payload))
    index.write_text(
        json.dumps(
            build_artifact_index(
                manifest_path=manifest,
                output_path=index,
                extra_artifacts=[("worker_metrics_1", metrics_path)],
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    assert main(["--manifest", str(manifest), "--require-worker-ipc-phase3"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["phase3_worker_ipc_result"]["worker_metrics_admission_only"] is True


def test_check_replay_validation_bundle_rejects_missing_worker_ipc_phase3_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, _index = _bundle(tmp_path)

    assert main(["--manifest", str(manifest), "--require-worker-ipc-phase3"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["field"] == "phase3_worker_ipc_evidence"
        for failure in output["failures"]
    )


def test_check_replay_validation_bundle_accepts_storage_phase5_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, index = _bundle(tmp_path)
    _add_storage_phase5_evidence(manifest, index, tmp_path)

    assert main(["--manifest", str(manifest), "--require-storage-phase5"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["phase5_storage_result"]["matched"] is True


def test_check_replay_validation_bundle_cli_runs_from_repo_root(tmp_path: Path):
    manifest, index = _bundle(tmp_path)
    _add_storage_phase5_evidence(manifest, index, tmp_path)
    repo_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_replay_validation_bundle.py",
            "--manifest",
            str(manifest),
            "--require-storage-phase5",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["matched"] is True


def test_check_replay_validation_bundle_rejects_missing_storage_phase5_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, _index = _bundle(tmp_path)

    assert main(["--manifest", str(manifest), "--require-storage-phase5"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["field"] == "phase5_storage_evidence"
        for failure in output["failures"]
    )


def test_check_replay_validation_bundle_accepts_fanout_phase6_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, index = _bundle(tmp_path)
    _add_fanout_phase6_evidence(manifest, index, tmp_path)

    assert main(["--manifest", str(manifest), "--require-fanout-phase6"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["phase6_fanout_result"]["matched"] is True


def test_check_replay_validation_bundle_rejects_missing_fanout_phase6_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, _index = _bundle(tmp_path)

    assert main(["--manifest", str(manifest), "--require-fanout-phase6"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["field"] == "phase6_fanout_evidence"
        for failure in output["failures"]
    )


def test_check_replay_validation_bundle_accepts_replay_fanout_phase6_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, index = _bundle(tmp_path)
    _add_replay_fanout_phase6_evidence(manifest, index)

    assert main(["--manifest", str(manifest), "--require-replay-fanout-phase6"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["phase6_replay_fanout_result"]["matched"] is True


def test_check_replay_validation_bundle_rejects_missing_replay_fanout_phase6_evidence(
    tmp_path: Path,
    capsys,
):
    manifest, _index = _bundle(tmp_path)

    assert main(["--manifest", str(manifest), "--require-replay-fanout-phase6"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["field"] == "phase6_replay_fanout_evidence"
        for failure in output["failures"]
    )


@pytest.mark.parametrize(
    ("add_evidence", "role", "flag"),
    [
        (_add_worker_phase3_evidence, "worker_metrics_1", "--require-worker-ipc-phase3"),
        (_add_storage_phase5_evidence, "storage_backend_registry", "--require-storage-phase5"),
        (_add_fanout_phase6_evidence, "fanout_reduce_planner", "--require-fanout-phase6"),
    ],
)
def test_check_replay_validation_bundle_requires_indexed_phase_evidence_roles(
    tmp_path: Path,
    capsys,
    add_evidence,
    role: str,
    flag: str,
):
    manifest, index = _bundle(tmp_path)
    add_evidence(manifest, index, tmp_path)
    _drop_index_role(index, role)

    assert main(["--manifest", str(manifest), flag]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any(
        failure["reason"] == "artifact index missing required phase evidence roles"
        and failure["roles"] == [role]
        for failure in output["failures"]
    )
