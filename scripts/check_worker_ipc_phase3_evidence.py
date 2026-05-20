#!/usr/bin/env python
"""Validate Phase 3 worker IPC evidence in a replay validation manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.check_worker_ipc_metrics import validate_worker_ipc_metrics
from scripts.package_replay_validation_artifacts import resolve_indexed_path


def _load_manifest(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _resolve(value: str, *, manifest_path: Path | None) -> Path:
    if manifest_path is None:
        return Path(value)
    return resolve_indexed_path(value, index_path=manifest_path)


def validate_worker_ipc_phase3_evidence(
    manifest: dict[str, Any],
    *,
    check_artifacts: bool = False,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    artifacts = manifest.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    worker_metrics = artifacts.get("worker_metrics")
    if not isinstance(worker_metrics, list) or not worker_metrics:
        failures.append(
            {
                "field": "artifacts.worker_metrics",
                "reason": "Phase 3 IPC evidence requires at least one worker metrics artifact",
            }
        )
        worker_metrics = []

    steps = manifest.get("steps")
    step_names = [
        step.get("name")
        for step in (steps if isinstance(steps, list) else [])
        if isinstance(step, dict)
    ]
    if not any(
        isinstance(name, str)
        and name.startswith("worker_metrics_")
        and name.endswith("_integrity")
        for name in step_names
    ):
        failures.append(
            {
                "field": "steps",
                "reason": "Phase 3 IPC evidence requires worker metrics integrity checks",
            }
        )

    metric_results: list[dict[str, Any]] = []
    if check_artifacts:
        for index, entry in enumerate(worker_metrics):
            if not isinstance(entry, dict):
                continue
            path_value = entry.get("path")
            if not isinstance(path_value, str) or not path_value:
                continue
            path = _resolve(path_value, manifest_path=manifest_path)
            try:
                result = validate_worker_ipc_metrics(path.read_text())
            except OSError as exc:
                failures.append(
                    {
                        "field": f"artifacts.worker_metrics[{index}].path",
                        "reason": "worker metrics artifact could not be read",
                        "path": path_value,
                        "error": str(exc),
                    }
                )
                continue
            metric_results.append({"role": entry.get("role"), "path": str(path), "result": result})
            if result.get("matched") is not True:
                failures.append(
                    {
                        "field": f"artifacts.worker_metrics[{index}]",
                        "reason": "worker metrics IPC evidence validation failed",
                        "failures": result.get("failures", []),
                    }
                )

    return {
        "matched": not failures,
        "metric_results": metric_results,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 3 worker IPC evidence")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--check-artifacts", action="store_true")
    args = parser.parse_args(argv)

    output = validate_worker_ipc_phase3_evidence(
        _load_manifest(args.manifest),
        check_artifacts=args.check_artifacts,
        manifest_path=args.manifest,
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
