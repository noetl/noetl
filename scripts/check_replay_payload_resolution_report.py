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
    return [dict(row) for row in rows if isinstance(row, dict)]


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
    supplied_summary = report.get("payload_resolution_summary") or {}
    if supplied_summary and supplied_summary.get("checksum") != computed_summary["checksum"]:
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
