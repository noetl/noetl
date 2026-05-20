#!/usr/bin/env python
"""Compare replayed and live projection checksum bundle JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from noetl.server.api.replay import projection_checksum_parity_report


def _load_bundle(path: Path) -> dict[str, str]:
    data: Any = json.loads(path.read_text())
    if isinstance(data, dict) and isinstance(data.get("projection_checksums"), dict):
        data = data["projection_checksums"]
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a checksum object")
    return {str(key): str(value) for key, value in data.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare replayed and live NoETL projection checksum bundles",
    )
    parser.add_argument(
        "--replayed",
        required=True,
        type=Path,
        help="JSON file containing replayed projection_checksums or a raw checksum map",
    )
    parser.add_argument(
        "--live",
        required=True,
        type=Path,
        help="JSON file containing live projection_checksums or a raw checksum map",
    )
    args = parser.parse_args(argv)

    report = projection_checksum_parity_report(
        replayed=_load_bundle(args.replayed),
        live=_load_bundle(args.live),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
