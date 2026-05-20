#!/usr/bin/env python
"""Validate replay validation run manifest JSON."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_CONFIG_FIELDS = (
    "base_url",
    "execution_id",
    "tenant_id",
    "organization_id",
    "projection",
    "limit",
    "resolve_payloads",
)
REQUIRED_STEP_ORDER = ("fetch", "state_integrity")
OPTIONAL_STEP_NAMES = ("live_checksums", "projection_parity", "payload_resolution")


def _load_manifest(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _validate_manifest(manifest: dict[str, Any], *, require_matched: bool, check_artifacts: bool) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    if require_matched and manifest.get("matched") is not True:
        failures.append({"field": "matched", "reason": "manifest must be matched=true"})
    elif not isinstance(manifest.get("matched"), bool):
        failures.append({"field": "matched", "reason": "must be a boolean"})

    for field in ("started_at", "finished_at"):
        if not _valid_timestamp(manifest.get(field)):
            failures.append({"field": field, "reason": "must be an ISO-8601 timestamp"})

    config = manifest.get("config")
    if not isinstance(config, dict):
        failures.append({"field": "config", "reason": "must be an object"})
    else:
        for field in REQUIRED_CONFIG_FIELDS:
            if field not in config:
                failures.append({"field": f"config.{field}", "reason": "missing required config field"})
        if isinstance(config.get("execution_id"), bool) or not isinstance(config.get("execution_id"), int):
            failures.append({"field": "config.execution_id", "reason": "must be an integer"})
        if isinstance(config.get("limit"), bool) or not isinstance(config.get("limit"), int):
            failures.append({"field": "config.limit", "reason": "must be an integer"})
        if not isinstance(config.get("resolve_payloads"), bool):
            failures.append({"field": "config.resolve_payloads", "reason": "must be a boolean"})
        if config.get("live_checksums") and config.get("live_rows"):
            failures.append(
                {
                    "field": "config.live_checksums",
                    "reason": "live_checksums and live_rows are mutually exclusive",
                }
            )

    artifacts = manifest.get("artifacts")
    if artifacts is not None and not isinstance(artifacts, dict):
        failures.append({"field": "artifacts", "reason": "must be an object"})
    elif isinstance(artifacts, dict) and check_artifacts:
        for field, value in artifacts.items():
            if value is None:
                continue
            if not isinstance(value, str) or not value:
                failures.append({"field": f"artifacts.{field}", "reason": "artifact path must be a string"})
            elif not Path(value).exists():
                failures.append({"field": f"artifacts.{field}", "reason": "artifact path does not exist", "path": value})

    steps = manifest.get("steps")
    if not isinstance(steps, list):
        failures.append({"field": "steps", "reason": "must be a list"})
        steps = []

    step_names: list[str] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            failures.append({"field": f"steps[{index}]", "reason": "step must be an object"})
            continue
        name = step.get("name")
        if not isinstance(name, str) or not name:
            failures.append({"field": f"steps[{index}].name", "reason": "must be a non-empty string"})
        else:
            step_names.append(name)
        if step.get("skipped") is True:
            continue
        if isinstance(step.get("returncode"), bool) or not isinstance(step.get("returncode"), int):
            failures.append({"field": f"steps[{index}].returncode", "reason": "must be an integer"})
        elif require_matched and step.get("returncode") != 0:
            failures.append({"field": f"steps[{index}].returncode", "reason": "successful manifests require returncode=0"})
        duration = step.get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
            failures.append({"field": f"steps[{index}].duration_seconds", "reason": "must be a non-negative number"})
        command = step.get("command")
        if command is not None and not (isinstance(command, list) and all(isinstance(part, str) for part in command)):
            failures.append({"field": f"steps[{index}].command", "reason": "must be a list of strings"})

    for expected_index, name in enumerate(REQUIRED_STEP_ORDER):
        if len(step_names) <= expected_index or step_names[expected_index] != name:
            failures.append({"field": "steps", "reason": f"required step {name} missing or out of order"})
    for name in step_names:
        if name not in (*REQUIRED_STEP_ORDER, *OPTIONAL_STEP_NAMES, "fetch_artifact"):
            failures.append({"field": "steps", "reason": "unknown validation step", "step": name})

    return {"matched": not failures, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate replay validation manifest JSON")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--allow-failed", action="store_true", help="Allow matched=false manifests")
    parser.add_argument("--check-artifacts", action="store_true", help="Require artifact paths to exist")
    args = parser.parse_args(argv)

    output = _validate_manifest(
        _load_manifest(args.manifest),
        require_matched=not args.allow_failed,
        check_artifacts=args.check_artifacts,
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
