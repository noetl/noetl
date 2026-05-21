#!/usr/bin/env python
"""Validate a complete replay validation evidence bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_fanout_phase6_evidence import validate_fanout_phase6_report
from scripts.check_projector_phase2_evidence import validate_projector_phase2_evidence
from scripts.check_replay_validation_manifest import _load_manifest, _validate_manifest
from scripts.check_storage_phase5_evidence import validate_storage_phase5_evidence
from scripts.check_worker_ipc_phase3_evidence import validate_worker_ipc_phase3_evidence
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
    require_worker_ipc_phase3: bool = False,
    require_storage_phase5: bool = False,
    require_fanout_phase6: bool = False,
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
    phase3_result: dict[str, Any] | None = None
    if require_worker_ipc_phase3:
        phase3_result = validate_worker_ipc_phase3_evidence(
            manifest,
            check_artifacts=True,
            manifest_path=manifest_path,
        )
        if phase3_result.get("matched") is not True:
            failures.append(
                {
                    "field": "phase3_worker_ipc_evidence",
                    "reason": "Phase 3 worker IPC evidence validation failed",
                    "failures": phase3_result.get("failures", []),
                }
            )
    phase5_result: dict[str, Any] | None = None
    if require_storage_phase5:
        phase5_result = validate_storage_phase5_evidence(
            manifest,
            check_artifacts=True,
            manifest_path=manifest_path,
        )
        if phase5_result.get("matched") is not True:
            failures.append(
                {
                    "field": "phase5_storage_evidence",
                    "reason": "Phase 5 storage registry evidence validation failed",
                    "failures": phase5_result.get("failures", []),
                }
            )
    phase6_result: dict[str, Any] | None = None
    if require_fanout_phase6:
        phase6_result = _validate_fanout_phase6_evidence(
            manifest,
            manifest_path=manifest_path,
        )
        if phase6_result.get("matched") is not True:
            failures.append(
                {
                    "field": "phase6_fanout_evidence",
                    "reason": "Phase 6 fan-out/reduce planner evidence validation failed",
                    "failures": phase6_result.get("failures", []),
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
        "phase3_worker_ipc_result": phase3_result,
        "phase5_storage_result": phase5_result,
        "phase6_fanout_result": phase6_result,
        "artifact_index_result": index_result,
        "failures": failures,
    }


def _validate_fanout_phase6_evidence(
    manifest: dict[str, Any],
    *,
    manifest_path: Path,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    artifacts = manifest.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    reports = artifacts.get("fanout_reduce_planner")
    if not isinstance(reports, list) or not reports:
        failures.append(
            {
                "field": "artifacts.fanout_reduce_planner",
                "reason": "Phase 6 evidence requires at least one fan-out/reduce planner report",
            }
        )
        reports = []

    steps = manifest.get("steps")
    step_names = [
        step.get("name")
        for step in (steps if isinstance(steps, list) else [])
        if isinstance(step, dict)
    ]
    if "fanout_reduce_planner_integrity" not in step_names:
        failures.append(
            {
                "field": "steps",
                "reason": "Phase 6 evidence requires a fan-out/reduce planner integrity step",
            }
        )

    report_results: list[dict[str, Any]] = []
    for index, entry in enumerate(reports):
        if not isinstance(entry, dict):
            continue
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value:
            continue
        path = resolve_indexed_path(path_value, index_path=manifest_path)
        try:
            report = json.loads(path.read_text())
            if not isinstance(report, dict):
                raise ValueError(f"{path} must contain a JSON object")
            result = validate_fanout_phase6_report(
                report,
                require_fanout=True,
                require_reduce=True,
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failures.append(
                {
                    "field": f"artifacts.fanout_reduce_planner[{index}].path",
                    "reason": "fan-out/reduce planner report could not be read",
                    "path": path_value,
                    "error": str(exc),
                }
            )
            continue
        report_results.append({"role": entry.get("role"), "path": str(path), "result": result})
        if result.get("matched") is not True:
            failures.append(
                {
                    "field": f"artifacts.fanout_reduce_planner[{index}]",
                    "reason": "fan-out/reduce planner report validation failed",
                    "failures": result.get("failures", []),
                }
            )

    return {
        "matched": not failures,
        "report_results": report_results,
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
    parser.add_argument(
        "--require-worker-ipc-phase3",
        action="store_true",
        help="Require Phase 3 worker IPC metrics evidence in the manifest",
    )
    parser.add_argument(
        "--require-storage-phase5",
        action="store_true",
        help="Require Phase 5 storage backend registry evidence in the manifest",
    )
    parser.add_argument(
        "--require-fanout-phase6",
        action="store_true",
        help="Require Phase 6 fan-out/reduce planner evidence in the manifest",
    )
    args = parser.parse_args(argv)

    output = validate_bundle(
        manifest_path=args.manifest,
        artifact_index_path=args.artifact_index,
        require_matched=not args.allow_failed,
        require_projector_phase2=args.require_projector_phase2,
        require_projection_parity=args.require_projection_parity,
        require_worker_ipc_phase3=args.require_worker_ipc_phase3,
        require_storage_phase5=args.require_storage_phase5,
        require_fanout_phase6=args.require_fanout_phase6,
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
