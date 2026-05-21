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
from scripts.check_replay_fanout_reduce_report import validate_replay_fanout_reduce_report
from scripts.check_replay_validation_manifest import _load_manifest, _validate_manifest
from scripts.check_storage_phase5_evidence import validate_storage_phase5_evidence
from scripts.check_worker_ipc_phase3_evidence import validate_worker_ipc_phase3_evidence
from scripts.package_replay_validation_artifacts import (
    resolve_indexed_path,
    validate_artifact_index,
)
from scripts.replay_validation_artifacts import (
    artifact_index_path_value,
    artifact_result_entry,
    indexed_artifact_entries,
    indexed_artifact_paths,
    manifest_artifacts,
    manifest_step_names,
    missing_indexed_artifact_roles,
    phase_artifact_roles,
    result_matched,
)


def _required_index_roles(
    manifest: dict[str, Any],
    *,
    require_projector_phase2: bool,
    require_worker_ipc_phase3: bool,
    require_storage_phase5: bool,
    require_fanout_phase6: bool,
) -> list[str]:
    artifacts = manifest_artifacts(manifest)
    if not artifacts:
        return []
    fields: list[str] = []
    if require_projector_phase2:
        fields.append("projector_summaries")
    if require_worker_ipc_phase3:
        fields.append("worker_metrics")
    if require_storage_phase5:
        fields.append("storage_backend_registry")
    if require_fanout_phase6:
        fields.append("fanout_reduce_planner")
    return phase_artifact_roles(artifacts, fields=tuple(fields))


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
    require_replay_fanout_phase6: bool = False,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    manifest = _load_manifest(manifest_path)

    manifest_result = _validate_manifest(
        manifest,
        require_matched=require_matched,
        check_artifacts=True,
        manifest_path=manifest_path,
    )
    if not result_matched(manifest_result):
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
        if not result_matched(phase2_result):
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
        if not result_matched(phase3_result):
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
        if not result_matched(phase5_result):
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
        if not result_matched(phase6_result):
            failures.append(
                {
                    "field": "phase6_fanout_evidence",
                    "reason": "Phase 6 fan-out/reduce planner evidence validation failed",
                    "failures": phase6_result.get("failures", []),
                }
            )
    replay_phase6_result: dict[str, Any] | None = None
    if require_replay_fanout_phase6:
        replay_phase6_result = _validate_replay_fanout_phase6_evidence(
            manifest,
            manifest_path=manifest_path,
        )
        if not result_matched(replay_phase6_result):
            failures.append(
                {
                    "field": "phase6_replay_fanout_evidence",
                    "reason": "Phase 6 replay fan-out/reduce evidence validation failed",
                    "failures": replay_phase6_result.get("failures", []),
                }
            )

    manifest_index = artifact_index_path_value(manifest)
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
            if not result_matched(index_result):
                failures.append(
                    {
                        "field": "artifact_index",
                        "reason": "artifact index validation failed",
                        "path": str(resolved_index_path),
                        "failures": index_result.get("failures", []),
                    }
                )
            required_index_roles = _required_index_roles(
                manifest,
                require_projector_phase2=require_projector_phase2,
                require_worker_ipc_phase3=require_worker_ipc_phase3,
                require_storage_phase5=require_storage_phase5,
                require_fanout_phase6=require_fanout_phase6,
            )
            missing_index_roles = missing_indexed_artifact_roles(
                required_index_roles,
                index_result.get("roles"),
            )
            if missing_index_roles:
                failures.append(
                    {
                        "field": "artifact_index",
                        "reason": "artifact index missing required phase evidence roles",
                        "roles": missing_index_roles,
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
        "phase6_replay_fanout_result": replay_phase6_result,
        "artifact_index_result": index_result,
        "failures": failures,
    }


def _validate_fanout_phase6_evidence(
    manifest: dict[str, Any],
    *,
    manifest_path: Path,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    artifacts = manifest_artifacts(manifest)
    reports = artifacts.get("fanout_reduce_planner")
    if not isinstance(reports, list) or not reports:
        failures.append(
            {
                "field": "artifacts.fanout_reduce_planner",
                "reason": "Phase 6 evidence requires at least one fan-out/reduce planner report",
            }
        )
        reports = []

    step_names = manifest_step_names(manifest)
    if "fanout_reduce_planner_integrity" not in step_names:
        failures.append(
            {
                "field": "steps",
                "reason": "Phase 6 evidence requires a fan-out/reduce planner integrity step",
            }
        )

    report_results: list[dict[str, Any]] = []
    for index, entry, path_value in indexed_artifact_paths(
        {"fanout_reduce_planner": reports},
        "fanout_reduce_planner",
    ):
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
        report_results.append(artifact_result_entry(entry, path=str(path), result=result))
        if not result_matched(result):
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


def _validate_replay_fanout_phase6_evidence(
    manifest: dict[str, Any],
    *,
    manifest_path: Path,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    artifacts = manifest_artifacts(manifest)
    replay_path = artifacts.get("replay")
    if not isinstance(replay_path, str) or not replay_path:
        failures.append(
            {
                "field": "artifacts.replay",
                "reason": "Phase 6 replay evidence requires a replay artifact",
            }
        )
        return {"matched": False, "result": None, "failures": failures}

    step_names = manifest_step_names(manifest)
    if "replay_fanout_reduce_integrity" not in step_names:
        failures.append(
            {
                "field": "steps",
                "reason": "Phase 6 replay evidence requires replay_fanout_reduce_integrity step",
            }
        )

    path = resolve_indexed_path(replay_path, index_path=manifest_path)
    try:
        report = json.loads(path.read_text())
        if not isinstance(report, dict):
            raise ValueError(f"{path} must contain a JSON object")
        result = validate_replay_fanout_reduce_report(report)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        failures.append(
            {
                "field": "artifacts.replay",
                "reason": "replay artifact could not be read for Phase 6 evidence",
                "path": replay_path,
                "error": str(exc),
            }
        )
        return {"matched": False, "result": None, "failures": failures}

    if not result_matched(result):
        failures.append(
            {
                "field": "artifacts.replay",
                "reason": "replay fan-out/reduce metadata validation failed",
                "failures": result.get("failures", []),
            }
        )

    return {
        "matched": not failures,
        "result": result,
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
    parser.add_argument(
        "--require-replay-fanout-phase6",
        action="store_true",
        help="Require Phase 6 fan-out/reduce metadata in the replay artifact",
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
        require_replay_fanout_phase6=args.require_replay_fanout_phase6,
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
