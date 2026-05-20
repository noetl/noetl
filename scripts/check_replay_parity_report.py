#!/usr/bin/env python
"""Compare replayed and live projection checksum bundle JSON files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from noetl.server.api.replay import projection_checksum_parity_report

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_PROJECTION_SURFACES = (
    "execution",
    "stages",
    "frames",
    "commands",
    "business_objects",
    "loops",
)


def _load_bundle(path: Path) -> dict[str, str]:
    data: Any = json.loads(path.read_text())
    if isinstance(data, dict) and isinstance(data.get("projection_checksums"), dict):
        data = data["projection_checksums"]
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a checksum object")
    return {str(key): str(value) for key, value in data.items()}


def _checksum_shape_report(bundle: dict[str, str], *, label: str) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for surface, checksum in sorted(bundle.items()):
        if not _SHA256_RE.fullmatch(checksum):
            failures.append(
                {
                    "bundle": label,
                    "surface": surface,
                    "checksum": checksum,
                    "reason": "checksum must be a lowercase sha256 hex digest",
                }
            )
    return failures


def _surface_shape_report(bundle: dict[str, str], *, label: str) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for surface in REQUIRED_PROJECTION_SURFACES:
        if surface not in bundle:
            failures.append(
                {
                    "bundle": label,
                    "surface": surface,
                    "reason": "missing required projection checksum surface",
                }
            )
    for surface in sorted(set(bundle) - set(REQUIRED_PROJECTION_SURFACES)):
        failures.append(
            {
                "bundle": label,
                "surface": surface,
                "reason": "unknown projection checksum surface",
            }
        )
    return failures


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
    parser.add_argument(
        "--allow-invalid-checksum-shape",
        action="store_true",
        help="Skip lowercase sha256 hex validation for legacy ad-hoc reports",
    )
    args = parser.parse_args(argv)

    replayed = _load_bundle(args.replayed)
    live = _load_bundle(args.live)
    report = projection_checksum_parity_report(
        replayed=replayed,
        live=live,
    )
    surface_failures: list[dict[str, str]] = []
    surface_failures.extend(_surface_shape_report(replayed, label="replayed"))
    surface_failures.extend(_surface_shape_report(live, label="live"))
    if surface_failures:
        report["matched"] = False
        report["surface_shape_failures"] = surface_failures

    shape_failures: list[dict[str, str]] = []
    if not args.allow_invalid_checksum_shape:
        shape_failures.extend(_checksum_shape_report(replayed, label="replayed"))
        shape_failures.extend(_checksum_shape_report(live, label="live"))
    if shape_failures:
        report["matched"] = False
        report["checksum_shape_failures"] = shape_failures
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
