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

    assert len(calls) == 5
    assert "scripts/fetch_replay_state_report.py" in calls[0]
    assert "--resolve-payloads" in calls[0]
    assert "scripts/check_replay_state_report.py" in calls[1]
    assert "scripts/check_runtime_locator_surfaces.py" in calls[2]
    assert "scripts/check_replay_parity_report.py" in calls[3]
    assert "scripts/check_replay_payload_resolution_report.py" in calls[4]
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


def test_run_replay_validation_captures_log_prefixed_step_json(monkeypatch, tmp_path: Path, capsys):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        if any(str(part).endswith("check_replay_state_report.py") for part in command):
            return 0, 'INFO validated env\n{"matched": true, "failures": []}\n', "", 0.01
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
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["steps"][1]["name"] == "state_integrity"
    assert output["steps"][1]["stdout_json"] == {"matched": True, "failures": []}


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
    manifest = tmp_path / "validation.json"

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
        "runtime_locator_state",
        "live_rows_export",
        "live_rows_integrity",
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
    assert manifest_payload["steps"][-1]["name"] == "artifact_index"
    assert manifest_payload["steps"][-1]["stdout_json"] == {
        "matched": True,
        "output": str(artifact_index),
    }
    assert json.loads(capsys.readouterr().out)["artifacts"]["artifact_index"] == str(artifact_index)


