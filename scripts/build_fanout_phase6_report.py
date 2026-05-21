#!/usr/bin/env python
"""Build a Phase 6 fan-out/reduce planner evidence report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from noetl.core.dsl.engine.parser import DSLParser
from noetl.core.dsl.engine.planner import FanoutReducePlan, build_fanout_reduce_plan

PLANNER_VERSION = 1


def _plan_to_dict(plan: FanoutReducePlan) -> dict[str, Any]:
    return {
        "fanouts": [
            {
                "step": fanout.step,
                "arcs": list(fanout.arcs),
                "reduce_steps": list(fanout.reduce_steps),
            }
            for fanout in plan.fanouts
        ],
        "reduces": [
            {
                "step": reduce.step,
                "upstream_steps": list(reduce.upstream_steps),
            }
            for reduce in plan.reduces
        ],
    }


def build_fanout_phase6_report(playbook_paths: list[Path]) -> dict[str, Any]:
    """Return a deterministic fan-out/reduce planner report."""
    parser = DSLParser()
    playbook_reports: list[dict[str, Any]] = []
    total_fanouts = 0
    total_reduces = 0

    for path in sorted(playbook_paths, key=lambda item: item.as_posix()):
        playbook = parser.parse_file(path, use_cache=False)
        plan = build_fanout_reduce_plan(playbook)
        plan_data = _plan_to_dict(plan)
        total_fanouts += len(plan.fanouts)
        total_reduces += len(plan.reduces)
        playbook_reports.append(
            {
                "path": path.as_posix(),
                "name": playbook.metadata.get("name"),
                "planner": plan_data,
            }
        )

    return {
        "planner_version": PLANNER_VERSION,
        "summary": {
            "playbooks": len(playbook_reports),
            "fanouts": total_fanouts,
            "reduces": total_reduces,
        },
        "playbooks": playbook_reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Phase 6 fan-out/reduce planner report")
    parser.add_argument("--playbook", action="append", type=Path, required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    report = build_fanout_phase6_report(args.playbook)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"matched": True, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
