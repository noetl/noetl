#!/usr/bin/env python
"""Fetch replay state JSON for offline parity and payload-resolution gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _build_url(args: argparse.Namespace) -> str:
    base_url = str(args.base_url).rstrip("/")
    params: dict[str, str | int] = {
        "execution_id": int(args.execution_id),
        "tenant_id": args.tenant_id,
        "organization_id": args.organization_id,
        "projection": args.projection,
        "limit": int(args.limit),
        "resolve_payloads": "true" if args.resolve_payloads else "false",
    }
    if args.as_of_event_id is not None:
        params["as_of_event_id"] = int(args.as_of_event_id)
    if args.as_of_position is not None:
        params["as_of_position"] = int(args.as_of_position)
    if args.as_of_time is not None:
        params["as_of_time"] = args.as_of_time
    return f"{base_url}/api/replay/state?{urlencode(params)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch NoETL replay state JSON for validation gates",
    )
    parser.add_argument("--base-url", required=True, help="NoETL server base URL")
    parser.add_argument("--execution-id", required=True, type=int)
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--organization-id", default="default")
    parser.add_argument("--projection", default="all")
    parser.add_argument("--limit", default=100000, type=int)
    parser.add_argument("--as-of-event-id", type=int)
    parser.add_argument("--as-of-position", type=int)
    parser.add_argument("--as-of-time")
    parser.add_argument("--resolve-payloads", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", default=60.0, type=float)
    args = parser.parse_args(argv)

    cutoff_count = sum(
        value is not None
        for value in (args.as_of_event_id, args.as_of_position, args.as_of_time)
    )
    if cutoff_count > 1:
        parser.error("use only one replay cutoff")

    request = Request(_build_url(args), headers={"Accept": "application/json"})
    with urlopen(request, timeout=args.timeout) as response:
        body = response.read()
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("replay state response must be a JSON object")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "bytes": len(body)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
