#!/usr/bin/env python
"""Build live projection checksum bundles from adapter-exported JSON rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from noetl.server.api.replay import live_projection_checksum_bundle

SURFACE_ROW_KEYS = {
    "execution": "execution_rows",
    "stages": "stage_rows",
    "frames": "frame_rows",
    "commands": "command_rows",
    "business_objects": "business_object_rows",
    "loops": "loop_rows",
}


def _load_rows(path: Path) -> dict[str, list[dict[str, Any]]]:
    data: Any = json.loads(path.read_text())
    if isinstance(data, dict) and isinstance(data.get("rows"), dict):
        data = data["rows"]
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object of live projection rows")

    rows: dict[str, list[dict[str, Any]]] = {}
    for surface in SURFACE_ROW_KEYS:
        value = data.get(surface, [])
        if not isinstance(value, list):
            raise ValueError(f"{path}: {surface} must be a list")
        if not all(isinstance(row, dict) for row in value):
            raise ValueError(f"{path}: {surface} rows must be objects")
        rows[surface] = value

    unknown = sorted(set(data) - set(SURFACE_ROW_KEYS))
    if unknown:
        raise ValueError(f"{path}: unknown live projection row surfaces: {', '.join(unknown)}")
    return rows


def build_live_projection_checksums(rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    bundle = live_projection_checksum_bundle(
        execution_rows=rows["execution"],
        stage_rows=rows["stages"],
        frame_rows=rows["frames"],
        command_rows=rows["commands"],
        business_object_rows=rows["business_objects"],
        loop_rows=rows["loops"],
    )
    return {
        "projection_checksums": bundle,
        "row_counts": {surface: len(values) for surface, values in rows.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build NoETL live projection checksum bundle from exported row JSON",
    )
    parser.add_argument("--rows", required=True, type=Path, help="Live projection row export JSON")
    parser.add_argument("--output", required=True, type=Path, help="Output checksum bundle JSON")
    args = parser.parse_args(argv)

    output = build_live_projection_checksums(_load_rows(args.rows))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "row_counts": output["row_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
