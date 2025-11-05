"""
Worker-side helpers to fetch credentials from the NoETL server.

These helpers return credential metadata merged with decrypted payload
when include_data=true is supported by the server endpoint.
"""

from __future__ import annotations

from typing import Dict, List
import logging

import httpx
from noetl.core.config import get_worker_settings

logger = logging.getLogger(__name__)


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


def fetch_credential_by_key(key: str) -> Dict:
    if not key:
        return {}
    # Try to use endpoint property, fallback to old URL building
    try:
        worker_settings = get_worker_settings()
        url = worker_settings.endpoint_credential_by_key(key, include_data=True)
    except Exception:
        url = f"{_server_base()}/credentials/{key}?include_data=true"
    
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(url)
            if r.status_code != 200:
                return {}
            body = r.json() or {}
            data = body.get('data') or {}
            payload = data.get('data') if isinstance(data, dict) and isinstance(data.get('data'), dict) else data
            payload = payload if isinstance(payload, dict) else {}
            # Normalize fields
            rec = {
                'key': key,
                'type': (body.get('type') or body.get('credential_type') or '').lower(),
                'service': (body.get('service') or body.get('provider') or body.get('kind') or '').lower(),
                'secret_name': body.get('secret_name') or body.get('name') or key,
                'scope': body.get('scope') or body.get('path') or None,
                'data': payload,
            }
            # Promote commonly used fields to top-level for consumers expecting a flat mapping
            try:
                for k, v in payload.items():
                    # Avoid overwriting normalized meta keys
                    if k not in rec:
                        rec[k] = v
            except (TypeError, AttributeError) as e:
                logger.warning(f"Could not flatten credential payload fields: {e}")
            # If service missing, infer from type
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
    except Exception:
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
