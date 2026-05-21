#!/usr/bin/env python
"""Validate replay validation run manifest JSON."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.package_replay_validation_artifacts import (
    resolve_indexed_path,
    validate_artifact_index,
)

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
OPTIONAL_STEP_NAMES = (
    "live_rows_export",
    "live_rows_integrity",
    "live_checksums",
    "projection_parity",
    "payload_resolution",
    "runtime_locator_live_rows",
    "runtime_locator_state",
    "replay_fanout_reduce_integrity",
    "artifact_index",
    "storage_backend_registry_report",
    "fanout_reduce_planner_report",
)


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


def _artifact_path(value: str, manifest_path: Path | None) -> Path:
    path = Path(value)
    if not path.is_absolute() and manifest_path is not None:
        return (manifest_path.parent / path).resolve()
    return path


def _validate_artifact_path(
    failures: list[dict[str, Any]],
    *,
    field: str,
    value: Any,
    manifest_path: Path | None,
    check_artifacts: bool,
) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value:
        failures.append({"field": field, "reason": "artifact path must be a string"})
    elif check_artifacts and not _artifact_path(value, manifest_path).exists():
        failures.append({"field": field, "reason": "artifact path does not exist", "path": value})


def _is_projector_summary_step(name: str) -> bool:
    return (
        name.startswith("projector_summary_")
        and (name.endswith("_integrity") or name.endswith("_fetch"))
    )


def _is_worker_metrics_step(name: str) -> bool:
    return (
        name.startswith("worker_metrics_")
        and (name.endswith("_integrity") or name.endswith("_fetch"))
    )


def _is_storage_backend_registry_step(name: str) -> bool:
    return name == "storage_backend_registry_integrity"


def _is_fanout_reduce_planner_step(name: str) -> bool:
    return name == "fanout_reduce_planner_integrity"


def _validate_artifact_list(
    failures: list[dict[str, Any]],
    *,
    field: str,
    value: Any,
    manifest_path: Path | None,
    check_artifacts: bool,
) -> None:
    if not isinstance(value, list):
        failures.append({"field": field, "reason": "must be a list"})
        return
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            failures.append(
                {
                    "field": f"{field}[{index}]",
                    "reason": "must be an object",
                }
            )
            continue
        if not isinstance(entry.get("role"), str) or not entry.get("role"):
            failures.append(
                {
                    "field": f"{field}[{index}].role",
                    "reason": "must be a non-empty string",
                }
            )
        _validate_artifact_path(
            failures,
            field=f"{field}[{index}].path",
            value=entry.get("path"),
            manifest_path=manifest_path,
            check_artifacts=check_artifacts,
        )
        if "url" in entry and (not isinstance(entry.get("url"), str) or not entry.get("url")):
            failures.append(
                {
                    "field": f"{field}[{index}].url",
                    "reason": "must be a non-empty string when present",
                }
            )


def _artifact_roles(artifacts: dict[str, Any], field: str) -> list[str]:
    value = artifacts.get(field)
    if not isinstance(value, list):
        return []
    roles: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        if isinstance(role, str) and role:
            roles.append(role)
    return roles


def _phase_artifact_roles(artifacts: dict[str, Any]) -> list[str]:
    roles: list[str] = []
    for field in (
        "projector_summaries",
        "worker_metrics",
        "storage_backend_registry",
        "fanout_reduce_planner",
    ):
        roles.extend(_artifact_roles(artifacts, field))
    return sorted(set(roles))


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    require_matched: bool,
    check_artifacts: bool,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
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
    elif isinstance(artifacts, dict):
        for field, value in artifacts.items():
            if field == "projector_summaries":
                _validate_artifact_list(
                    failures,
                    field="artifacts.projector_summaries",
                    value=value,
                    manifest_path=manifest_path,
                    check_artifacts=check_artifacts,
                )
                continue
            if field == "worker_metrics":
                _validate_artifact_list(
                    failures,
                    field="artifacts.worker_metrics",
                    value=value,
                    manifest_path=manifest_path,
                    check_artifacts=check_artifacts,
                )
                continue
            if field == "storage_backend_registry":
                _validate_artifact_list(
                    failures,
                    field="artifacts.storage_backend_registry",
                    value=value,
                    manifest_path=manifest_path,
                    check_artifacts=check_artifacts,
                )
                continue
            if field == "fanout_reduce_planner":
                _validate_artifact_list(
                    failures,
                    field="artifacts.fanout_reduce_planner",
                    value=value,
                    manifest_path=manifest_path,
                    check_artifacts=check_artifacts,
                )
                continue
            _validate_artifact_path(
                failures,
                field=f"artifacts.{field}",
                value=value,
                manifest_path=manifest_path,
                check_artifacts=check_artifacts,
            )

        artifact_index = artifacts.get("artifact_index")
        if isinstance(artifact_index, str) and artifact_index:
            index_path = _artifact_path(artifact_index, manifest_path)
            if index_path.exists():
                try:
                    index_output = validate_artifact_index(index_path)
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    failures.append(
                        {
                            "field": "artifacts.artifact_index",
                            "reason": "artifact index could not be validated",
                            "path": artifact_index,
                            "error": str(exc),
                        }
                    )
                else:
                    if index_output.get("matched") is not True:
                        failures.append(
                            {
                                "field": "artifacts.artifact_index",
                                "reason": "artifact index validation failed",
                                "path": artifact_index,
                                "failures": index_output.get("failures", []),
                            }
                        )
                    indexed_roles = index_output.get("roles")
                    indexed_roles = indexed_roles if isinstance(indexed_roles, list) else []
                    missing_phase_roles = [
                        role
                        for role in _phase_artifact_roles(artifacts)
                        if role not in indexed_roles
                    ]
                    if missing_phase_roles:
                        failures.append(
                            {
                                "field": "artifacts.artifact_index",
                                "reason": "artifact index missing phase artifact roles",
                                "path": artifact_index,
                                "roles": missing_phase_roles,
                            }
                        )
                    if manifest_path is not None:
                        try:
                            index_data = _load_manifest(index_path)
                            indexed_manifest = index_data.get("manifest")
                            if not isinstance(indexed_manifest, str) or not indexed_manifest:
                                failures.append(
                                    {
                                        "field": "artifacts.artifact_index",
                                        "reason": "artifact index manifest path is missing",
                                        "path": artifact_index,
                                    }
                                )
                            elif resolve_indexed_path(indexed_manifest, index_path=index_path) != manifest_path.resolve():
                                failures.append(
                                    {
                                        "field": "artifacts.artifact_index",
                                        "reason": "artifact index points at a different manifest",
                                        "path": artifact_index,
                                        "indexed_manifest": indexed_manifest,
                                    }
                                )
                        except (OSError, json.JSONDecodeError, ValueError) as exc:
                            failures.append(
                                {
                                    "field": "artifacts.artifact_index",
                                    "reason": "artifact index manifest path could not be checked",
                                    "path": artifact_index,
                                    "error": str(exc),
                                }
                            )

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
    artifacts_live_rows = artifacts.get("live_rows") if isinstance(artifacts, dict) else None
    config_live_rows = config.get("live_rows") if isinstance(config, dict) else None
    export_live_rows = (
        config.get("export_live_rows_postgres") if isinstance(config, dict) else False
    )
    if artifacts_live_rows or config_live_rows or export_live_rows:
        if "live_rows_integrity" not in step_names:
            failures.append(
                {
                    "field": "steps",
                    "reason": "live row manifests require live_rows_integrity step",
                }
            )
        elif "live_checksums" in step_names and step_names.index("live_rows_integrity") > step_names.index("live_checksums"):
            failures.append(
                {
                    "field": "steps",
                    "reason": "live_rows_integrity must run before live_checksums",
                }
            )
    artifacts_index = artifacts.get("artifact_index") if isinstance(artifacts, dict) else None
    projector_summaries = artifacts.get("projector_summaries") if isinstance(artifacts, dict) else None
    if projector_summaries:
        integrity_steps = [name for name in step_names if _is_projector_summary_step(name) and name.endswith("_integrity")]
        if len(integrity_steps) < len(projector_summaries):
            failures.append(
                {
                    "field": "steps",
                    "reason": "projector summary artifacts require matching integrity steps",
                }
            )
    worker_metrics = artifacts.get("worker_metrics") if isinstance(artifacts, dict) else None
    if worker_metrics:
        integrity_steps = [name for name in step_names if _is_worker_metrics_step(name) and name.endswith("_integrity")]
        if len(integrity_steps) < len(worker_metrics):
            failures.append(
                {
                    "field": "steps",
                    "reason": "worker metrics artifacts require matching integrity steps",
                }
            )
    storage_backend_registry = artifacts.get("storage_backend_registry") if isinstance(artifacts, dict) else None
    if storage_backend_registry and "storage_backend_registry_integrity" not in step_names:
        failures.append(
            {
                "field": "steps",
                "reason": "storage backend registry artifacts require an integrity step",
            }
        )
    fanout_reduce_planner = artifacts.get("fanout_reduce_planner") if isinstance(artifacts, dict) else None
    if fanout_reduce_planner and "fanout_reduce_planner_integrity" not in step_names:
        failures.append(
            {
                "field": "steps",
                "reason": "fan-out/reduce planner artifacts require an integrity step",
            }
        )
    if artifacts_index:
        if "artifact_index" not in step_names:
            failures.append(
                {
                    "field": "steps",
                    "reason": "artifact index manifests require artifact_index step",
                }
            )
        elif step_names.index("artifact_index") != len(step_names) - 1:
            failures.append(
                {
                    "field": "steps",
                    "reason": "artifact_index step must be last",
                }
            )
    elif "artifact_index" in step_names:
        failures.append(
            {
                "field": "artifacts.artifact_index",
                "reason": "artifact_index step requires artifacts.artifact_index",
            }
        )
    for name in step_names:
        if _is_projector_summary_step(name):
            continue
        if _is_worker_metrics_step(name):
            continue
        if _is_storage_backend_registry_step(name):
            continue
        if _is_fanout_reduce_planner_step(name):
            continue
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
        manifest_path=args.manifest,
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
