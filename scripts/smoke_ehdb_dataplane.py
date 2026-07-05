#!/usr/bin/env python3
"""Smoke the EHDB Phase C bounded data-plane append/read through NoETL.

Appends two domain records to a fresh local-reference stream and reads them
back, asserting the bounded append/read roundtrip works for a worker role.
Intended as a worker/playbook-local command or kind smoke step — not a server
endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from noetl.core.ehdb_adapter import EHDB_HELPER_BIN_ENV
from noetl.core.ehdb_contract import (
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_LOCAL_REFERENCE_LOG_ENV,
    EHDB_MODE_ENV,
)
from noetl.core.ehdb_dataplane import (
    EhdbDataPlaneOutcome,
    append_ehdb_domain_record,
    read_ehdb_domain_records,
)


def run_smoke(
    *,
    helper_bin: str | None = None,
    log_path: Path | None = None,
    role: str = "worker",
    stream: str = "noetl-smoke-domain",
    timeout_seconds: float = 30.0,
    env: Mapping[str, str] | None = None,
) -> Mapping[str, object]:
    source_env = dict(os.environ if env is None else env)
    log_path = log_path or _temporary_log_path()
    source_env.update(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "local_reference",
            EHDB_CLIENT_ROLE_ENV: role,
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
        }
    )
    if helper_bin is not None:
        source_env[EHDB_HELPER_BIN_ENV] = helper_bin

    first = append_ehdb_domain_record(
        stream, f"{stream}.created", '{"seq":1}',
        env=source_env, timeout_seconds=timeout_seconds,
    )
    if first.outcome is not EhdbDataPlaneOutcome.APPENDED:
        raise RuntimeError(f"first append not APPENDED: {first.as_dict()}")

    second = append_ehdb_domain_record(
        stream, f"{stream}.updated", '{"seq":2}',
        env=source_env, timeout_seconds=timeout_seconds,
    )
    if second.outcome is not EhdbDataPlaneOutcome.APPENDED:
        raise RuntimeError(f"second append not APPENDED: {second.as_dict()}")

    read = read_ehdb_domain_records(
        stream, env=source_env, timeout_seconds=timeout_seconds
    )
    if read.outcome is not EhdbDataPlaneOutcome.READ:
        raise RuntimeError(f"read not READ: {read.as_dict()}")
    if read.read is None or read.read.record_count != 2:
        raise RuntimeError(f"expected 2 records, got: {read.as_dict()}")

    return {
        "append_first": first.as_dict(),
        "append_second": second.as_dict(),
        "read": read.as_dict(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded NoETL smoke against the EHDB Phase C data plane.",
    )
    parser.add_argument("--helper-bin", help="Path to ehdb-local-reference. Defaults to NoETL discovery.")
    parser.add_argument("--log", type=Path, help="EHDB JSONL log. Defaults to a temp path.")
    parser.add_argument("--role", default="worker", help="worker|playbook|system. Default: worker.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Helper timeout seconds. Default: 30.")
    args = parser.parse_args(argv)

    try:
        payload = run_smoke(
            helper_bin=args.helper_bin,
            log_path=args.log,
            role=args.role,
            timeout_seconds=args.timeout,
        )
    except Exception as exc:
        print(f"EHDB data-plane smoke failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, sort_keys=True))
    return 0


def _temporary_log_path() -> Path:
    handle = tempfile.NamedTemporaryFile(
        prefix="noetl-ehdb-dataplane-smoke-",
        suffix=".jsonl",
        delete=False,
    )
    handle.close()
    return Path(handle.name)


if __name__ == "__main__":
    raise SystemExit(main())
