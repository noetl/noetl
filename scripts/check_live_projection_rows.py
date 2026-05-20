#!/usr/bin/env python
"""Validate adapter-exported live projection row artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.build_live_projection_checksums import SURFACE_ROW_KEYS, _load_rows


def _canonical_checksum(value: Any) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _load_artifact(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def validate_live_projection_rows(path: Path) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    artifact = _load_artifact(path)

    if artifact.get("schema_version") != 1:
        failures.append({"field": "schema_version", "reason": "must be 1"})
    if not isinstance(artifact.get("adapter"), str) or not artifact.get("adapter"):
        failures.append({"field": "adapter", "reason": "must be a non-empty string"})
    if isinstance(artifact.get("execution_id"), bool) or not isinstance(artifact.get("execution_id"), int):
        failures.append({"field": "execution_id", "reason": "must be an integer"})
    for field in ("tenant_id", "organization_id", "projection"):
        if not isinstance(artifact.get(field), str) or not artifact.get(field):
            failures.append({"field": field, "reason": "must be a non-empty string"})
    if not _valid_timestamp(artifact.get("exported_at")):
        failures.append({"field": "exported_at", "reason": "must be an ISO-8601 timestamp"})

    try:
        rows = _load_rows(path)
    except ValueError as exc:
        failures.append({"field": "rows", "reason": str(exc)})
        rows = {surface: [] for surface in SURFACE_ROW_KEYS}

    row_counts = artifact.get("row_counts")
    if not isinstance(row_counts, dict):
        failures.append({"field": "row_counts", "reason": "must be an object"})
    else:
        unknown_counts = sorted(set(row_counts) - set(SURFACE_ROW_KEYS))
        if unknown_counts:
            failures.append(
                {
                    "field": "row_counts",
                    "reason": "unknown row count surfaces",
                    "surfaces": unknown_counts,
                }
            )
        for surface, surface_rows in rows.items():
            value = row_counts.get(surface)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                failures.append(
                    {
                        "field": f"row_counts.{surface}",
                        "reason": "must be a non-negative integer",
                    }
                )
            elif value != len(surface_rows):
                failures.append(
                    {
                        "field": f"row_counts.{surface}",
                        "reason": "does not match exported row count",
                        "expected": len(surface_rows),
                        "actual": value,
                    }
                )

    expected_checksum = _canonical_checksum(rows)
    if artifact.get("rows_checksum") != expected_checksum:
        failures.append(
            {
                "field": "rows_checksum",
                "reason": "does not match canonical rows checksum",
                "expected": expected_checksum,
                "actual": artifact.get("rows_checksum"),
            }
        )

    return {
        "matched": not failures,
        "adapter": artifact.get("adapter"),
        "execution_id": artifact.get("execution_id"),
        "row_counts": {surface: len(rows.get(surface, [])) for surface in SURFACE_ROW_KEYS},
        "rows_checksum": expected_checksum,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate live projection row artifact JSON")
    parser.add_argument("--rows", required=True, type=Path)
    args = parser.parse_args(argv)

    output = validate_live_projection_rows(args.rows)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
