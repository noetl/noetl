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


def append_storage_ipc_metrics(
    lines: list[str],
    stats: Mapping[str, int | float],
    *,
    labels: Mapping[str, str] | None = None,
) -> None:
    """Append TempStore IPC counters and derived hit ratio to metrics output."""
    label_text = _format_labels(labels or {})
    for key, (metric_name, help_text) in _IPC_COUNTERS.items():
        value = stats.get(key, 0)
        lines.append(f"# HELP {metric_name} {help_text}")
        lines.append(f"# TYPE {metric_name} counter")
        lines.append(f"{metric_name}{label_text} {value}")

    read_attempts = float(stats.get("read_attempts", 0) or 0)
    read_hits = float(stats.get("read_hits", 0) or 0)
    hit_ratio = read_hits / read_attempts if read_attempts > 0 else 0.0
    lines.append("# HELP noetl_storage_ipc_read_hit_ratio IPC cache read hit ratio for this process")
    lines.append("# TYPE noetl_storage_ipc_read_hit_ratio gauge")
    lines.append(f"noetl_storage_ipc_read_hit_ratio{label_text} {hit_ratio}")


def append_frame_backlog_metrics(
    lines: list[str],
    rows: list[Mapping[str, object]],
) -> None:
    """Append frame backlog gauges grouped by status and stage kind."""
    metric_name = "noetl_frame_backlog_total"
    lines.append("# HELP noetl_frame_backlog_total Worker-claimable frame backlog by stage kind and status")
    lines.append("# TYPE noetl_frame_backlog_total gauge")
    totals_by_status: dict[str, int] = {}
    total = 0
    for row in rows:
        stage_kind = str(row.get("stage_kind") or "unknown")
        status = str(row.get("status") or "unknown")
        count = int(row.get("count") or 0)
        total += count
        totals_by_status[status] = totals_by_status.get(status, 0) + count
        labels = _format_labels({"stage_kind": stage_kind, "status": status})
        lines.append(f"{metric_name}{labels} {count}")

    for status, count in sorted(totals_by_status.items()):
        lines.append(f'{metric_name}{{stage_kind="all",status="{_escape_label(status)}"}} {count}')
    lines.append(f'{metric_name}{{stage_kind="all",status="all"}} {total}')


def _format_labels(labels: Mapping[str, str]) -> str:
    filtered = {key: value for key, value in labels.items() if value}
    if not filtered:
        return ""
    body = ",".join(f'{key}="{_escape_label(value)}"' for key, value in sorted(filtered.items()))
    return "{" + body + "}"


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


__all__ = ["append_frame_backlog_metrics", "append_storage_ipc_metrics"]
