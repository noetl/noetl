#!/usr/bin/env python
"""Validate Phase 6 fan-out/reduce planner evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json_object(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def validate_fanout_phase6_report(
    report: dict[str, Any],
    *,
    require_fanout: bool = False,
    require_reduce: bool = False,
) -> dict[str, Any]:
    """Validate a Phase 6 planner report artifact."""
    failures: list[dict[str, Any]] = []

    if report.get("planner_version") != 1:
        failures.append(
            {
                "field": "planner_version",
                "reason": "Phase 6 planner report requires planner_version=1",
            }
        )

    summary = report.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    fanout_count = int(summary.get("fanouts") or 0)
    reduce_count = int(summary.get("reduces") or 0)
    playbook_count = int(summary.get("playbooks") or 0)

    playbooks = report.get("playbooks")
    if not isinstance(playbooks, list) or len(playbooks) != playbook_count:
        failures.append(
            {
                "field": "playbooks",
                "reason": "playbook entries must match summary.playbooks",
            }
        )
        playbooks = []

    observed_fanouts = 0
    observed_reduces = 0
    for index, entry in enumerate(playbooks):
        if not isinstance(entry, dict):
            failures.append(
                {
                    "field": f"playbooks[{index}]",
                    "reason": "playbook entry must be an object",
                }
            )
            continue
        planner = entry.get("planner")
        planner = planner if isinstance(planner, dict) else {}
        fanouts = planner.get("fanouts")
        reduces = planner.get("reduces")
        if not isinstance(fanouts, list) or not isinstance(reduces, list):
            failures.append(
                {
                    "field": f"playbooks[{index}].planner",
                    "reason": "planner must include fanouts and reduces lists",
                }
            )
            continue
        observed_fanouts += len(fanouts)
        observed_reduces += len(reduces)
        failures.extend(_validate_fanout_entries(index, fanouts))
        failures.extend(_validate_reduce_entries(index, reduces))

    if observed_fanouts != fanout_count:
        failures.append(
            {
                "field": "summary.fanouts",
                "reason": "summary fanout count does not match planner entries",
                "expected": observed_fanouts,
                "actual": fanout_count,
            }
        )
    if observed_reduces != reduce_count:
        failures.append(
            {
                "field": "summary.reduces",
                "reason": "summary reduce count does not match planner entries",
                "expected": observed_reduces,
                "actual": reduce_count,
            }
        )
    if require_fanout and observed_fanouts < 1:
        failures.append(
            {
                "field": "summary.fanouts",
                "reason": "at least one fanout is required",
            }
        )
    if require_reduce and observed_reduces < 1:
        failures.append(
            {
                "field": "summary.reduces",
                "reason": "at least one reduce is required",
            }
        )

    return {
        "matched": not failures,
        "summary": {
            "playbooks": playbook_count,
            "fanouts": observed_fanouts,
            "reduces": observed_reduces,
        },
        "failures": failures,
    }


def _validate_fanout_entries(playbook_index: int, fanouts: list[Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for index, fanout in enumerate(fanouts):
        if not isinstance(fanout, dict):
            failures.append(
                {
                    "field": f"playbooks[{playbook_index}].planner.fanouts[{index}]",
                    "reason": "fanout entry must be an object",
                }
            )
            continue
        arcs = fanout.get("arcs")
        if not isinstance(fanout.get("step"), str) or not fanout["step"]:
            failures.append(
                {
                    "field": f"playbooks[{playbook_index}].planner.fanouts[{index}].step",
                    "reason": "fanout step is required",
                }
            )
        if not isinstance(arcs, list) or len(arcs) < 2 or not all(isinstance(item, str) and item for item in arcs):
            failures.append(
                {
                    "field": f"playbooks[{playbook_index}].planner.fanouts[{index}].arcs",
                    "reason": "fanout arcs must include at least two target step names",
                }
            )
        reduce_steps = fanout.get("reduce_steps")
        if reduce_steps is not None and not isinstance(reduce_steps, list):
            failures.append(
                {
                    "field": f"playbooks[{playbook_index}].planner.fanouts[{index}].reduce_steps",
                    "reason": "fanout reduce_steps must be a list when present",
                }
            )
    return failures


def _validate_reduce_entries(playbook_index: int, reduces: list[Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for index, reduce in enumerate(reduces):
        if not isinstance(reduce, dict):
            failures.append(
                {
                    "field": f"playbooks[{playbook_index}].planner.reduces[{index}]",
                    "reason": "reduce entry must be an object",
                }
            )
            continue
        upstream_steps = reduce.get("upstream_steps")
        if not isinstance(reduce.get("step"), str) or not reduce["step"]:
            failures.append(
                {
                    "field": f"playbooks[{playbook_index}].planner.reduces[{index}].step",
                    "reason": "reduce step is required",
                }
            )
        if (
            not isinstance(upstream_steps, list)
            or len(upstream_steps) < 2
            or not all(isinstance(item, str) and item for item in upstream_steps)
        ):
            failures.append(
                {
                    "field": f"playbooks[{playbook_index}].planner.reduces[{index}].upstream_steps",
                    "reason": "reduce upstream_steps must include at least two step names",
                }
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 6 fan-out/reduce planner evidence")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--require-fanout", action="store_true")
    parser.add_argument("--require-reduce", action="store_true")
    args = parser.parse_args(argv)

    output = validate_fanout_phase6_report(
        _load_json_object(args.report),
        require_fanout=args.require_fanout,
        require_reduce=args.require_reduce,
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
