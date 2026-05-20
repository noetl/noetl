#!/usr/bin/env python
"""Build and validate a SHA-256 index for replay validation artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INDEX_SCHEMA_VERSION = 1
REQUIRED_ROLES = ("manifest", "replay", "report")
PAIRED_ROLES = (("live_rows", "live_checksums"),)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _artifact_entry(role: str, path: Path, *, required: bool = True) -> dict[str, Any]:
    exists = path.exists()
    entry: dict[str, Any] = {
        "role": role,
        "path": str(path),
        "required": required,
        "exists": exists,
    }
    if exists:
        entry["size_bytes"] = path.stat().st_size
        entry["sha256"] = _sha256(path)
    return entry


def build_artifact_index(
    *,
    manifest_path: Path,
    extra_artifacts: list[tuple[str, Path]] | None = None,
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    artifacts = manifest.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}

    entries: list[dict[str, Any]] = [_artifact_entry("manifest", manifest_path)]
    for role in ("replay", "live_rows", "live_checksums", "report"):
        value = artifacts.get(role)
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            entries.append(
                {
                    "role": role,
                    "path": value,
                    "required": True,
                    "exists": False,
                    "error": "artifact path is not a non-empty string",
                }
            )
            continue
        path = Path(value)
        if not path.is_absolute():
            path = (manifest_path.parent / path).resolve()
        entries.append(_artifact_entry(role, path))

    for role, path in extra_artifacts or []:
        entries.append(_artifact_entry(role, path))

    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "manifest": str(manifest_path),
        "matched": all(entry.get("exists") for entry in entries if entry.get("required", True)),
        "artifacts": entries,
    }


def validate_artifact_index(index_path: Path) -> dict[str, Any]:
    index = _load_json(index_path)
    failures: list[dict[str, Any]] = []

    if index.get("schema_version") != INDEX_SCHEMA_VERSION:
        failures.append({"field": "schema_version", "reason": f"must be {INDEX_SCHEMA_VERSION}"})
    if not isinstance(index.get("generated_at"), str) or not index.get("generated_at"):
        failures.append({"field": "generated_at", "reason": "must be a non-empty string"})

    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list):
        failures.append({"field": "artifacts", "reason": "must be a list"})
        artifacts = []

    roles: dict[str, int] = {}
    for idx, entry in enumerate(artifacts):
        if not isinstance(entry, dict):
            failures.append({"field": f"artifacts[{idx}]", "reason": "must be an object"})
            continue
        role = entry.get("role")
        if not isinstance(role, str) or not role:
            failures.append({"field": f"artifacts[{idx}].role", "reason": "must be a non-empty string"})
        else:
            roles[role] = roles.get(role, 0) + 1
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value:
            failures.append({"field": f"artifacts[{idx}].path", "reason": "must be a non-empty string"})
            continue
        path = Path(path_value)
        required = bool(entry.get("required", True))
        if required and not path.exists():
            failures.append(
                {
                    "field": f"artifacts[{idx}].path",
                    "reason": "artifact path does not exist",
                    "path": path_value,
                }
            )
            continue
        if not path.exists():
            continue
        size_bytes = entry.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
            failures.append({"field": f"artifacts[{idx}].size_bytes", "reason": "must be a non-negative integer"})
        elif size_bytes != path.stat().st_size:
            failures.append(
                {
                    "field": f"artifacts[{idx}].size_bytes",
                    "reason": "size drift",
                    "expected": size_bytes,
                    "actual": path.stat().st_size,
                }
            )
        actual_sha = _sha256(path)
        if entry.get("sha256") != actual_sha:
            failures.append(
                {
                    "field": f"artifacts[{idx}].sha256",
                    "reason": "sha256 drift",
                    "expected": entry.get("sha256"),
                    "actual": actual_sha,
                }
            )

    for role in REQUIRED_ROLES:
        if roles.get(role, 0) == 0:
            failures.append({"field": "artifacts", "reason": "missing required artifact role", "role": role})
    for role, count in sorted(roles.items()):
        if count > 1:
            failures.append(
                {
                    "field": "artifacts",
                    "reason": "duplicate artifact role",
                    "role": role,
                    "count": count,
                }
            )
    for left, right in PAIRED_ROLES:
        if bool(roles.get(left)) != bool(roles.get(right)):
            failures.append(
                {
                    "field": "artifacts",
                    "reason": "paired artifact roles must appear together",
                    "roles": [left, right],
                }
            )

    matched = not failures and all(
        bool(entry.get("exists"))
        for entry in artifacts
        if isinstance(entry, dict) and entry.get("required", True)
    )
    return {"matched": matched, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or validate replay validation artifact index")
    parser.add_argument("--manifest", type=Path, help="Replay validation manifest JSON")
    parser.add_argument("--output", type=Path, help="Output artifact index JSON")
    parser.add_argument("--check", type=Path, help="Validate an existing artifact index JSON")
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="ROLE=PATH",
        help="Extra artifact to include in the index",
    )
    args = parser.parse_args(argv)

    if args.check:
        output = validate_artifact_index(args.check)
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0 if output["matched"] else 1
    if not args.manifest or not args.output:
        parser.error("--manifest and --output are required unless --check is used")

    extra_artifacts: list[tuple[str, Path]] = []
    for raw in args.artifact:
        if "=" not in raw:
            parser.error("--artifact must be ROLE=PATH")
        role, value = raw.split("=", 1)
        if not role or not value:
            parser.error("--artifact must be ROLE=PATH")
        extra_artifacts.append((role, Path(value)))

    index = build_artifact_index(manifest_path=args.manifest, extra_artifacts=extra_artifacts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "matched": index["matched"]}, sort_keys=True))
    return 0 if index["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
