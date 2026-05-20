#!/usr/bin/env python
"""Fetch worker Prometheus metrics from a live worker metrics endpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen


def _metrics_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("--url must be an absolute http(s) URL")
    path = parsed.path.rstrip("/")
    if not path:
        path = "/metrics"
    elif path != "/metrics":
        path = f"{path}/metrics"
    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


def fetch_worker_metrics(url: str, *, timeout: float) -> str:
    metrics_url = _metrics_url(url)
    try:
        with urlopen(metrics_url, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"failed to fetch worker metrics from {metrics_url}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch NoETL worker /metrics text")
    parser.add_argument("--url", required=True, help="Worker metrics server base URL or /metrics URL")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", default=10.0, type=float)
    args = parser.parse_args(argv)

    try:
        payload = fetch_worker_metrics(args.url, timeout=args.timeout)
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"matched": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    print(
        json.dumps(
            {
                "matched": True,
                "output": str(args.output),
                "url": _metrics_url(args.url),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
