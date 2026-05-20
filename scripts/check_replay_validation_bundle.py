#!/usr/bin/env python
"""Validate a complete replay validation evidence bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.check_projector_phase2_evidence import validate_projector_phase2_evidence
from scripts.check_replay_validation_manifest import _load_manifest, _validate_manifest
from scripts.package_replay_validation_artifacts import (
    resolve_indexed_path,
    validate_artifact_index,
)


def _artifact_index_from_manifest(manifest: dict[str, Any]) -> str | None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    value = artifacts.get("artifact_index")
    if not isinstance(value, str) or not value:
        return None
    return value


def validate_bundle(
    *,
    manifest_path: Path,
    artifact_index_path: Path | None = None,
    require_matched: bool = True,
    require_projector_phase2: bool = False,
    require_projection_parity: bool = False,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    manifest = _load_manifest(manifest_path)

    manifest_result = _validate_manifest(
        manifest,
        require_matched=require_matched,
        check_artifacts=True,
        manifest_path=manifest_path,
    )
    if manifest_result.get("matched") is not True:
        failures.append(
            {
                "field": "manifest",
                "reason": "manifest validation failed",
                "failures": manifest_result.get("failures", []),
            }
        )
    phase2_result: dict[str, Any] | None = None
    if require_projector_phase2:
        phase2_result = validate_projector_phase2_evidence(
            manifest,
            require_projection_parity=require_projection_parity,
            check_artifacts=True,
            manifest_path=manifest_path,
        )
        if phase2_result.get("matched") is not True:
            failures.append(
                {
                    "field": "phase2_projector_evidence",
                    "reason": "Phase 2 projector evidence validation failed",
                    "failures": phase2_result.get("failures", []),
                }
            )

    manifest_index = _artifact_index_from_manifest(manifest)
    if artifact_index_path is None:
        if manifest_index is None:
            failures.append(
                {
                    "field": "artifacts.artifact_index",
                    "reason": "manifest does not reference an artifact index",
                }
            )
            resolved_index_path = None
        else:
            resolved_index_path = resolve_indexed_path(
                manifest_index,
                index_path=manifest_path,
            )
    else:
        resolved_index_path = artifact_index_path
        if manifest_index is not None:
            manifest_resolved_index = resolve_indexed_path(
                manifest_index,
                index_path=manifest_path,
            )
            if manifest_resolved_index != artifact_index_path.resolve():
                failures.append(
                    {
                        "field": "artifact_index",
                        "reason": "artifact index argument differs from manifest reference",
                        "manifest_artifact_index": manifest_index,
                        "artifact_index": str(artifact_index_path),
                    }
                )

    index_result: dict[str, Any] | None = None
    if resolved_index_path is not None:
        try:
            index_result = validate_artifact_index(resolved_index_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failures.append(
                {
                    "field": "artifact_index",
                    "reason": "artifact index could not be validated",
                    "path": str(resolved_index_path),
                    "error": str(exc),
                }
            )
        else:
            if index_result.get("matched") is not True:
                failures.append(
                    {
                        "field": "artifact_index",
                        "reason": "artifact index validation failed",
                        "path": str(resolved_index_path),
                        "failures": index_result.get("failures", []),
                    }
                )

    return {
        "matched": not failures,
        "manifest": str(manifest_path),
        "artifact_index": str(resolved_index_path) if resolved_index_path else None,
        "manifest_result": manifest_result,
        "phase2_projector_result": phase2_result,
        "artifact_index_result": index_result,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a replay validation evidence bundle")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--artifact-index", type=Path)
    parser.add_argument("--allow-failed", action="store_true", help="Allow matched=false manifests")
    parser.add_argument(
        "--require-projector-phase2",
        action="store_true",
        help="Require Phase 2 projector summary evidence in the manifest",
    )
    parser.add_argument(
        "--require-projection-parity",
        action="store_true",
        help="When requiring Phase 2 projector evidence, require projection parity to run",
    )
    args = parser.parse_args(argv)

    output = validate_bundle(
        manifest_path=args.manifest,
        artifact_index_path=args.artifact_index,
        require_matched=not args.allow_failed,
        require_projector_phase2=args.require_projector_phase2,
        require_projection_parity=args.require_projection_parity,
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
