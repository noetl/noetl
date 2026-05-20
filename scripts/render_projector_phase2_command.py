#!/usr/bin/env python
"""Render a reproducible Phase 2 projector validation command."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path


def render_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "scripts/run_projector_phase2_validation.py",
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
        "--output-dir",
        str(args.output_dir),
    ]
    if args.live_rows:
        command.extend(["--live-rows", str(args.live_rows)])
    if args.live_checksums:
        command.extend(["--live-checksums", str(args.live_checksums)])
    if args.export_live_rows_postgres:
        command.append("--export-live-rows-postgres")
    if args.require_projection_parity:
        command.append("--require-projection-parity")
    for url in args.projector_summary_url:
        command.extend(["--projector-summary-url", url])
    for path in args.projector_summary:
        command.extend(["--projector-summary", str(path)])
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a Phase 2 projector validation command")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--execution-id", required=True, type=int)
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--organization-id", default="default")
    parser.add_argument("--projection", default="all")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--live-rows", type=Path)
    parser.add_argument("--live-checksums", type=Path)
    parser.add_argument("--export-live-rows-postgres", action="store_true")
    parser.add_argument("--projector-summary-url", action="append", default=[], metavar="NAME=URL")
    parser.add_argument("--projector-summary", action="append", default=[], type=Path)
    parser.add_argument("--require-projection-parity", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit JSON with argv and shell fields")
    args = parser.parse_args(argv)

    live_inputs = sum(
        1
        for enabled in (
            bool(args.live_rows),
            bool(args.live_checksums),
            bool(args.export_live_rows_postgres),
        )
        if enabled
    )
    if live_inputs > 1:
        parser.error("use only one live parity input")
    if not args.projector_summary and not args.projector_summary_url:
        parser.error("provide at least one projector summary source")

    command = render_command(args)
    shell = " ".join(shlex.quote(part) for part in command)
    if args.json:
        print(json.dumps({"argv": command, "shell": shell}, indent=2, sort_keys=True))
    else:
        print(shell)
    return 0


if __name__ == "__main__":
    sys.exit(main())
