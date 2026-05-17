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
