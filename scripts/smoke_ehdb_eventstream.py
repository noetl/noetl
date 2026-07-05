#!/usr/bin/env python3
"""Smoke the EHDB Phase D bounded event-stream drain through NoETL.

Projects two already-emitted NoETL events into a fresh derived EHDB stream,
drains them through a durable consumer, acks the first, and re-consumes to
prove the durable cursor restarted (only the unacked record is pending).
Intended as a worker/playbook-local command or kind smoke step — not a server
endpoint.  The NoETL event log stays authoritative; this only touches the
derived EHDB local-reference stream.
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
from noetl.core.ehdb_eventstream import (
    EhdbEventStreamOutcome,
    ack_ehdb_event,
    consume_ehdb_events,
    project_ehdb_event,
)


def run_smoke(
    *,
    helper_bin: str | None = None,
    log_path: Path | None = None,
    role: str = "worker",
    stream: str = "noetl-smoke-events",
    consumer: str = "noetl-smoke-consumer",
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

    first = project_ehdb_event(
        stream, "noetl.execution.completed", '{"seq":1}',
        env=source_env, timeout_seconds=timeout_seconds,
    )
    if first.outcome is not EhdbEventStreamOutcome.PROJECTED:
        raise RuntimeError(f"first project not PROJECTED: {first.as_dict()}")

    second = project_ehdb_event(
        stream, "noetl.execution.completed", '{"seq":2}',
        env=source_env, timeout_seconds=timeout_seconds,
    )
    if second.outcome is not EhdbEventStreamOutcome.PROJECTED:
        raise RuntimeError(f"second project not PROJECTED: {second.as_dict()}")

    consumed = consume_ehdb_events(
        stream, consumer, env=source_env, timeout_seconds=timeout_seconds
    )
    if consumed.outcome is not EhdbEventStreamOutcome.CONSUMED:
        raise RuntimeError(f"consume not CONSUMED: {consumed.as_dict()}")
    if consumed.consume is None or consumed.consume.pending_count != 2:
        raise RuntimeError(f"expected 2 pending, got: {consumed.as_dict()}")
    if not consumed.consume.created_consumer:
        raise RuntimeError(f"expected consumer creation, got: {consumed.as_dict()}")

    acked = ack_ehdb_event(
        stream, consumer, 1, env=source_env, timeout_seconds=timeout_seconds
    )
    if acked.outcome is not EhdbEventStreamOutcome.ACKED:
        raise RuntimeError(f"ack not ACKED: {acked.as_dict()}")

    reconsumed = consume_ehdb_events(
        stream, consumer, env=source_env, timeout_seconds=timeout_seconds
    )
    if reconsumed.consume is None or reconsumed.consume.pending_count != 1:
        raise RuntimeError(f"expected 1 pending after ack, got: {reconsumed.as_dict()}")
    if reconsumed.consume.created_consumer:
        raise RuntimeError(f"durable consumer should not be recreated: {reconsumed.as_dict()}")
    if reconsumed.consume.acked_sequence != 1:
        raise RuntimeError(f"expected cursor at 1, got: {reconsumed.as_dict()}")

    return {
        "project_first": first.as_dict(),
        "project_second": second.as_dict(),
        "consume": consumed.as_dict(),
        "ack": acked.as_dict(),
        "reconsume": reconsumed.as_dict(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded NoETL smoke against the EHDB Phase D event stream.",
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
        print(f"EHDB event-stream smoke failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, sort_keys=True))
    return 0


def _temporary_log_path() -> Path:
    handle = tempfile.NamedTemporaryFile(
        prefix="noetl-ehdb-eventstream-smoke-",
        suffix=".jsonl",
        delete=False,
    )
    handle.close()
    return Path(handle.name)


if __name__ == "__main__":
    raise SystemExit(main())
