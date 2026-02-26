"""
Worker-side helpers to fetch credentials from the NoETL server.

These helpers return credential metadata merged with decrypted payload
when include_data=true is supported by the server endpoint.
"""

from __future__ import annotations

from typing import Dict, List, Optional
import os
import time
import threading

import httpx
from noetl.core.config import get_worker_settings

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)


_CACHE_TTL_SECONDS = max(1.0, float(os.getenv("NOETL_CREDENTIAL_CACHE_TTL_SECONDS", "300")))
_CACHE_MAX_ENTRIES = max(1, int(os.getenv("NOETL_CREDENTIAL_CACHE_MAX_ENTRIES", "256")))
_FETCH_TIMEOUT_SECONDS = max(0.1, float(os.getenv("NOETL_CREDENTIAL_FETCH_TIMEOUT_SECONDS", "5.0")))
_FETCH_RETRIES = max(1, int(os.getenv("NOETL_CREDENTIAL_FETCH_RETRIES", "3")))
_FETCH_BACKOFF_SECONDS = max(0.0, float(os.getenv("NOETL_CREDENTIAL_FETCH_BACKOFF_SECONDS", "0.2")))

_credential_cache: Dict[str, tuple[float, Dict]] = {}
_cache_lock = threading.Lock()


def _server_base() -> str:
    """
    Get server API base URL from centralized worker settings.
    Falls back to localhost if settings unavailable.
    """
    try:
        worker_settings = get_worker_settings()
        return worker_settings.server_api_url
    except Exception:
        # Fallback for cases where settings aren't initialized
        return 'http://localhost:8082/api'


def _normalize_credential_record(key: str, body: Dict) -> Dict:
    data = body.get('data') or {}
    payload = data.get('data') if isinstance(data, dict) and isinstance(data.get('data'), dict) else data
    payload = payload if isinstance(payload, dict) else {}
    rec = {
        'key': key,
        'type': (body.get('type') or body.get('credential_type') or '').lower(),
        'service': (body.get('service') or body.get('provider') or body.get('kind') or '').lower(),
        'secret_name': body.get('secret_name') or body.get('name') or key,
        'scope': body.get('scope') or body.get('path') or None,
        'data': payload,
    }
    for k, v in payload.items():
        if k not in rec:
            rec[k] = v
    if not rec['service']:
        t = rec['type']
        if 'postgres' in t:
            rec['service'] = 'postgres'
        elif 'gcs' in t:
            rec['service'] = 'gcs'
        elif 's3' in t:
            rec['service'] = 's3'
        elif 'azure' in t:
            rec['service'] = 'azure'
    return rec


def _get_cached_credential(key: str, allow_stale: bool = False) -> Optional[Dict]:
    now = time.time()
    with _cache_lock:
        entry = _credential_cache.get(key)
        if not entry:
            return None
        ts, rec = entry
        if now - ts <= _CACHE_TTL_SECONDS:
            return dict(rec)
        if allow_stale:
            return dict(rec)
    return None


def _set_cached_credential(key: str, record: Dict) -> None:
    now = time.time()
    with _cache_lock:
        _credential_cache[key] = (now, dict(record))
        if len(_credential_cache) <= _CACHE_MAX_ENTRIES:
            return
        # Evict oldest entries first.
        for stale_key, _ in sorted(_credential_cache.items(), key=lambda item: item[1][0])[: len(_credential_cache) - _CACHE_MAX_ENTRIES]:
            _credential_cache.pop(stale_key, None)


def fetch_credential_by_key(key: str) -> Dict:
    if not key:
        return {}
    cached = _get_cached_credential(key)
    if cached:
        return cached

    # Try to use endpoint property, fallback to old URL building
    try:
        worker_settings = get_worker_settings()
        url = worker_settings.endpoint_credential_by_key(key, include_data=True)
    except Exception:
        url = f"{_server_base()}/credentials/{key}?include_data=true"

    last_error: Optional[str] = None
    for attempt in range(1, _FETCH_RETRIES + 1):
        try:
            with httpx.Client(timeout=_FETCH_TIMEOUT_SECONDS) as c:
                r = c.get(url)
            if r.status_code == 200:
                body = r.json() or {}
                rec = _normalize_credential_record(key, body)
                _set_cached_credential(key, rec)
                return rec
            if r.status_code == 404:
                last_error = "not_found"
                break
            last_error = f"http_{r.status_code}"
        except Exception as exc:
            last_error = type(exc).__name__

        if attempt < _FETCH_RETRIES and _FETCH_BACKOFF_SECONDS > 0:
            time.sleep(_FETCH_BACKOFF_SECONDS * (2 ** (attempt - 1)))

    stale = _get_cached_credential(key, allow_stale=True)
    if stale:
        logger.warning(
            "Credential fetch failed for key=%s (reason=%s); using stale cache entry",
            key,
            last_error or "unknown",
        )
        return stale

    logger.warning(
        "Credential fetch failed for key=%s (reason=%s)",
        key,
        last_error or "unknown",
    )
    return {}


def fetch_credentials_by_keys(keys: List[str]) -> Dict[str, Dict]:
    res: Dict[str, Dict] = {}
    for k in keys or []:
        if not isinstance(k, str) or not k:
            continue
        if k in res:
            continue
        rec = fetch_credential_by_key(k)
        if rec:
            res[k] = rec
    return res


__all__ = ['fetch_credential_by_key', 'fetch_credentials_by_keys']
