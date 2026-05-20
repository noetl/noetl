#!/usr/bin/env python
"""Fetch replay state and run offline replay validation gates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_json(value: str) -> object | None:
    if not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _run(command: list[str]) -> tuple[int, str, str, float]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
    )
    duration = time.monotonic() - started
    return completed.returncode, completed.stdout, completed.stderr, duration


def _build_report(
    *,
    matched: bool,
    args: argparse.Namespace,
    replay_path: Path,
    live_checksums_path: Path | None,
    live_rows_path: Path | None,
    steps: list[dict[str, object]],
    started_at: str,
) -> dict[str, object]:
    finished_at = _utc_now()
    return {
        "matched": matched,
        "started_at": started_at,
        "finished_at": finished_at,
        "replay": str(replay_path),
        "artifacts": {
            "replay": str(replay_path),
            "live_rows": str(live_rows_path) if live_rows_path else None,
            "live_checksums": str(live_checksums_path) if live_checksums_path else None,
            "report": str(args.report_output) if args.report_output else None,
        },
        "config": {
            "base_url": args.base_url,
            "execution_id": args.execution_id,
            "tenant_id": args.tenant_id,
            "organization_id": args.organization_id,
            "projection": args.projection,
            "limit": args.limit,
            "as_of_event_id": args.as_of_event_id,
            "as_of_position": args.as_of_position,
            "as_of_time": args.as_of_time,
            "resolve_payloads": args.resolve_payloads,
            "live_checksums": str(args.live_checksums) if args.live_checksums else None,
            "live_rows": str(args.live_rows) if args.live_rows else None,
            "export_live_rows_postgres": args.export_live_rows_postgres,
        },
        "steps": steps,
    }


def _emit_report(report: dict[str, object], report_output: Path | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if report_output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(rendered + "\n")
    print(rendered)


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
    parser.add_argument(
        "--live-rows",
        type=Path,
        help="Optional adapter-exported live projection rows JSON; converted to live checksums before parity",
    )
    parser.add_argument(
        "--export-live-rows-postgres",
        action="store_true",
        help="Export live rows from the reference Postgres adapter before parity",
    )
    parser.add_argument(
        "--postgres-dsn",
        help="Optional Postgres DSN for --export-live-rows-postgres; defaults to NoETL env",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        help="Optional path to write the validation run manifest JSON",
    )
    args = parser.parse_args(argv)

    cutoff_count = sum(
        value is not None
        for value in (args.as_of_event_id, args.as_of_position, args.as_of_time)
    )
    if cutoff_count > 1:
        parser.error("use only one replay cutoff")
    live_input_count = sum(
        1
        for enabled in (
            bool(args.live_checksums),
            bool(args.live_rows),
            bool(args.export_live_rows_postgres),
        )
        if enabled
    )
    if live_input_count > 1:
        parser.error(
            "use only one live parity input: --live-checksums, --live-rows, or --export-live-rows-postgres"
        )
    if args.postgres_dsn and not args.export_live_rows_postgres:
        parser.error("--postgres-dsn requires --export-live-rows-postgres")

    started_at = _utc_now()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    replay_path = output_dir / f"replay-{args.execution_id}.json"
    live_checksums_path = args.live_checksums
    live_rows_path = args.live_rows
    if args.export_live_rows_postgres:
        live_rows_path = output_dir / f"live-rows-{args.execution_id}.json"
    if live_rows_path:
        live_checksums_path = output_dir / f"live-checksums-{args.execution_id}.json"
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
            "live_rows_export",
            [
                sys.executable,
                "scripts/export_live_projection_rows_postgres.py",
                "--execution-id",
                str(args.execution_id),
                "--tenant-id",
                args.tenant_id,
                "--organization-id",
                args.organization_id,
                "--projection",
                args.projection,
                "--output",
                str(live_rows_path),
            ]
            + (["--dsn", args.postgres_dsn] if args.postgres_dsn else [])
            if args.export_live_rows_postgres
            else [],
        ),
        (
            "live_checksums",
            [
                sys.executable,
                "scripts/build_live_projection_checksums.py",
                "--rows",
                str(live_rows_path),
                "--output",
                str(live_checksums_path),
            ]
            if live_rows_path
            else [],
        ),
        (
            "projection_parity",
            [
                sys.executable,
                "scripts/check_replay_parity_report.py",
                "--replayed",
                str(replay_path),
                "--live",
                str(live_checksums_path),
            ]
            if live_checksums_path
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
        code, stdout, stderr, duration = _run(command)
        step = {
            "name": name,
            "command": command,
            "returncode": code,
            "duration_seconds": round(duration, 6),
            "stdout": stdout,
            "stderr": stderr,
        }
        stdout_json = _parse_json(stdout)
        if stdout_json is not None:
            step["stdout_json"] = stdout_json
        steps.append(step)
        if code != 0:
            _emit_report(
                _build_report(
                    matched=False,
                    args=args,
                    replay_path=replay_path,
                    live_checksums_path=live_checksums_path,
                    live_rows_path=live_rows_path,
                    steps=steps,
                    started_at=started_at,
                ),
                args.report_output,
            )
            return code
        if name == "fetch" and not replay_path.exists():
            steps.append(
                {
                    "name": "fetch_artifact",
                    "returncode": 1,
                    "duration_seconds": 0.0,
                    "stdout": "",
                    "stderr": f"fetch step did not create replay report: {replay_path}",
                }
            )
            _emit_report(
                _build_report(
                    matched=False,
                    args=args,
                    replay_path=replay_path,
                    live_checksums_path=live_checksums_path,
                    live_rows_path=live_rows_path,
                    steps=steps,
                    started_at=started_at,
                ),
                args.report_output,
            )
            return 1

    _emit_report(
        _build_report(
            matched=True,
            args=args,
            replay_path=replay_path,
            live_checksums_path=live_checksums_path,
            live_rows_path=live_rows_path,
            steps=steps,
            started_at=started_at,
        ),
        args.report_output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
