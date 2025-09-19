"""
Worker-side helpers to fetch credentials from the NoETL server.

These helpers return credential metadata merged with decrypted payload
when include_data=true is supported by the server endpoint.
"""

from __future__ import annotations

import os
from typing import Dict, List

import httpx


def _server_base() -> str:
    base = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
    if not base.endswith('/api'):
        base = base + '/api'
    return base


def fetch_credential_by_key(key: str) -> Dict:
    if not key:
        return {}
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
            except Exception:
                pass
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
