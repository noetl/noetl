#!/usr/bin/env python
"""Fetch replay state and run offline replay validation gates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _run(command: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
    )
    return completed.returncode, completed.stdout, completed.stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch NoETL replay state and run offline validation gates",
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--execution-id", required=True, type=int)
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--organization-id", default="default")
    parser.add_argument("--projection", default="all")
    parser.add_argument("--limit", default=100000, type=int)
    parser.add_argument("--as-of-event-id", type=int)
    parser.add_argument("--as-of-position", type=int)
    parser.add_argument("--as-of-time")
    parser.add_argument("--resolve-payloads", action="store_true")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout", default=60.0, type=float)
    parser.add_argument("--live-checksums", type=Path)
    args = parser.parse_args(argv)

    output_dir = args.output_dir
    replay_path = output_dir / f"replay-{args.execution_id}.json"
    fetch_command = [
        sys.executable,
        "scripts/fetch_replay_state_report.py",
        "--base-url",
        args.base_url,
        "--execution-id",
        str(args.execution_id),
        "--tenant-id",
        args.tenant_id,
        "--organization-id",
        args.organization_id,
        "--projection",
        args.projection,
        "--limit",
        str(args.limit),
        "--output",
        str(replay_path),
        "--timeout",
        str(args.timeout),
    ]
    for flag in ("as_of_event_id", "as_of_position", "as_of_time"):
        value = getattr(args, flag)
        if value is not None:
            fetch_command.extend([f"--{flag.replace('_', '-')}", str(value)])
    if args.resolve_payloads:
        fetch_command.append("--resolve-payloads")

    steps: list[dict[str, object]] = []
    for name, command in [
        ("fetch", fetch_command),
        (
            "state_integrity",
            [
                sys.executable,
                "scripts/check_replay_state_report.py",
                "--report",
                str(replay_path),
            ],
        ),
        (
            "projection_parity",
            [
                sys.executable,
                "scripts/check_replay_parity_report.py",
                "--replayed",
                str(replay_path),
                "--live",
                str(args.live_checksums),
            ]
            if args.live_checksums
            else [],
        ),
        (
            "payload_resolution",
            [
                sys.executable,
                "scripts/check_replay_payload_resolution_report.py",
                "--report",
                str(replay_path),
            ]
            if args.resolve_payloads
            else [],
        ),
    ]:
        if not command:
            steps.append({"name": name, "skipped": True})
            continue
        code, stdout, stderr = _run(command)
        steps.append(
            {
                "name": name,
                "command": command,
                "returncode": code,
                "stdout": stdout,
                "stderr": stderr,
            }
        )
        if code != 0:
            print(json.dumps({"matched": False, "replay": str(replay_path), "steps": steps}, indent=2))
            return code

    print(json.dumps({"matched": True, "replay": str(replay_path), "steps": steps}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
