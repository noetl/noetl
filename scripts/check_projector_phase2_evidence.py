#!/usr/bin/env python
"""Validate Phase 2 projector evidence in a replay validation manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.check_replay_validation_manifest import _load_manifest, _validate_manifest
from scripts.replay_validation_artifacts import manifest_artifacts, manifest_step_names


def validate_projector_phase2_evidence(
    manifest: dict[str, Any],
    *,
    require_projection_parity: bool,
    check_artifacts: bool,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    base = _validate_manifest(
        manifest,
        require_matched=True,
        check_artifacts=check_artifacts,
        manifest_path=manifest_path,
    )
    failures: list[dict[str, Any]] = list(base.get("failures", []))
    artifacts = manifest_artifacts(manifest)
    projector_summaries = artifacts.get("projector_summaries")
    if not isinstance(projector_summaries, list) or not projector_summaries:
        failures.append(
            {
                "field": "artifacts.projector_summaries",
                "reason": "Phase 2 projector evidence requires at least one projector summary artifact",
            }
        )

    names = manifest_step_names(manifest)
    if not any(name.startswith("projector_summary_") and name.endswith("_integrity") for name in names):
        failures.append(
            {
                "field": "steps",
                "reason": "Phase 2 projector evidence requires projector summary integrity checks",
            }
        )
    if require_projection_parity:
        if "projection_parity" not in names:
            failures.append(
                {
                    "field": "steps",
                    "reason": "Phase 2 projector evidence requires projection_parity step",
                }
            )
        elif any(
            isinstance(step, dict)
            and step.get("name") == "projection_parity"
            and step.get("skipped") is True
            for step in manifest.get("steps", [])
        ):
            failures.append(
                {
                    "field": "steps.projection_parity",
                    "reason": "Phase 2 projector evidence requires projection_parity to run",
                }
            )

    return {"matched": not failures, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 2 projector evidence manifest")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--require-projection-parity",
        action="store_true",
        help="Require a non-skipped projection_parity step",
    )
    parser.add_argument("--check-artifacts", action="store_true")
    args = parser.parse_args(argv)

    output = validate_projector_phase2_evidence(
        _load_manifest(args.manifest),
        require_projection_parity=args.require_projection_parity,
        check_artifacts=args.check_artifacts,
        manifest_path=args.manifest,
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