def test_run_replay_validation_indexes_all_saved_phase_artifacts(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        if any(str(part).endswith("package_replay_validation_artifacts.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(
                json.dumps({"schema_version": 1, "matched": True, "artifacts": []})
            )
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)
    manifest = tmp_path / "validation.json"
    artifact_index = tmp_path / "artifact-index.json"
    projector_summary = tmp_path / "projector-summary.json"
    projector_summary.write_text("{}")
    worker_metrics = tmp_path / "worker.prom"
    worker_metrics.write_text("noetl_storage_ipc_admit_success_total 1\n")
    storage_report = tmp_path / "storage-phase5-report.json"
    storage_report.write_text("{}")
    fanout_report = tmp_path / "fanout-phase6-report.json"
    fanout_report.write_text("{}")

    assert (
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--projector-summary",
                str(projector_summary),
                "--worker-metrics",
                str(worker_metrics),
                "--storage-backend-registry-report",
                str(storage_report),
                "--fanout-reduce-planner-report",
                str(fanout_report),
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

    package_call = next(
        call for call in calls if "scripts/package_replay_validation_artifacts.py" in call
    )
    artifact_args = [
        package_call[idx + 1]
        for idx, value in enumerate(package_call)
        if value == "--artifact"
    ]
    assert artifact_args == [
        f"projector_summary_1={projector_summary}",
        f"worker_metrics_1={worker_metrics}",
        f"storage_backend_registry_1={storage_report}",
        f"fanout_reduce_planner_1={fanout_report}",
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["artifacts"]["projector_summaries"][0]["role"] == "projector_summary_1"
    assert output["artifacts"]["worker_metrics"][0]["role"] == "worker_metrics_1"
    assert output["artifacts"]["storage_backend_registry"][0]["role"] == "storage_backend_registry_1"
    assert output["artifacts"]["fanout_reduce_planner"][0]["role"] == "fanout_reduce_planner_1"


def test_run_replay_validation_validates_saved_projector_summary(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)
    projector_summary = tmp_path / "projector-summary.json"
    projector_summary.write_text(json.dumps({"labels": {}, "summary": {}}))

    assert (
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--projector-summary",
                str(projector_summary),
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )

    assert any("scripts/check_projector_metrics_summary.py" in call for call in calls)
    output = json.loads(capsys.readouterr().out)
    assert output["artifacts"]["projector_summaries"] == [
        {"role": "projector_summary_1", "path": str(projector_summary)}
    ]
    assert output["steps"][-1]["name"] == "projector_summary_1_integrity"


def test_run_replay_validation_fetches_and_indexes_projector_summary(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        if any(str(part).endswith("fetch_projector_metrics_summary.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"labels": {}, "summary": {}}))
        if any(str(part).endswith("package_replay_validation_artifacts.py") for part in command):
            assert "--artifact" in command
            artifact_arg = command[command.index("--artifact") + 1]
            assert artifact_arg.startswith("projector_summary_url_1_projector-0=")
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
                "--projector-summary-url",
                "projector-0=http://projector-0.example:9090",
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

    assert any("scripts/fetch_projector_metrics_summary.py" in call for call in calls)
    assert any("scripts/check_projector_metrics_summary.py" in call for call in calls)
    output = json.loads(capsys.readouterr().out)
    summaries = output["artifacts"]["projector_summaries"]
    assert summaries[0]["role"] == "projector_summary_url_1_projector-0"
    assert summaries[0]["url"] == "http://projector-0.example:9090"
    assert summaries[0]["path"].endswith("projector_summary_url_1_projector-0.json")


def test_run_replay_validation_rejects_invalid_projector_summary_url(tmp_path: Path):
    try:
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--projector-summary-url",
                "http://projector.example",
                "--output-dir",
                str(tmp_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")


def test_run_replay_validation_fetches_and_indexes_worker_metrics(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        if any(str(part).endswith("fetch_worker_metrics.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text("noetl_worker_up 1\n")
        if any(str(part).endswith("package_replay_validation_artifacts.py") for part in command):
            artifact_args = [
                command[idx + 1]
                for idx, value in enumerate(command)
                if value == "--artifact"
            ]
            assert any(arg.startswith("worker_metrics_url_1_worker-0=") for arg in artifact_args)
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
                "--worker-metrics-url",
                "worker-0=http://worker-0.example:9091",
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

    assert any("scripts/fetch_worker_metrics.py" in call for call in calls)
    assert any("scripts/check_worker_ipc_metrics.py" in call for call in calls)
    output = json.loads(capsys.readouterr().out)
    metrics = output["artifacts"]["worker_metrics"]
    assert metrics[0]["role"] == "worker_metrics_url_1_worker-0"
    assert metrics[0]["url"] == "http://worker-0.example:9091"
    assert metrics[0]["path"].endswith("worker_metrics_url_1_worker-0.prom")


def test_run_replay_validation_passes_worker_metrics_admission_only_flag(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        if any(str(part).endswith("fetch_worker_metrics.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text("noetl_worker_up 1\n")
        if any(str(part).endswith("package_replay_validation_artifacts.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"schema_version": 1, "matched": True, "artifacts": []}))
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)
    manifest = tmp_path / "validation.json"

    assert (
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--worker-metrics-url",
                "worker-0=http://worker-0.example:9091",
                "--worker-metrics-admission-only",
                "--output-dir",
                str(tmp_path),
                "--report-output",
                str(manifest),
            ]
        )
        == 0
    )

    assert any(
        "scripts/check_worker_ipc_metrics.py" in call
        and "--require-admission-only" in call
        for call in calls
    )
    output = json.loads(capsys.readouterr().out)
    assert output["config"]["worker_metrics_admission_only"] is True


def test_run_replay_validation_builds_and_indexes_storage_phase5_report(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        if any(str(part).endswith("build_storage_phase5_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(
                json.dumps(
                    {
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
                )
            )
        if any(str(part).endswith("package_replay_validation_artifacts.py") for part in command):
            artifact_args = [
                command[idx + 1]
                for idx, value in enumerate(command)
                if value == "--artifact"
            ]
            assert any(
                arg.startswith("storage_backend_registry_generated=")
                for arg in artifact_args
            )
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
                "--build-storage-backend-registry-report",
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

    assert any("scripts/build_storage_phase5_report.py" in call for call in calls)
    assert any("scripts/check_storage_phase5_evidence.py" in call for call in calls)
    output = json.loads(capsys.readouterr().out)
    reports = output["artifacts"]["storage_backend_registry"]
    assert reports == [
        {
            "role": "storage_backend_registry_generated",
            "path": str(tmp_path / "storage-phase5-report.json"),
        }
    ]
    assert output["config"]["build_storage_backend_registry_report"] is True
    assert "storage_backend_registry_integrity" in [
        step["name"] for step in output["steps"]
    ]


def test_run_replay_validation_builds_and_indexes_fanout_phase6_report(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        if any(str(part).endswith("build_fanout_phase6_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(
                json.dumps(
                    {
                        "planner_version": 1,
                        "summary": {"playbooks": 1, "fanouts": 1, "reduces": 1},
                        "playbooks": [
                            {
                                "path": "fanout.yaml",
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
                )
            )
        if any(str(part).endswith("package_replay_validation_artifacts.py") for part in command):
            artifact_args = [
                command[idx + 1]
                for idx, value in enumerate(command)
                if value == "--artifact"
            ]
            assert any(arg.startswith("fanout_reduce_planner_generated=") for arg in artifact_args)
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"schema_version": 1, "matched": True, "artifacts": []}))
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)
    manifest = tmp_path / "validation.json"
    artifact_index = tmp_path / "artifact-index.json"
    playbook = tmp_path / "fanout.yaml"
    playbook.write_text("apiVersion: noetl.io/v2\nkind: Playbook\nmetadata: {name: fanout}\nworkflow: []\n")

    assert (
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--fanout-reduce-playbook",
                str(playbook),
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

    assert any("scripts/build_fanout_phase6_report.py" in call for call in calls)
    assert any("scripts/check_fanout_phase6_evidence.py" in call for call in calls)
    output = json.loads(capsys.readouterr().out)
    reports = output["artifacts"]["fanout_reduce_planner"]
    assert reports == [
        {
            "role": "fanout_reduce_planner_generated",
            "path": str(tmp_path / "fanout-phase6-report.json"),
        }
    ]
    assert "fanout_reduce_planner_integrity" in [
        step["name"] for step in output["steps"]
    ]


def test_run_replay_validation_can_check_replay_fanout_reduce_metadata(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls = []

    def _run(command):
        calls.append(command)
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "projection_checksums": {"execution": "a" * 64},
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
                        },
                    }
                )
            )
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)
    manifest = tmp_path / "validation.json"

    assert (
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--check-replay-fanout-reduce",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )

    assert any("scripts/check_replay_fanout_reduce_report.py" in call for call in calls)
    output = json.loads(capsys.readouterr().out)
    assert output["config"]["check_replay_fanout_reduce"] is True
    assert "replay_fanout_reduce_integrity" in [step["name"] for step in output["steps"]]


def test_run_replay_validation_rejects_invalid_worker_metrics_url(tmp_path: Path):
    try:
        run_replay_validation.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--worker-metrics-url",
                "http://worker.example",
                "--output-dir",
                str(tmp_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")


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
    manifest = tmp_path / "validation.json"

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


def test_run_replay_validation_fails_when_artifact_index_is_not_written(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    def _run(command):
        if any(str(part).endswith("fetch_replay_state_report.py") for part in command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"projection_checksums": {"execution": "a" * 64}}))
        return 0, json.dumps({"ok": True}), "", 0.01

    monkeypatch.setattr(run_replay_validation, "_run", _run)
    manifest = tmp_path / "validation.json"

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
                str(tmp_path / "artifact-index.json"),
            ]
        )
        == 1
    )
    capsys.readouterr()
    output = json.loads(manifest.read_text())
    assert output["matched"] is False
    assert output["steps"][-1]["name"] == "artifact_index"
    assert output["steps"][-1]["stderr"].startswith("artifact index step did not create artifact index:")
