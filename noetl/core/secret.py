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
    """Obtain GCP OAuth2 access token from service account credentials.
    
    Args:
        scopes: OAuth2 scopes (default: cloud-platform)
        credentials_path: Path to service account JSON file
        use_metadata: Whether to use GCE metadata server
        service_account_secret: GCP Secret Manager path to credentials
        credentials_info: Service account JSON as dict
        
    Returns:
        Dict with access_token, token_expiry, scopes
    """
    import os
    
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except ImportError:
        raise ImportError(
            "google-auth library is required for GCP token generation. "
            "Install it with: pip install google-auth"
        )
    
    # Normalize scopes
    if scopes is None:
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    elif isinstance(scopes, str):
        scopes = [scopes]
    elif isinstance(scopes, Iterable) and not isinstance(scopes, (str, bytes)):
        scopes = list(scopes)
    else:
        scopes = [str(scopes)]
    
    # Determine credential source
    creds = None
    source = None
    
    # 1. Try metadata server (GCE/GKE)
    if use_metadata:
        try:
            from google.auth import compute_engine
            creds = compute_engine.Credentials()
            source = "metadata"
        except Exception as e:
            raise RuntimeError(f"Failed to get credentials from metadata server: {e}")
    
    # 2. Try credentials_info (dict)
    elif credentials_info is not None:
        try:
            if isinstance(credentials_info, str):
                credentials_info = json.loads(credentials_info)
            creds = service_account.Credentials.from_service_account_info(
                credentials_info, scopes=scopes
            )
            source = "inline"
        except Exception as e:
            raise RuntimeError(f"Failed to create credentials from info dict: {e}")
    
    # 3. Try credentials_path (file)
    elif credentials_path is not None:
        try:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(f"Credentials file not found: {credentials_path}")
            creds = service_account.Credentials.from_service_account_file(
                credentials_path, scopes=scopes
            )
            source = "path"
        except Exception as e:
            raise RuntimeError(f"Failed to load credentials from {credentials_path}: {e}")
    
    # 4. Try Secret Manager
    elif service_account_secret is not None:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            response = client.access_secret_version(name=service_account_secret)
            secret_data = json.loads(response.payload.data.decode('UTF-8'))
            creds = service_account.Credentials.from_service_account_info(
                secret_data, scopes=scopes
            )
            source = "secret"
        except Exception as e:
            raise RuntimeError(f"Failed to get credentials from Secret Manager: {e}")
    
    else:
        raise ValueError(
            "No credential source specified. Provide one of: "
            "credentials_info, credentials_path, use_metadata=True, or service_account_secret"
        )
    
    # Refresh the token
    try:
        creds.refresh(Request())
    except Exception as e:
        raise RuntimeError(f"Failed to refresh access token: {e}")
    
    # Get expiry time
    expiry_str = None
    if creds.expiry:
        expiry_str = creds.expiry.isoformat() + "Z"
    
    return {
        "access_token": creds.token,
        "token_expiry": expiry_str,
        "scopes": scopes,
        "metadata_used": bool(use_metadata),
        "credential_source": source,
    }

