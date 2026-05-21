from scripts.replay_validation_artifacts import artifact_roles, phase_artifact_roles


def test_artifact_roles_ignores_malformed_entries():
    artifacts = {
        "projector_summaries": [
            {"role": "projector_summary_1", "path": "summary.json"},
            {"role": "", "path": "missing-role.json"},
            {"path": "no-role.json"},
            "not-an-entry",
        ]
    }

    assert artifact_roles(artifacts, "projector_summaries") == ["projector_summary_1"]


def test_phase_artifact_roles_collects_unique_sorted_roles():
    artifacts = {
        "projector_summaries": [{"role": "projector_summary_1"}],
        "worker_metrics": [{"role": "worker_metrics_1"}],
        "storage_backend_registry": [{"role": "storage_backend_registry"}],
        "fanout_reduce_planner": [{"role": "fanout_reduce_planner"}],
    }

    assert phase_artifact_roles(artifacts) == [
        "fanout_reduce_planner",
        "projector_summary_1",
        "storage_backend_registry",
        "worker_metrics_1",
    ]


def test_phase_artifact_roles_can_limit_fields():
    artifacts = {
        "projector_summaries": [{"role": "projector_summary_1"}],
        "worker_metrics": [{"role": "worker_metrics_1"}],
    }

    assert phase_artifact_roles(artifacts, fields=("worker_metrics",)) == [
        "worker_metrics_1"
    ]
