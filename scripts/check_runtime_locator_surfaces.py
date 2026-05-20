#!/usr/bin/env python
"""Validate Cloud OS worker locators in replay and live projection artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from noetl.core.resource_locator import ResourceLocatorError
from noetl.core.runtime.topology import WorkerLocatorParts, parse_worker_locator


def _load_json(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _command_rows(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        for row in value.values():
            if isinstance(row, Mapping):
                yield row
        return
    if isinstance(value, list):
        for row in value:
            if isinstance(row, Mapping):
                yield row


def _expected_context(document: Mapping[str, Any]) -> dict[str, str]:
    context: dict[str, str] = {}
    tenant_id = document.get("tenant_id")
    organization_id = document.get("organization_id")
    if isinstance(tenant_id, str) and tenant_id:
        context["tenant_id"] = tenant_id
    if isinstance(organization_id, str) and organization_id:
        context["organization_id"] = organization_id
    return context


def _validate_parts(
    failures: list[dict[str, Any]],
    *,
    surface: str,
    index: int,
    command_id: Any,
    parts: WorkerLocatorParts,
    row: Mapping[str, Any],
    context: Mapping[str, str],
) -> None:
    if context.get("tenant_id") and parts.tenant_id != context["tenant_id"]:
        failures.append(
            {
                "surface": surface,
                "index": index,
                "command_id": command_id,
                "field": "worker_locator.tenant",
                "reason": "does not match artifact tenant_id",
                "expected": context["tenant_id"],
                "actual": parts.tenant_id,
            }
        )
    if context.get("organization_id") and parts.organization_id != context["organization_id"]:
        failures.append(
            {
                "surface": surface,
                "index": index,
                "command_id": command_id,
                "field": "worker_locator.org",
                "reason": "does not match artifact organization_id",
                "expected": context["organization_id"],
                "actual": parts.organization_id,
            }
        )

    locality = row.get("locality")
    if not isinstance(locality, Mapping):
        return
    locality_checks = {
        "cluster_id": parts.cluster_id,
        "node_id": parts.node_id,
        "worker_pool": parts.worker_pool,
    }
    for field, actual in locality_checks.items():
        expected = locality.get(field)
        if expected is None or expected == "" or actual is None:
            continue
        if str(expected) != actual:
            failures.append(
                {
                    "surface": surface,
                    "index": index,
                    "command_id": command_id,
                    "field": f"locality.{field}",
                    "reason": "does not match worker_locator",
                    "expected": str(expected),
                    "actual": actual,
                }
            )


def _validate_command_surface(
    failures: list[dict[str, Any]],
    *,
    surface: str,
    rows: Iterable[Mapping[str, Any]],
    context: Mapping[str, str],
) -> int:
    locator_count = 0
    for index, row in enumerate(rows):
        locator = row.get("worker_locator")
        if locator is None or locator == "":
            continue
        locator_count += 1
        command_id = row.get("command_id")
        if not isinstance(locator, str):
            failures.append(
                {
                    "surface": surface,
                    "index": index,
                    "command_id": command_id,
                    "field": "worker_locator",
                    "reason": "must be a string when present",
                    "actual": locator,
                }
            )
            continue
        try:
            parts = parse_worker_locator(locator)
        except ResourceLocatorError as exc:
            failures.append(
                {
                    "surface": surface,
                    "index": index,
                    "command_id": command_id,
                    "field": "worker_locator",
                    "reason": str(exc),
                    "actual": locator,
                }
            )
            continue
        _validate_parts(
            failures,
            surface=surface,
            index=index,
            command_id=command_id,
            parts=parts,
            row=row,
            context=context,
        )
    return locator_count


def validate_runtime_locator_surfaces(
    *,
    replay_report: Path | None = None,
    live_rows: Path | None = None,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    surfaces: dict[str, int] = {}

    if replay_report is not None:
        replay = _load_json(replay_report)
        count = _validate_command_surface(
            failures,
            surface="replay.commands",
            rows=_command_rows(replay.get("commands")),
            context=_expected_context(replay),
        )
        surfaces["replay.commands"] = count

    if live_rows is not None:
        artifact = _load_json(live_rows)
        rows = artifact.get("rows") if isinstance(artifact.get("rows"), Mapping) else {}
        commands = rows.get("commands") if isinstance(rows, Mapping) else None
        count = _validate_command_surface(
            failures,
            surface="live_rows.commands",
            rows=_command_rows(commands),
            context=_expected_context(artifact),
        )
        surfaces["live_rows.commands"] = count

    return {
        "matched": not failures,
        "surfaces": surfaces,
        "locator_count": sum(surfaces.values()),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate NoETL runtime locator surfaces")
    parser.add_argument("--replay-report", type=Path)
    parser.add_argument("--live-rows", type=Path)
    args = parser.parse_args(argv)

    if args.replay_report is None and args.live_rows is None:
        parser.error("at least one of --replay-report or --live-rows is required")

    output = validate_runtime_locator_surfaces(
        replay_report=args.replay_report,
        live_rows=args.live_rows,
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
