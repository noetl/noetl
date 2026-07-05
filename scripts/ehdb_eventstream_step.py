#!/usr/bin/env python3
"""Worker/playbook-local EHDB bounded event-stream step (Phase D).

Projects an already-emitted NoETL event into the derived EHDB stream, or drains
a durable consumer (consume / ack), printing a secret-free JSON report.
Intended as a worker/playbook-local command or kind smoke step — deliberately
*not* a server endpoint, so the control-plane boundary is preserved.  The NoETL
event log stays the authoritative, append-only source of truth; this step only
touches the derived EHDB local-reference stream.

Exit codes:

* ``0`` — ok (``disabled`` / ``projected`` / ``consumed`` / ``absent`` /
  ``acked``); also ``truncated`` / ``unavailable`` unless ``--strict`` is given.
* ``2`` — request rejected by a NoETL bound (``rejected``).
* ``3`` — degraded (``truncated`` / ``unavailable``) with ``--strict``.
* ``4`` — control-plane guard refused an event-stream operation.
* ``5`` — invalid EHDB configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from noetl.core.ehdb_eventstream import (
    EhdbEventStreamOutcome,
    ack_ehdb_event,
    consume_ehdb_events,
    project_ehdb_event,
)


def _exit_code(
    outcome: EhdbEventStreamOutcome, *, strict: bool, degraded: bool, ok: bool
) -> int:
    if outcome is EhdbEventStreamOutcome.GUARD_REFUSED:
        return 4
    if outcome is EhdbEventStreamOutcome.INVALID:
        return 5
    if outcome is EhdbEventStreamOutcome.REJECTED:
        return 2
    if strict and degraded:
        return 3
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded EHDB local-reference event-stream project/consume/ack.",
    )
    parser.add_argument("--strict", action="store_true", help="Treat degraded outcomes as failure.")
    parser.add_argument("--timeout", type=float, default=None, help="Helper timeout seconds (clamped 0.1-30).")
    parser.add_argument("--tenant", default=None, help="EHDB tenant (default: adapter default).")
    parser.add_argument("--namespace", default=None, help="EHDB namespace (default: adapter default).")

    sub = parser.add_subparsers(dest="operation", required=True)

    project = sub.add_parser("project", help="Mirror one NoETL event into the derived EHDB stream.")
    project.add_argument("--stream", required=True)
    project.add_argument("--subject", required=True)
    project.add_argument("--payload", required=True, help="UTF-8 event payload (already emitted to noetl.event).")
    project.add_argument("--transaction-id", default=None, help="Override the app-generated id.")

    consume = sub.add_parser("consume", help="Pull pending records for a durable consumer.")
    consume.add_argument("--stream", required=True)
    consume.add_argument("--consumer", required=True)
    consume.add_argument("--limit", type=int, default=None)
    consume.add_argument("--transaction-id", default=None, help="Override the app-generated id.")

    ack = sub.add_parser("ack", help="Advance a durable consumer cursor after materialize.")
    ack.add_argument("--stream", required=True)
    ack.add_argument("--consumer", required=True)
    ack.add_argument("--sequence", type=int, required=True)
    ack.add_argument("--transaction-id", default=None, help="Override the app-generated id.")

    args = parser.parse_args(argv)

    if args.operation == "project":
        result = project_ehdb_event(
            args.stream,
            args.subject,
            args.payload,
            transaction_id=args.transaction_id,
            tenant=args.tenant,
            namespace=args.namespace,
            timeout_seconds=args.timeout,
        )
    elif args.operation == "consume":
        result = consume_ehdb_events(
            args.stream,
            args.consumer,
            transaction_id=args.transaction_id,
            limit=args.limit,
            tenant=args.tenant,
            namespace=args.namespace,
            timeout_seconds=args.timeout,
        )
    else:
        result = ack_ehdb_event(
            args.stream,
            args.consumer,
            args.sequence,
            transaction_id=args.transaction_id,
            tenant=args.tenant,
            namespace=args.namespace,
            timeout_seconds=args.timeout,
        )

    print(json.dumps(result.as_dict(), sort_keys=True))
    return _exit_code(
        result.outcome,
        strict=args.strict,
        degraded=result.degraded,
        ok=result.ok,
    )


if __name__ == "__main__":
    raise SystemExit(main())
