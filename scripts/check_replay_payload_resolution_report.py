#!/usr/bin/env python
"""Validate replay payload-resolution summary JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from noetl.server.api.replay import replay_payload_resolution_summary

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SUMMARY_FIELDS = (
    "total",
    "resolved",
    "unresolved",
    "unique_refs",
    "all_resolved",
    "checksum",
)


def _load_report(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _payload_resolution_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = report.get("payload_resolution")
    if rows is None and isinstance(report.get("replay"), dict):
        rows = report["replay"].get("payload_resolution")
    if rows is None:
        raise ValueError("report does not contain payload_resolution")
    if not isinstance(rows, list):
        raise ValueError("payload_resolution must be a list")
    return rows


def _row_shape_failures(rows: list[Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            failures.append(
                {
                    "index": index,
                    "reason": "payload_resolution row must be an object",
                    "supplied_type": type(row).__name__,
                }
            )
            continue
        resolution = row.get("resolution")
        if not isinstance(resolution, dict):
            failures.append(
                {
                    "index": index,
                    "scope": row.get("scope"),
                    "reason": "payload_resolution row resolution must be an object",
                    "supplied_type": type(resolution).__name__,
                }
            )
    return failures


def _checksum_shape_failures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        resolution = row.get("resolution")
        if not isinstance(resolution, dict):
            continue
        checksum = resolution.get("checksum")
        if checksum is None:
            continue
        if not _SHA256_RE.fullmatch(str(checksum)):
            failures.append(
                {
                    "index": index,
                    "scope": row.get("scope"),
                    "ref": resolution.get("ref"),
                    "checksum": checksum,
                    "reason": "payload checksum must be a lowercase sha256 hex digest",
                }
            )
    return failures


def _summary_shape_failures(summary: Any) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if summary is None:
        return failures
    if not isinstance(summary, dict):
        return [
            {
                "field": "payload_resolution_summary",
                "reason": "payload_resolution_summary must be an object",
                "supplied_type": type(summary).__name__,
            }
        ]

    for field in SUMMARY_FIELDS:
        if field not in summary:
            failures.append(
                {
                    "field": f"payload_resolution_summary.{field}",
                    "reason": "missing required summary field",
                }
            )
    for field in sorted(set(summary) - set(SUMMARY_FIELDS)):
        failures.append(
            {
                "field": f"payload_resolution_summary.{field}",
                "reason": "unknown summary field",
            }
        )
    for field in ("total", "resolved", "unresolved", "unique_refs"):
        value = summary.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            failures.append(
                {
                    "field": f"payload_resolution_summary.{field}",
                    "reason": "must be a non-negative integer",
                    "supplied": value,
                }
            )
    if not isinstance(summary.get("all_resolved"), bool):
        failures.append(
            {
                "field": "payload_resolution_summary.all_resolved",
                "reason": "must be a boolean",
                "supplied": summary.get("all_resolved"),
            }
        )
    checksum = summary.get("checksum")
    if not isinstance(checksum, str) or not _SHA256_RE.fullmatch(checksum):
        failures.append(
            {
                "field": "payload_resolution_summary.checksum",
                "reason": "checksum must be a lowercase sha256 hex digest",
                "supplied": checksum,
            }
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate NoETL replay payload-resolution report JSON",
    )
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="Replay state JSON containing payload_resolution and optional payload_resolution_summary",
    )
    args = parser.parse_args(argv)

    report = _load_report(args.report)
    rows = _payload_resolution_rows(report)
    row_shape_failures = _row_shape_failures(rows)
    if row_shape_failures:
        output = {
            "matched": False,
            "reason": "payload_resolution row shape mismatch",
            "row_shape_failures": row_shape_failures,
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 1

    checksum_shape_failures = _checksum_shape_failures(rows)
    if checksum_shape_failures:
        output = {
            "matched": False,
            "reason": "payload checksum shape mismatch",
            "checksum_shape_failures": checksum_shape_failures,
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 1

    computed_summary = replay_payload_resolution_summary(rows)
    supplied_summary = report.get("payload_resolution_summary")
    summary_shape_failures = _summary_shape_failures(supplied_summary)
    if summary_shape_failures:
        output = {
            "matched": False,
            "reason": "payload_resolution_summary shape mismatch",
            "summary_shape_failures": summary_shape_failures,
            "computed": computed_summary,
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 1
    if supplied_summary is not None and supplied_summary.get("checksum") != computed_summary["checksum"]:
        output = {
            "matched": False,
            "reason": "payload_resolution_summary checksum mismatch",
            "supplied": supplied_summary,
            "computed": computed_summary,
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 1

    output = {
        "matched": bool(computed_summary["all_resolved"]),
        "summary": computed_summary,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
