#!/usr/bin/env python
"""Validate replay-state report structure and derived checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from noetl.server.api.replay import replay_projection_checksum_bundle


def _load_report(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _canonical_checksum(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def replay_state_checksum(report: Mapping[str, Any]) -> str:
    checksum_input = {
        key: value
        for key, value in report.items()
        if key not in {"checksum", "checksum_algorithm", "projection_checksums"}
    }
    return _canonical_checksum(checksum_input)


def validate_replay_state_report(report: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    supplied_bundle = report.get("projection_checksums")
    if not isinstance(supplied_bundle, dict):
        failures.append({"field": "projection_checksums", "reason": "missing or not an object"})
    else:
        computed_bundle = replay_projection_checksum_bundle(report)
        for surface, computed in computed_bundle.items():
            supplied = supplied_bundle.get(surface)
            if supplied != computed:
                failures.append(
                    {
                        "field": f"projection_checksums.{surface}",
                        "reason": "checksum mismatch",
                        "supplied": supplied,
                        "computed": computed,
                    }
                )

    if report.get("checksum_algorithm") not in {None, "sha256"}:
        failures.append(
            {
                "field": "checksum_algorithm",
                "reason": "unsupported checksum algorithm",
                "supplied": report.get("checksum_algorithm"),
            }
        )
    elif report.get("checksum") is not None:
        computed_checksum = replay_state_checksum(report)
        if report.get("checksum") != computed_checksum:
            failures.append(
                {
                    "field": "checksum",
                    "reason": "checksum mismatch",
                    "supplied": report.get("checksum"),
                    "computed": computed_checksum,
                }
            )

    snapshot = report.get("replay_snapshot")
    if snapshot is not None:
        if not isinstance(snapshot, dict):
            failures.append({"field": "replay_snapshot", "reason": "must be an object"})
        else:
            snapshot_version = snapshot.get("version")
            last_event_id = report.get("last_event_id")
            if snapshot_version is None:
                failures.append({"field": "replay_snapshot.version", "reason": "missing"})
            elif last_event_id is not None and int(snapshot_version) > int(last_event_id):
                failures.append(
                    {
                        "field": "replay_snapshot.version",
                        "reason": "snapshot version is after replay last_event_id",
                        "snapshot_version": snapshot_version,
                        "last_event_id": last_event_id,
                    }
                )

            state_digest = report.get("upcaster_registry_digest")
            snapshot_meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
            snapshot_digest = snapshot_meta.get("upcaster_registry_digest")
            if snapshot_digest is not None and state_digest is not None and snapshot_digest != state_digest:
                failures.append(
                    {
                        "field": "replay_snapshot.meta.upcaster_registry_digest",
                        "reason": "snapshot registry digest differs from replay state",
                        "snapshot": snapshot_digest,
                        "state": state_digest,
                    }
                )

    return {"matched": not failures, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate NoETL replay-state report JSON",
    )
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="Replay state JSON returned by /api/replay/state",
    )
    args = parser.parse_args(argv)

    output = validate_replay_state_report(_load_report(args.report))
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
