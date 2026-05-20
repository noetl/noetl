#!/usr/bin/env python
"""Validate replay-state report structure and derived checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from noetl.server.api.replay import replay_projection_checksum_bundle

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_TOP_LEVEL_FIELDS = (
    "tenant_id",
    "organization_id",
    "execution_id",
    "projection",
    "upcaster_registry_digest",
    "event_count",
    "last_event_id",
    "last_event_type",
    "checksum_algorithm",
    "checksum",
    "projection_checksums",
)


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


def _validate_digest_shape(
    failures: list[dict[str, Any]],
    *,
    field: str,
    value: Any,
) -> None:
    if value is None:
        return
    if not _SHA256_RE.fullmatch(str(value)):
        failures.append(
            {
                "field": field,
                "reason": "digest must be a lowercase sha256 hex value",
                "supplied": value,
            }
        )


def _validate_int_field(
    failures: list[dict[str, Any]],
    *,
    field: str,
    value: Any,
    required: bool = True,
    minimum: int | None = None,
) -> int | None:
    if value is None:
        if required:
            failures.append({"field": field, "reason": "must be an integer"})
        return None
    if isinstance(value, bool):
        failures.append({"field": field, "reason": "must be an integer", "supplied": value})
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        failures.append({"field": field, "reason": "must be an integer", "supplied": value})
        return None
    if minimum is not None and parsed < minimum:
        failures.append(
            {
                "field": field,
                "reason": f"must be >= {minimum}",
                "supplied": value,
            }
        )
    return parsed


def _validate_string_field(
    failures: list[dict[str, Any]],
    *,
    field: str,
    value: Any,
    required: bool = True,
) -> None:
    if value is None:
        if required:
            failures.append({"field": field, "reason": "must be a non-empty string"})
        return
    if not isinstance(value, str) or not value:
        failures.append(
            {
                "field": field,
                "reason": "must be a non-empty string",
                "supplied": value,
            }
        )


def validate_replay_state_report(report: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in report:
            failures.append({"field": field, "reason": "missing required replay state field"})

    for field in ("tenant_id", "organization_id", "projection", "last_event_type"):
        _validate_string_field(failures, field=field, value=report.get(field))
    _validate_int_field(failures, field="execution_id", value=report.get("execution_id"), minimum=0)
    _validate_int_field(failures, field="event_count", value=report.get("event_count"), minimum=0)
    last_event_id = _validate_int_field(
        failures,
        field="last_event_id",
        value=report.get("last_event_id"),
        required=False,
        minimum=0,
    )

    _validate_digest_shape(
        failures,
        field="upcaster_registry_digest",
        value=report.get("upcaster_registry_digest"),
    )

    supplied_bundle = report.get("projection_checksums")
    if not isinstance(supplied_bundle, dict):
        failures.append({"field": "projection_checksums", "reason": "missing or not an object"})
    else:
        try:
            computed_bundle = replay_projection_checksum_bundle(report)
        except (TypeError, ValueError) as exc:
            failures.append(
                {
                    "field": "projection_checksums",
                    "reason": "could not recompute projection checksums",
                    "error": str(exc),
                }
            )
        else:
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

    if report.get("checksum_algorithm") != "sha256":
        failures.append(
            {
                "field": "checksum_algorithm",
                "reason": "checksum_algorithm must be sha256",
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
            snapshot_version = _validate_int_field(
                failures,
                field="replay_snapshot.version",
                value=snapshot.get("version"),
                minimum=0,
            )
            if snapshot_version is not None and last_event_id is not None and snapshot_version > last_event_id:
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
            _validate_digest_shape(
                failures,
                field="replay_snapshot.meta.upcaster_registry_digest",
                value=snapshot_digest,
            )
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
