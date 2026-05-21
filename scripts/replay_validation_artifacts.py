"""Shared helpers for replay validation artifact metadata."""

from __future__ import annotations

from typing import Any

PHASE_ARTIFACT_FIELDS = (
    "projector_summaries",
    "worker_metrics",
    "storage_backend_registry",
    "fanout_reduce_planner",
)


def artifact_roles(artifacts: dict[str, Any], field: str) -> list[str]:
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


def phase_artifact_roles(
    artifacts: dict[str, Any],
    *,
    fields: tuple[str, ...] = PHASE_ARTIFACT_FIELDS,
) -> list[str]:
    roles: list[str] = []
    for field in fields:
        roles.extend(artifact_roles(artifacts, field))
    return sorted(set(roles))


def artifact_cli_args(entries: list[dict[str, Any]]) -> list[str]:
    args: list[str] = []
    for entry in entries:
        role = entry.get("role")
        path = entry.get("path")
        if not isinstance(role, str) or not role:
            continue
        if not isinstance(path, str) or not path:
            continue
        args.extend(["--artifact", f"{role}={path}"])
    return args
