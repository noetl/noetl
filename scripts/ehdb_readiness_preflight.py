#!/usr/bin/env python3
"""Worker/playbook-local EHDB readiness preflight command.

Runs the bounded, stateless EHDB local-reference readiness evaluation for the
current role and prints a secret-free JSON report.  Intended as a
worker/playbook-local command or kind smoke step — deliberately *not* a server
endpoint, so the control-plane boundary is preserved.

Exit codes:

* ``0`` — ready (``disabled`` / ``control_plane`` / ``ready`` / ``empty``);
  also ``truncated`` / ``unavailable`` unless ``--strict`` is given.
* ``3`` — degraded (``truncated`` / ``unavailable``) with ``--strict``.
* ``4`` — control-plane guard refused a data-plane read (misconfiguration).
* ``5`` — invalid EHDB configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from noetl.core.ehdb_readiness import (
    EhdbReadinessOutcome,
    evaluate_ehdb_readiness,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded EHDB local-reference readiness preflight.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Readiness helper timeout in seconds (clamped 0.1-30). "
        "Defaults to NOETL_EHDB_READINESS_TIMEOUT_SECONDS or 5s.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat degraded (truncated/unavailable) outcomes as failure.",
    )
    args = parser.parse_args(argv)

    result = evaluate_ehdb_readiness(timeout_seconds=args.timeout)
    print(json.dumps(result.as_dict(), sort_keys=True))

    if result.outcome is EhdbReadinessOutcome.GUARD_REFUSED:
        return 4
    if result.outcome is EhdbReadinessOutcome.INVALID:
        return 5
    if args.strict and result.degraded:
        return 3
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
