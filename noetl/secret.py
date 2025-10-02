"""
Lightweight secret utilities for development and local testing.

This module provides simple JSON "encryption" and decryption helpers used by
the credentials API endpoints. In development, we only serialize/deserialize
JSON without applying cryptography so the system remains self‑contained.

If you need real encryption at rest, replace these helpers with a KMS‑backed
implementation and rotate existing records accordingly.
"""

from __future__ import annotations

from typing import Any, Iterable
import json
import datetime as _dt


def encrypt_json(data: Any) -> str:
    """Serialize data to a JSON string (dev-friendly placeholder for encryption)."""
    try:
        if isinstance(data, str):
            # If it's already a JSON-like string, store as-is
            s = data.strip()
            if (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
                return s
        return json.dumps(data, default=str)
    except Exception:
        # Last resort: stringify
        try:
            return json.dumps({"value": str(data)})
        except Exception:
            return str(data)


def decrypt_json(payload: str) -> Any:
    """Deserialize a JSON string back to Python (dev-friendly placeholder)."""
    try:
        if isinstance(payload, str):
            s = payload.strip()
            if (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
                return json.loads(s)
        return payload
    except Exception:
        return payload


def obtain_gcp_token(
    scopes: Any = None,
    credentials_path: str | None = None,
    use_metadata: bool = False,
    service_account_secret: str | None = None,
    credentials_info: Any | None = None,
) -> dict:
    """Dev stub for GCP token acquisition.

    Returns a dummy token payload sufficient for local testing of the
    credentials API without introducing external dependencies.
    """
    if scopes is None:
        scopes = "https://www.googleapis.com/auth/cloud-platform"
    if isinstance(scopes, Iterable) and not isinstance(scopes, (str, bytes)):
        scopes_out = list(scopes)
    else:
        scopes_out = [str(scopes)]
    return {
        "access_token": "dev-token-placeholder",
        "token_expiry": _dt.datetime(2099, 1, 1, 0, 0, 0).isoformat() + "Z",
        "scopes": scopes_out,
        "metadata_used": bool(use_metadata),
        "credential_source": (
            "path" if credentials_path else ("secret" if service_account_secret else ("inline" if credentials_info else None))
        ),
    }

