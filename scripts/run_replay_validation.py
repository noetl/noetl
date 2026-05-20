#!/usr/bin/env python
"""Fetch replay state and run offline replay validation gates."""

from __future__ import annotations

import argparse
import json
import os
import re
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
    env = os.environ.copy()
    repo_root = str(Path.cwd())
    env["PYTHONPATH"] = repo_root if not env.get("PYTHONPATH") else f"{repo_root}{os.pathsep}{env['PYTHONPATH']}"
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    duration = time.monotonic() - started
    return completed.returncode, completed.stdout, completed.stderr, duration


def _validation_python() -> str:
    return os.environ.get("NOETL_VALIDATION_PYTHON") or sys.executable


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return slug or "endpoint"


def _parse_named_value(raw: str, *, flag: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"{flag} must use NAME=VALUE")
    name, value = raw.split("=", 1)
    name = name.strip()
    value = value.strip()
    if not name or not value:
        raise ValueError(f"{flag} must use NAME=VALUE")
    return name, value


def _build_report(
    *,
    matched: bool,
    args: argparse.Namespace,
    replay_path: Path,
    live_checksums_path: Path | None,
    live_rows_path: Path | None,
    projector_summaries: list[dict[str, str]],
    worker_metrics: list[dict[str, str]],
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
            "projector_summaries": projector_summaries,
            "worker_metrics": worker_metrics,
            "report": str(args.report_output) if args.report_output else None,
            "artifact_index": str(args.artifact_index_output) if args.artifact_index_output else None,
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
            "projector_summary": [str(path) for path in args.projector_summary],
            "projector_summary_url": list(args.projector_summary_url),
            "worker_metrics": [str(path) for path in args.worker_metrics],
            "worker_metrics_url": list(args.worker_metrics_url),
            "artifact_index_output": str(args.artifact_index_output) if args.artifact_index_output else None,
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
    parser.add_argument(
        "--artifact-index-output",
        type=Path,
        help="Optional path to write SHA-256/size index for validation artifacts",
    )
    parser.add_argument(
        "--projector-summary",
        action="append",
        default=[],
        type=Path,
        help="Optional saved projector /summary JSON artifact to validate",
    )
    parser.add_argument(
        "--projector-summary-url",
        action="append",
        default=[],
        metavar="NAME=URL",
        help="Fetch and validate a live projector summary from NAME=URL",
    )
    parser.add_argument(
        "--worker-metrics",
        action="append",
        default=[],
        type=Path,
        help="Optional saved worker /metrics text artifact to validate for Phase 3 IPC evidence",
    )
    parser.add_argument(
        "--worker-metrics-url",
        action="append",
        default=[],
        metavar="NAME=URL",
        help="Fetch and validate a live worker metrics endpoint from NAME=URL",
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
    if args.artifact_index_output and args.report_output is None:
        parser.error("--artifact-index-output requires --report-output")
    projector_summary_urls: list[tuple[str, str]] = []
    try:
        projector_summary_urls = [
            _parse_named_value(raw, flag="--projector-summary-url")
            for raw in args.projector_summary_url
        ]
    except ValueError as exc:
        parser.error(str(exc))
    worker_metrics_urls: list[tuple[str, str]] = []
    try:
        worker_metrics_urls = [
            _parse_named_value(raw, flag="--worker-metrics-url")
            for raw in args.worker_metrics_url
        ]
    except ValueError as exc:
        parser.error(str(exc))

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
    projector_summaries: list[dict[str, str]] = []
    projector_fetch_steps: list[tuple[str, list[str]]] = []
    projector_check_steps: list[tuple[str, list[str]]] = []
    for idx, path in enumerate(args.projector_summary, start=1):
        role = f"projector_summary_{idx}"
        projector_summaries.append({"role": role, "path": str(path)})
        projector_check_steps.append(
            (
                f"projector_summary_{idx}_integrity",
                [
                    _validation_python(),
                    "scripts/check_projector_metrics_summary.py",
                    "--report",
                    str(path),
                ],
            )
        )
    for idx, (name, url) in enumerate(projector_summary_urls, start=1):
        role = f"projector_summary_url_{idx}_{_safe_slug(name)}"
        path = output_dir / f"{role}.json"
        projector_summaries.append({"role": role, "name": name, "url": url, "path": str(path)})
        projector_fetch_steps.append(
            (
                f"{role}_fetch",
                [
                    _validation_python(),
                    "scripts/fetch_projector_metrics_summary.py",
                    "--url",
                    url,
                    "--output",
                    str(path),
                    "--timeout",
                    str(args.timeout),
                ],
            )
        )
        projector_check_steps.append(
            (
                f"{role}_integrity",
                [
                    _validation_python(),
                    "scripts/check_projector_metrics_summary.py",
                    "--report",
                    str(path),
                ],
            )
        )
    worker_metrics: list[dict[str, str]] = []
    worker_fetch_steps: list[tuple[str, list[str]]] = []
    worker_check_steps: list[tuple[str, list[str]]] = []
    for idx, path in enumerate(args.worker_metrics, start=1):
        role = f"worker_metrics_{idx}"
        worker_metrics.append({"role": role, "path": str(path)})
        worker_check_steps.append(
            (
                f"worker_metrics_{idx}_integrity",
                [
                    _validation_python(),
                    "scripts/check_worker_ipc_metrics.py",
                    "--metrics",
                    str(path),
                ],
            )
        )
    for idx, (name, url) in enumerate(worker_metrics_urls, start=1):
        role = f"worker_metrics_url_{idx}_{_safe_slug(name)}"
        path = output_dir / f"{role}.prom"
        worker_metrics.append({"role": role, "name": name, "url": url, "path": str(path)})
        worker_fetch_steps.append(
            (
                f"{role}_fetch",
                [
                    _validation_python(),
                    "scripts/fetch_worker_metrics.py",
                    "--url",
                    url,
                    "--output",
                    str(path),
                    "--timeout",
                    str(args.timeout),
                ],
            )
        )
        worker_check_steps.append(
            (
                f"{role}_integrity",
                [
                    _validation_python(),
                    "scripts/check_worker_ipc_metrics.py",
                    "--metrics",
                    str(path),
                ],
            )
        )
    fetch_command = [
        _validation_python(),
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
    validation_steps = [
        ("fetch", fetch_command),
        (
            "state_integrity",
            [
                _validation_python(),
                "scripts/check_replay_state_report.py",
                "--report",
                str(replay_path),
            ],
        ),
        (
            "live_rows_export",
            [
                _validation_python(),
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
            "live_rows_integrity",
            [
                _validation_python(),
                "scripts/check_live_projection_rows.py",
                "--rows",
                str(live_rows_path),
            ]
            if live_rows_path
            else [],
        ),
        (
            "live_checksums",
            [
                _validation_python(),
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
                _validation_python(),
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
                _validation_python(),
                "scripts/check_replay_payload_resolution_report.py",
                "--report",
                str(replay_path),
            ]
            if args.resolve_payloads
            else [],
        ),
    ]
    validation_steps.extend(projector_fetch_steps)
    validation_steps.extend(projector_check_steps)
    validation_steps.extend(worker_fetch_steps)
    validation_steps.extend(worker_check_steps)

    for name, command in validation_steps:
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
                    projector_summaries=projector_summaries,
                    worker_metrics=worker_metrics,
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
                    projector_summaries=projector_summaries,
                    worker_metrics=worker_metrics,
                    steps=steps,
                    started_at=started_at,
                ),
                args.report_output,
            )
            return 1

    artifact_index_command: list[str] | None = None
    if args.artifact_index_output:
        artifact_index_command = [
            _validation_python(),
            "scripts/package_replay_validation_artifacts.py",
            "--manifest",
            str(args.report_output),
            "--output",
            str(args.artifact_index_output),
        ]
        for summary in projector_summaries:
            artifact_index_command.extend(
                [
                    "--artifact",
                    f"{summary['role']}={summary['path']}",
                ]
            )
        for metrics in worker_metrics:
            artifact_index_command.extend(
                [
                    "--artifact",
                    f"{metrics['role']}={metrics['path']}",
                ]
            )
        steps.append(
            {
                "name": "artifact_index",
                "command": artifact_index_command,
                "returncode": 0,
                "duration_seconds": 0.0,
                "stdout": json.dumps(
                    {"output": str(args.artifact_index_output), "matched": True},
                    sort_keys=True,
                ),
                "stderr": "",
                "stdout_json": {
                    "output": str(args.artifact_index_output),
                    "matched": True,
                },
            }
        )

    _emit_report(
        _build_report(
            matched=True,
            args=args,
            replay_path=replay_path,
            live_checksums_path=live_checksums_path,
            live_rows_path=live_rows_path,
            projector_summaries=projector_summaries,
            worker_metrics=worker_metrics,
            steps=steps,
            started_at=started_at,
        ),
        args.report_output,
    )
    if artifact_index_command:
        code, stdout, stderr, duration = _run(artifact_index_command)
        if code != 0:
            steps[-1] = {
                "name": "artifact_index",
                "command": artifact_index_command,
                "returncode": code,
                "duration_seconds": round(duration, 6),
                "stdout": stdout,
                "stderr": stderr,
            }
            stdout_json = _parse_json(stdout)
            if stdout_json is not None:
                steps[-1]["stdout_json"] = stdout_json
            _emit_report(
                _build_report(
                    matched=False,
                    args=args,
                    replay_path=replay_path,
                    live_checksums_path=live_checksums_path,
                    live_rows_path=live_rows_path,
                    projector_summaries=projector_summaries,
                    worker_metrics=worker_metrics,
                    steps=steps,
                    started_at=started_at,
                ),
                args.report_output,
            )
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
