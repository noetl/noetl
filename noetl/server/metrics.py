"""Prometheus exposition helpers for NoETL runtime metrics."""

from __future__ import annotations

from typing import Mapping


_IPC_COUNTERS = {
    "admit_attempts": ("noetl_storage_ipc_admit_attempts_total", "Total IPC cache admission attempts"),
    "admit_success": ("noetl_storage_ipc_admit_success_total", "Total successful IPC cache admissions"),
    "admit_failures": ("noetl_storage_ipc_admit_failures_total", "Total failed IPC cache admissions"),
    "read_attempts": ("noetl_storage_ipc_read_attempts_total", "Total IPC cache read attempts"),
    "read_hits": ("noetl_storage_ipc_read_hits_total", "Total IPC cache read hits"),
    "read_misses": ("noetl_storage_ipc_read_misses_total", "Total IPC cache read misses"),
    "fallback_reads": ("noetl_storage_ipc_fallback_reads_total", "Total durable fallback reads after IPC miss or bypass"),
}


def append_storage_ipc_metrics(lines: list[str], stats: Mapping[str, int | float]) -> None:
    """Append TempStore IPC counters and derived hit ratio to metrics output."""
    for key, (metric_name, help_text) in _IPC_COUNTERS.items():
        value = stats.get(key, 0)
        lines.append(f"# HELP {metric_name} {help_text}")
        lines.append(f"# TYPE {metric_name} counter")
        lines.append(f"{metric_name} {value}")

    read_attempts = float(stats.get("read_attempts", 0) or 0)
    read_hits = float(stats.get("read_hits", 0) or 0)
    hit_ratio = read_hits / read_attempts if read_attempts > 0 else 0.0
    lines.append("# HELP noetl_storage_ipc_read_hit_ratio IPC cache read hit ratio for this process")
    lines.append("# TYPE noetl_storage_ipc_read_hit_ratio gauge")
    lines.append(f"noetl_storage_ipc_read_hit_ratio {hit_ratio}")


__all__ = ["append_storage_ipc_metrics"]
