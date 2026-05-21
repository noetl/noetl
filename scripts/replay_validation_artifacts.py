"""Shared helpers for replay validation artifact metadata."""

from __future__ import annotations

from typing import Any

PHASE_ARTIFACT_FIELDS = (
    "projector_summaries",
    "worker_metrics",
    "storage_backend_registry",
    "fanout_reduce_planner",
)


def artifact_entries(artifacts: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = artifacts.get(field)
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def indexed_artifact_entries(
    artifacts: dict[str, Any],
    field: str,
) -> list[tuple[int, dict[str, Any]]]:
    value = artifacts.get(field)
    if not isinstance(value, list):
        return []
    return [
        (index, entry)
        for index, entry in enumerate(value)
        if isinstance(entry, dict)
    ]


def artifact_roles(artifacts: dict[str, Any], field: str) -> list[str]:
    roles: list[str] = []
    for entry in artifact_entries(artifacts, field):
        role = entry.get("role")
        if isinstance(role, str) and role:
            roles.append(role)
    return roles


def duplicate_artifact_roles(artifacts: dict[str, Any], field: str) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for role in artifact_roles(artifacts, field):
        if role in seen:
            duplicates.add(role)
        seen.add(role)
    return sorted(duplicates)


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
    for entry in [item for item in entries if isinstance(item, dict)]:
        role = entry.get("role")
        path = entry.get("path")
        if not isinstance(role, str) or not role:
            continue
        if not isinstance(path, str) or not path:
            continue
        args.extend(["--artifact", f"{role}={path}"])
    return args
