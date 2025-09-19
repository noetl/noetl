import os
import requests


def _base_url() -> str:
    url = os.getenv("NOETL_SERVER_URL", "http://localhost:8082").rstrip("/")
    if not url.endswith("/api"):
        url = url + "/api"
    return url


def fetch_credential_by_key(key: str) -> dict:
    """
    Fetch credential payload by key from the NoETL server.
    Expected response schema for /api/credentials/{key}?include_data=true:
      { "data": { ...decrypted_payload... } }

    In some contexts response may be nested as { data: { data: {...} } } — handle both.
    Returns the decrypted payload dict. Raises on HTTP errors or missing payload.
    """
    url = f"{_base_url()}/credentials/{key}?include_data=true"
    headers = {}
    tok = os.getenv("NOETL_SERVER_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    data = (body.get("data") or {}) if isinstance(body, dict) else {}
    # Support nested wrappers
    payload = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError(f"Credential '{key}' not found or empty payload")
    # Do NOT log secrets
    return payload

