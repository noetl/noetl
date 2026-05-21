#!/usr/bin/env python
"""Run the Phase 2 projector evidence validation workflow."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.validation_stdout import parse_json_output


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    return completed.returncode, completed.stdout, completed.stderr, time.monotonic() - started


def _step(name: str, command: list[str]) -> dict[str, Any]:
    code, stdout, stderr, duration = _run(command)
    step: dict[str, Any] = {
        "name": name,
        "command": command,
        "returncode": code,
        "duration_seconds": round(duration, 6),
        "stdout": stdout,
        "stderr": stderr,
    }
    stdout_json = parse_json_output(stdout)
    if stdout_json is not None:
        step["stdout_json"] = stdout_json
    return step


def _validation_python() -> str:
    return os.environ.get("NOETL_VALIDATION_PYTHON") or sys.executable


def _emit(report: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n")
    print(rendered)


def _build_report(
    *,
    matched: bool,
    started_at: str,
    manifest_path: Path,
    artifact_index_path: Path,
    steps: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "matched": matched,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "artifacts": {
            "manifest": str(manifest_path),
            "artifact_index": str(artifact_index_path),
            "report": str(args.report_output) if args.report_output else None,
        },
        "config": {
            "base_url": args.base_url,
            "execution_id": args.execution_id,
            "tenant_id": args.tenant_id,
            "organization_id": args.organization_id,
            "projection": args.projection,
            "limit": args.limit,
            "resolve_payloads": args.resolve_payloads,
            "live_checksums": str(args.live_checksums) if args.live_checksums else None,
            "live_rows": str(args.live_rows) if args.live_rows else None,
            "export_live_rows_postgres": args.export_live_rows_postgres,
            "projector_summary": [str(path) for path in args.projector_summary],
            "projector_summary_url": list(args.projector_summary_url),
            "require_projection_parity": args.require_projection_parity,
        },
        "steps": steps,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run NoETL Phase 2 projector validation")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--execution-id", required=True, type=int)
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--organization-id", default="default")
    parser.add_argument("--projection", default="all")
    parser.add_argument("--limit", default=100000, type=int)
    parser.add_argument("--resolve-payloads", action="store_true")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout", default=60.0, type=float)
    parser.add_argument("--live-checksums", type=Path)
    parser.add_argument("--live-rows", type=Path)
    parser.add_argument("--export-live-rows-postgres", action="store_true")
    parser.add_argument("--postgres-dsn")
    parser.add_argument("--projector-summary", action="append", default=[], type=Path)
    parser.add_argument("--projector-summary-url", action="append", default=[], metavar="NAME=URL")
    parser.add_argument("--require-projection-parity", action="store_true")
    parser.add_argument("--report-output", type=Path)
    args = parser.parse_args(argv)

    if not args.projector_summary and not args.projector_summary_url:
        parser.error("provide at least one --projector-summary or --projector-summary-url")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"phase2-replay-validation-{args.execution_id}.json"
    artifact_index_path = output_dir / f"phase2-artifact-index-{args.execution_id}.json"
    started_at = _utc_now()

    replay_command = [
        _validation_python(),
        "scripts/run_replay_validation.py",
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
        "--output-dir",
        str(output_dir),
        "--timeout",
        str(args.timeout),
        "--report-output",
        str(manifest_path),
        "--artifact-index-output",
        str(artifact_index_path),
    ]
    if args.resolve_payloads:
        replay_command.append("--resolve-payloads")
    if args.live_checksums:
        replay_command.extend(["--live-checksums", str(args.live_checksums)])
    if args.live_rows:
        replay_command.extend(["--live-rows", str(args.live_rows)])
    if args.export_live_rows_postgres:
        replay_command.append("--export-live-rows-postgres")
    if args.postgres_dsn:
        replay_command.extend(["--postgres-dsn", args.postgres_dsn])
    for path in args.projector_summary:
        replay_command.extend(["--projector-summary", str(path)])
    for value in args.projector_summary_url:
        replay_command.extend(["--projector-summary-url", value])

    steps: list[dict[str, Any]] = []
    steps.append(_step("replay_validation", replay_command))
    if steps[-1]["returncode"] != 0:
        report = _build_report(
            matched=False,
            started_at=started_at,
            manifest_path=manifest_path,
            artifact_index_path=artifact_index_path,
            steps=steps,
            args=args,
        )
        _emit(report, args.report_output)
        return int(steps[-1]["returncode"])

    phase_gate_command = [
        _validation_python(),
        "scripts/check_projector_phase2_evidence.py",
        "--manifest",
        str(manifest_path),
        "--check-artifacts",
    ]
    if args.require_projection_parity:
        phase_gate_command.append("--require-projection-parity")
    steps.append(_step("phase2_evidence", phase_gate_command))

    matched = steps[-1]["returncode"] == 0
    report = _build_report(
        matched=matched,
        started_at=started_at,
        manifest_path=manifest_path,
        artifact_index_path=artifact_index_path,
        steps=steps,
        args=args,
    )
    _emit(report, args.report_output)
    return 0 if matched else int(steps[-1]["returncode"])


if __name__ == "__main__":
    sys.exit(main())
