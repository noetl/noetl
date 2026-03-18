"""Shared URL helpers for consistent NoETL API endpoint construction."""

from __future__ import annotations

from typing import Optional


def normalize_server_base_url(server_url: Optional[str]) -> str:
    """Normalize URL to host base without trailing slash or duplicate /api."""
    base = (server_url or "").strip().rstrip("/")
    while base.endswith("/api"):
        base = base[:-4]
    return base


def build_api_url(server_url: Optional[str], path: str) -> str:
    """Build an API endpoint URL with exactly one '/api' segment."""
    base = normalize_server_base_url(server_url)
    normalized_path = path.lstrip("/")
    if normalized_path.startswith("api/"):
        normalized_path = normalized_path[4:]
    return f"{base}/api/{normalized_path}"
