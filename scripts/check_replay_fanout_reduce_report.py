#!/usr/bin/env python
"""Validate replay evidence for Phase 6 fan-out/reduce command metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def _load_json_object(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def validate_replay_fanout_reduce_report(
    report: Mapping[str, Any],
    *,
    require_reduce: bool = True,
) -> dict[str, Any]:
    """Validate fan-out/reduce metadata in a replay-state report."""
    failures: list[dict[str, Any]] = []
    commands = report.get("commands")
    commands = commands if isinstance(commands, Mapping) else {}

    matches: list[dict[str, Any]] = []
    for command_id, command in sorted(commands.items(), key=lambda item: str(item[0])):
        if not isinstance(command, Mapping):
            continue
        metadata = command.get("fanout_reduce")
        if not isinstance(metadata, Mapping) or not metadata:
            continue
        result = _validate_metadata(command_id=str(command_id), metadata=metadata)
        if result["failures"]:
            failures.extend(result["failures"])
        else:
            matches.append(result["match"])

    if not matches:
        failures.append(
            {
                "field": "commands",
                "reason": "replay report does not contain fan-out/reduce command metadata",
            }
        )

    if require_reduce and not any(match.get("reduce_steps") for match in matches):
        failures.append(
            {
                "field": "commands[*].fanout_reduce.reduce_steps",
                "reason": "at least one fan-out command must declare a reduce step",
            }
        )

    fanout_steps = sorted({str(match["fanout_step"]) for match in matches if match.get("fanout_step")})
    reduce_steps = sorted(
        {
            str(reduce_step)
            for match in matches
            for reduce_step in (match.get("reduce_steps") or [])
        }
    )

    return {
        "matched": not failures,
        "fanout_commands": len(matches),
        "fanout_steps": fanout_steps,
        "reduce_steps": reduce_steps,
        "failures": failures,
    }


def _validate_metadata(command_id: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    field_prefix = f"commands.{command_id}.fanout_reduce"

    planner_version = metadata.get("planner_version")
    if planner_version != 1:
        failures.append(
            {
                "field": f"{field_prefix}.planner_version",
                "reason": "planner_version must be 1",
                "supplied": planner_version,
            }
        )

    fanout_step = metadata.get("fanout_step")
    target_step = metadata.get("target_step")
    if not isinstance(fanout_step, str) or not fanout_step:
        failures.append({"field": f"{field_prefix}.fanout_step", "reason": "must be a non-empty string"})
    if not isinstance(target_step, str) or not target_step:
        failures.append({"field": f"{field_prefix}.target_step", "reason": "must be a non-empty string"})

    targets = metadata.get("fanout_targets")
    if not isinstance(targets, list) or len(targets) < 2 or not all(isinstance(item, str) and item for item in targets):
        failures.append(
            {
                "field": f"{field_prefix}.fanout_targets",
                "reason": "must include at least two target step names",
            }
        )

    target_index = metadata.get("target_index")
    if isinstance(target_index, bool) or not isinstance(target_index, int) or target_index < 0:
        failures.append(
            {
                "field": f"{field_prefix}.target_index",
                "reason": "must be a non-negative integer",
                "supplied": target_index,
            }
        )
    elif isinstance(targets, list) and target_index >= len(targets):
        failures.append(
            {
                "field": f"{field_prefix}.target_index",
                "reason": "must point inside fanout_targets",
                "supplied": target_index,
            }
        )
    elif isinstance(targets, list) and isinstance(target_step, str) and targets[target_index] != target_step:
        failures.append(
            {
                "field": f"{field_prefix}.target_step",
                "reason": "target_step must match fanout_targets[target_index]",
                "target_step": target_step,
                "target_at_index": targets[target_index],
            }
        )

    reduce_steps = metadata.get("reduce_steps")
    if reduce_steps is not None and (
        not isinstance(reduce_steps, list)
        or not all(isinstance(item, str) and item for item in reduce_steps)
    ):
        failures.append(
            {
                "field": f"{field_prefix}.reduce_steps",
                "reason": "must be a list of step names when present",
            }
        )

    return {
        "match": {
            "command_id": command_id,
            "fanout_step": fanout_step,
            "target_step": target_step,
            "target_index": target_index,
            "reduce_steps": list(reduce_steps or []) if isinstance(reduce_steps, list) else [],
        },
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate replay fan-out/reduce metadata evidence")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--allow-no-reduce", action="store_true")
    args = parser.parse_args(argv)

    output = validate_replay_fanout_reduce_report(
        _load_json_object(args.report),
        require_reduce=not args.allow_no_reduce,
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
