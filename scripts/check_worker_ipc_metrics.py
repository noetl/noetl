#!/usr/bin/env python
"""Validate worker Prometheus metrics for Phase 3 IPC evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_METRICS = {
    "noetl_storage_ipc_admit_attempts_total",
    "noetl_storage_ipc_admit_success_total",
    "noetl_storage_ipc_admit_failures_total",
    "noetl_storage_ipc_read_attempts_total",
    "noetl_storage_ipc_read_hits_total",
    "noetl_storage_ipc_read_misses_total",
    "noetl_storage_ipc_fallback_reads_total",
    "noetl_storage_ipc_read_hit_ratio",
}

DEFAULT_MINIMUMS = {
    "noetl_storage_ipc_admit_success_total": 1.0,
    "noetl_storage_ipc_read_hits_total": 1.0,
    "noetl_storage_ipc_fallback_reads_total": 1.0,
}

DEFAULT_REQUIRED_LABELS = ("worker_id", "node_id")

METRIC_RE = re.compile(
    r"^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+0-9.eE]+)\s*$"
)


def _parse_labels(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    labels: dict[str, str] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        labels[key] = value.strip().strip('"')
    return labels


def parse_prometheus_metrics(body: str) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = METRIC_RE.match(stripped)
        if match is None:
            continue
        samples.append(
            {
                "name": match.group("name"),
                "labels": _parse_labels(match.group("labels")),
                "value": float(match.group("value")),
            }
        )
    return samples


def validate_worker_ipc_metrics(
    body: str,
    *,
    minimums: dict[str, float] | None = None,
    required_labels: tuple[str, ...] = DEFAULT_REQUIRED_LABELS,
) -> dict[str, Any]:
    samples = parse_prometheus_metrics(body)
    by_name: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        by_name.setdefault(sample["name"], []).append(sample)

    failures: list[dict[str, Any]] = []
    for metric_name in sorted(REQUIRED_METRICS):
        if metric_name not in by_name:
            failures.append({"field": metric_name, "reason": "missing required IPC metric"})

    for label in required_labels:
        if not any(sample["labels"].get(label) for sample in samples if sample["name"] in REQUIRED_METRICS):
            failures.append({"field": f"labels.{label}", "reason": "missing required IPC metric label"})

    for metric_name, minimum in (minimums or DEFAULT_MINIMUMS).items():
        total = sum(sample["value"] for sample in by_name.get(metric_name, []))
        if total < minimum:
            failures.append(
                {
                    "field": metric_name,
                    "reason": f"sum must be >= {minimum}",
                    "actual": total,
                }
            )

    return {
        "matched": not failures,
        "metrics": sorted(by_name),
        "sample_count": len(samples),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate worker IPC Prometheus metrics")
    parser.add_argument("--metrics", required=True, type=Path, help="Worker /metrics text artifact")
    parser.add_argument(
        "--allow-zero-activity",
        action="store_true",
        help="Only require metric family/labels, not non-zero hit/fallback counters",
    )
    parser.add_argument(
        "--require-label",
        action="append",
        default=list(DEFAULT_REQUIRED_LABELS),
        help="IPC sample label that must be present at least once",
    )
    args = parser.parse_args(argv)

    output = validate_worker_ipc_metrics(
        args.metrics.read_text(),
        minimums={} if args.allow_zero_activity else DEFAULT_MINIMUMS,
        required_labels=tuple(args.require_label),
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
