#!/usr/bin/env python3
"""Smoke the EHDB local-reference summary helper through NoETL."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from noetl.core.ehdb_adapter import (
    EHDB_HELPER_BIN_ENV,
    execute_ehdb_local_reference_summary_from_env,
)
from noetl.core.ehdb_contract import (
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_LOCAL_REFERENCE_LOG_ENV,
    EHDB_MODE_ENV,
)


REQUIRED_SUMMARY_FIELDS = (
    "log_path",
    "transaction_count",
    "table_count",
    "snapshot_count",
    "scan_grant_count",
    "stream_count",
    "stream_record_count",
    "stream_consumer_count",
    "retrieval_document_count",
    "retrieval_chunk_count",
    "retrieval_embedding_count",
    "system_library_count",
    "system_binding_count",
    "storage_object_count",
    "storage_replica_count",
)


def run_smoke(
    *,
    helper_bin: str | None = None,
    log_path: Path | None = None,
    timeout_seconds: float = 30.0,
    env: Mapping[str, str] | None = None,
) -> Mapping[str, object]:
    source_env = dict(os.environ if env is None else env)
    log_path = log_path or _temporary_log_path()
    source_env.update(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "local_reference",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
        }
    )
    if helper_bin is not None:
        source_env[EHDB_HELPER_BIN_ENV] = helper_bin

    execution = execute_ehdb_local_reference_summary_from_env(
        source_env,
        timeout_seconds=timeout_seconds,
    )
    if execution is None:
        raise RuntimeError("EHDB local-reference summary smoke was unexpectedly disabled")

    missing = [field for field in REQUIRED_SUMMARY_FIELDS if field not in execution.json_payload]
    if missing:
        raise ValueError(f"EHDB summary missing required fields: {', '.join(missing)}")
    if execution.json_payload["log_path"] != str(log_path):
        raise ValueError("EHDB summary log_path does not match requested log")
    return execution.json_payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded NoETL smoke against ehdb-local-reference summary.",
    )
    parser.add_argument(
        "--helper-bin",
        help="Path to ehdb-local-reference. Defaults to NoETL discovery.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        help="EHDB JSONL log to summarize. Defaults to a temporary empty log path.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Helper timeout in seconds. Default: 30.",
    )
    args = parser.parse_args(argv)

    try:
        payload = run_smoke(
            helper_bin=args.helper_bin,
            log_path=args.log,
            timeout_seconds=args.timeout,
        )
    except Exception as exc:
        print(f"EHDB local-reference summary smoke failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, sort_keys=True))
    return 0


def _temporary_log_path() -> Path:
    handle = tempfile.NamedTemporaryFile(
        prefix="noetl-ehdb-summary-smoke-",
        suffix=".jsonl",
        delete=False,
    )
    handle.close()
    return Path(handle.name)


if __name__ == "__main__":
    raise SystemExit(main())
