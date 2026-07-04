#!/usr/bin/env python3
"""Worker/playbook-local EHDB bounded data-plane step (Phase C).

Appends or reads a single bounded domain record through the EHDB
local-reference adapter and prints a secret-free JSON report.  Intended as a
worker/playbook-local command or kind smoke step — deliberately *not* a server
endpoint, so the control-plane boundary is preserved.

Exit codes:

* ``0`` — ok (``disabled`` / ``appended`` / ``read`` / ``absent``); also
  ``truncated`` / ``unavailable`` unless ``--strict`` is given.
* ``2`` — request rejected by a NoETL bound (``rejected``).
* ``3`` — degraded (``truncated`` / ``unavailable``) with ``--strict``.
* ``4`` — control-plane guard refused a data-plane operation.
* ``5`` — invalid EHDB configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from noetl.core.ehdb_dataplane import (
    EhdbDataPlaneOutcome,
    append_ehdb_domain_record,
    read_ehdb_domain_records,
)


def _exit_code(outcome: EhdbDataPlaneOutcome, *, strict: bool, degraded: bool, ok: bool) -> int:
    if outcome is EhdbDataPlaneOutcome.GUARD_REFUSED:
        return 4
    if outcome is EhdbDataPlaneOutcome.INVALID:
        return 5
    if outcome is EhdbDataPlaneOutcome.REJECTED:
        return 2
    if strict and degraded:
        return 3
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded EHDB local-reference data-plane append/read.",
    )
    parser.add_argument("--strict", action="store_true", help="Treat degraded outcomes as failure.")
    parser.add_argument("--timeout", type=float, default=None, help="Helper timeout seconds (clamped 0.1-30).")
    parser.add_argument("--tenant", default=None, help="EHDB tenant (default: adapter default).")
    parser.add_argument("--namespace", default=None, help="EHDB namespace (default: adapter default).")

    sub = parser.add_subparsers(dest="operation", required=True)

    append = sub.add_parser("append", help="Append one bounded domain record.")
    append.add_argument("--stream", required=True)
    append.add_argument("--subject", required=True)
    append.add_argument("--payload", required=True, help="UTF-8 domain-record payload.")
    append.add_argument("--transaction-id", default=None, help="Override the app-generated id.")

    read = sub.add_parser("read", help="Read up to --limit bounded domain records.")
    read.add_argument("--stream", required=True)
    read.add_argument("--limit", type=int, default=None)
    read.add_argument("--after", type=int, default=None)

    args = parser.parse_args(argv)

    if args.operation == "append":
        result = append_ehdb_domain_record(
            args.stream,
            args.subject,
            args.payload,
            transaction_id=args.transaction_id,
            tenant=args.tenant,
            namespace=args.namespace,
            timeout_seconds=args.timeout,
        )
    else:
        result = read_ehdb_domain_records(
            args.stream,
            after=args.after,
            limit=args.limit,
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
