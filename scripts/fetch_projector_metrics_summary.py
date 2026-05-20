#!/usr/bin/env python
"""Fetch projector metrics summary JSON from a live projector."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen


def _summary_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("--url must be an absolute http(s) URL")
    path = parsed.path.rstrip("/")
    if not path:
        path = "/summary"
    elif path != "/summary":
        path = f"{path}/summary"
    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


def fetch_projector_metrics_summary(url: str, *, timeout: float) -> dict[str, Any]:
    summary_url = _summary_url(url)
    try:
        with urlopen(summary_url, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"failed to fetch projector metrics summary from {summary_url}: {exc}") from exc

    data: Any = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError(f"{summary_url} returned non-object JSON")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch NoETL projector /summary JSON")
    parser.add_argument("--url", required=True, help="Projector metrics server base URL or /summary URL")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", default=10.0, type=float)
    args = parser.parse_args(argv)

    try:
        payload = fetch_projector_metrics_summary(args.url, timeout=args.timeout)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"matched": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "matched": True,
                "output": str(args.output),
                "url": _summary_url(args.url),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
