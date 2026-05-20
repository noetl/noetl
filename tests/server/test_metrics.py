from __future__ import annotations


def test_append_storage_ipc_metrics_exports_counters_and_hit_ratio():
    from noetl.server.metrics import append_storage_ipc_metrics

    lines: list[str] = []
    append_storage_ipc_metrics(
        lines,
        {
            "admit_attempts": 2,
            "admit_success": 1,
            "admit_failures": 1,
            "read_attempts": 4,
            "read_hits": 3,
            "read_misses": 1,
            "fallback_reads": 1,
        },
    )
    body = "\n".join(lines)

    assert "noetl_storage_ipc_admit_attempts_total 2" in body
    assert "noetl_storage_ipc_admit_success_total 1" in body
    assert "noetl_storage_ipc_read_hits_total 3" in body
    assert "noetl_storage_ipc_fallback_reads_total 1" in body
    assert "noetl_storage_ipc_read_hit_ratio 0.75" in body


def test_core_batch_metrics_export_is_callable_without_route_state():
    from noetl.server.api.core import get_batch_metrics_snapshot

    snapshot = get_batch_metrics_snapshot()

    assert "accepted_total" in snapshot
    assert "queue_depth" in snapshot
    assert "worker_count" in snapshot


def test_append_frame_backlog_metrics_exports_stage_and_total_gauges():
    from noetl.server.metrics import append_frame_backlog_metrics

    lines: list[str] = []
    append_frame_backlog_metrics(
        lines,
        [
            {"stage_kind": "loop", "status": "PENDING", "count": 3},
            {
                "tenant_id": "tenant-a",
                "organization_id": "org-a",
                "stage_kind": "loop",
                "status": "RUNNING",
                "count": 2,
            },
            {
                "tenant_id": "tenant-b",
                "organization_id": "org-b",
                "stage_kind": "reduce",
                "status": "PENDING",
                "count": 1,
            },
        ],
    )
    body = "\n".join(lines)

    assert (
        "noetl_frame_backlog_detail_total"
        "{organization_id=\"org-a\",stage_kind=\"loop\",status=\"RUNNING\",tenant_id=\"tenant-a\"} 2"
        in body
    )
    assert "noetl_frame_backlog_total{stage_kind=\"loop\",status=\"PENDING\"} 3" in body
    assert "noetl_frame_backlog_total{stage_kind=\"loop\",status=\"RUNNING\"} 2" in body
    assert "noetl_frame_backlog_total{stage_kind=\"reduce\",status=\"PENDING\"} 1" in body
    assert "noetl_frame_backlog_total{stage_kind=\"all\",status=\"PENDING\"} 4" in body
    assert "noetl_frame_backlog_total{stage_kind=\"all\",status=\"all\"} 6" in body
