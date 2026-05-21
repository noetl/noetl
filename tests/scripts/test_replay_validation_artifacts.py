from scripts.replay_validation_artifacts import (
    artifact_cli_args,
    artifact_entries,
    artifact_result_entry,
    artifact_roles,
    duplicate_artifact_roles,
    indexed_artifact_entries,
    indexed_artifact_paths,
    missing_indexed_artifact_roles,
    phase_artifact_roles,
    result_matched,
)


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


def test_duplicate_artifact_roles_returns_sorted_duplicates():
    artifacts = {
        "projector_summaries": [
            {"role": "projector_summary_2", "path": "summary-2.json"},
            {"role": "projector_summary_1", "path": "summary-1-a.json"},
            {"role": "projector_summary_1", "path": "summary-1-b.json"},
            {"role": "projector_summary_2", "path": "summary-2-b.json"},
        ]
    }

    assert duplicate_artifact_roles(artifacts, "projector_summaries") == [
        "projector_summary_1",
        "projector_summary_2",
    ]


def test_artifact_entries_returns_only_object_entries():
    artifacts = {
        "worker_metrics": [
            {"role": "worker_metrics_1", "path": "worker.prom"},
            "not-an-entry",
        ]
    }

    assert artifact_entries(artifacts, "worker_metrics") == [
        {"role": "worker_metrics_1", "path": "worker.prom"}
    ]


def test_artifact_entries_returns_empty_for_missing_or_non_list_field():
    assert artifact_entries({}, "worker_metrics") == []
    assert artifact_entries({"worker_metrics": "worker.prom"}, "worker_metrics") == []


def test_indexed_artifact_entries_preserves_original_indexes():
    artifacts = {
        "worker_metrics": [
            "not-an-entry",
            {"role": "worker_metrics_1", "path": "worker.prom"},
        ]
    }

    assert indexed_artifact_entries(artifacts, "worker_metrics") == [
        (1, {"role": "worker_metrics_1", "path": "worker.prom"})
    ]


def test_indexed_artifact_paths_preserves_indexes_and_path_values():
    artifacts = {
        "worker_metrics": [
            {"role": "worker_metrics_1", "path": ""},
            {"role": "worker_metrics_2", "path": "worker.prom"},
            {"role": "worker_metrics_3"},
            "not-an-entry",
        ]
    }

    assert indexed_artifact_paths(artifacts, "worker_metrics") == [
        (1, {"role": "worker_metrics_2", "path": "worker.prom"}, "worker.prom")
    ]


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


def test_missing_indexed_artifact_roles_returns_unmatched_required_roles():
    assert missing_indexed_artifact_roles(
        ["projector_summary_1", "worker_metrics_1"],
        ["worker_metrics_1"],
    ) == ["projector_summary_1"]


def test_missing_indexed_artifact_roles_treats_malformed_index_roles_as_empty():
    assert missing_indexed_artifact_roles(
        ["projector_summary_1"],
        "projector_summary_1",
    ) == ["projector_summary_1"]


def test_artifact_result_entry_preserves_role_path_and_result():
    result = {"matched": True}

    assert artifact_result_entry(
        {"role": "worker_metrics_1"},
        path="/tmp/worker.prom",
        result=result,
    ) == {
        "role": "worker_metrics_1",
        "path": "/tmp/worker.prom",
        "result": result,
    }


def test_result_matched_requires_explicit_true_match():
    assert result_matched({"matched": True}) is True
    assert result_matched({"matched": False}) is False
    assert result_matched({"matched": "true"}) is False
    assert result_matched(None) is False


def test_artifact_cli_args_renders_role_path_pairs():
    assert artifact_cli_args(
        [
            {"role": "projector_summary_1", "path": "summary.json"},
            {"role": "worker_metrics_1", "path": "worker.prom"},
        ]
    ) == [
        "--artifact",
        "projector_summary_1=summary.json",
        "--artifact",
        "worker_metrics_1=worker.prom",
    ]


def test_artifact_cli_args_ignores_incomplete_entries():
    assert artifact_cli_args(
        [
            {"role": "projector_summary_1"},
            {"path": "worker.prom"},
            {"role": "", "path": "missing-role.json"},
        ]
    ) == []
