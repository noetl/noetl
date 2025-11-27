from __future__ import annotations

from typing import Optional


def normalize_server_url(url: Optional[str], ensure_api: bool = True) -> str:
    """Ensure server URL has http(s) scheme and optional '/api' suffix."""
    base = (url or "").strip()
    if not base:
        base = "http://localhost:8082"
    if not (base.startswith("http://") or base.startswith("https://")):
        base = "http://" + base
    base = base.rstrip("/")
    if ensure_api and not base.endswith("/api"):
        base = base + "/api"
    return base
