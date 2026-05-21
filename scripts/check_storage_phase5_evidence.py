#!/usr/bin/env python
"""Validate Phase 5 storage backend registry evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.package_replay_validation_artifacts import resolve_indexed_path
from scripts.replay_validation_artifacts import indexed_artifact_entries

REQUIRED_BACKENDS = {"disk", "gcs", "kv", "memory", "s3"}
REQUIRED_CONSUMERS = {
    "result_store",
    "artifact_executor",
    "agent_disk_fallback",
}


def _load_json_object(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _resolve(value: str, *, manifest_path: Path | None) -> Path:
    if manifest_path is None:
        return Path(value)
    return resolve_indexed_path(value, index_path=manifest_path)


def validate_storage_phase5_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validate a storage registry report artifact."""
    failures: list[dict[str, Any]] = []

    backends = report.get("registered_backends")
    backend_names = {str(name).lower() for name in backends} if isinstance(backends, list) else set()
    missing_backends = sorted(REQUIRED_BACKENDS - backend_names)
    if missing_backends:
        failures.append(
            {
                "field": "registered_backends",
                "reason": "missing required built-in backend registrations",
                "missing": missing_backends,
            }
        )

    consumers = report.get("consumer_paths")
    consumers = consumers if isinstance(consumers, dict) else {}
    missing_consumers = [
        name for name in sorted(REQUIRED_CONSUMERS) if consumers.get(name) is not True
    ]
    if missing_consumers:
        failures.append(
            {
                "field": "consumer_paths",
                "reason": "missing required registry-routed consumers",
                "missing": missing_consumers,
            }
        )

    direct_scan = report.get("direct_backend_construction")
    direct_scan = direct_scan if isinstance(direct_scan, dict) else {}
    if direct_scan.get("matched") is not True:
        failures.append(
            {
                "field": "direct_backend_construction",
                "reason": "direct backend construction scan did not pass",
                "unexpected": direct_scan.get("unexpected", []),
            }
        )

    return {
        "matched": not failures,
        "registered_backends": sorted(backend_names),
        "consumer_paths": {name: bool(consumers.get(name)) for name in sorted(REQUIRED_CONSUMERS)},
        "failures": failures,
    }


def validate_storage_phase5_evidence(
    manifest: dict[str, Any],
    *,
    check_artifacts: bool = False,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    artifacts = manifest.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    reports = artifacts.get("storage_backend_registry")
    if not isinstance(reports, list) or not reports:
        failures.append(
            {
                "field": "artifacts.storage_backend_registry",
                "reason": "Phase 5 evidence requires at least one storage backend registry report",
            }
        )
        reports = []

    steps = manifest.get("steps")
    step_names = [
        step.get("name")
        for step in (steps if isinstance(steps, list) else [])
        if isinstance(step, dict)
    ]
    if "storage_backend_registry_integrity" not in step_names:
        failures.append(
            {
                "field": "steps",
                "reason": "Phase 5 evidence requires a storage backend registry integrity step",
            }
        )

    report_results: list[dict[str, Any]] = []
    if check_artifacts:
        for index, entry in indexed_artifact_entries(
            {"storage_backend_registry": reports},
            "storage_backend_registry",
        ):
            path_value = entry.get("path")
            if not isinstance(path_value, str) or not path_value:
                continue
            path = _resolve(path_value, manifest_path=manifest_path)
            try:
                result = validate_storage_phase5_report(_load_json_object(path))
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                failures.append(
                    {
                        "field": f"artifacts.storage_backend_registry[{index}].path",
                        "reason": "storage backend registry report could not be read",
                        "path": path_value,
                        "error": str(exc),
                    }
                )
                continue
            report_results.append({"role": entry.get("role"), "path": str(path), "result": result})
            if result.get("matched") is not True:
                failures.append(
                    {
                        "field": f"artifacts.storage_backend_registry[{index}]",
                        "reason": "storage backend registry report validation failed",
                        "failures": result.get("failures", []),
                    }
                )

    return {
        "matched": not failures,
        "report_results": report_results,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 5 storage registry evidence")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check-artifacts", action="store_true")
    args = parser.parse_args(argv)

    if bool(args.manifest) == bool(args.report):
        parser.error("provide exactly one of --manifest or --report")

    if args.report:
        output = validate_storage_phase5_report(_load_json_object(args.report))
    else:
        output = validate_storage_phase5_evidence(
            _load_json_object(args.manifest),
            check_artifacts=args.check_artifacts,
            manifest_path=args.manifest,
        )

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
