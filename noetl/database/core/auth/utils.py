"""
Utility functions for authentication processing.
"""

import os
from typing import Dict, Any, Optional
from jinja2 import Environment

from noetl.core.logger import setup_logger
from .constants import REDACTED_FIELDS

logger = setup_logger(__name__, include_location=True)


def deep_render_template(jinja_env: Environment, context: Dict, obj: Any) -> Any:
    """
    Recursively render Jinja templates in nested objects.
    
    Args:
        jinja_env: Jinja2 environment
        context: Template context
        obj: Object to render (can be dict, list, string, or primitive)
        
    Returns:
        Rendered object with templates resolved
    """
    if isinstance(obj, str):
        try:
            template = jinja_env.from_string(obj)
            return template.render(context)
        except Exception as e:
            logger.debug(f"AUTH: Failed to render template '{obj}': {e}")
            return obj
    elif isinstance(obj, dict):
        return {k: deep_render_template(jinja_env, context, v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [deep_render_template(jinja_env, context, item) for item in obj]
    else:
        return obj


def redact_dict(data: Dict) -> Dict:
    """
    Create a redacted copy of a dictionary for safe logging.
    
    Args:
        data: Dictionary to redact
        
    Returns:
        Dictionary with sensitive fields redacted
    """
    result = {}
    for key, value in data.items():
        if key.lower() in REDACTED_FIELDS or "password" in key.lower() or "secret" in key.lower() or "token" in key.lower():
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        else:
            result[key] = value
    return result


async def fetch_secret_manager_value(
    key: str, 
    auth_type: str,
    oauth_credential: Optional[str] = None,
    execution_id: Optional[int] = None
) -> Optional[str]:
    """
    Fetch a scalar value from an external secret manager with caching.
    
    Supports:
    - Google Secret Manager with OAuth authentication
    - Execution-scoped credential caching (1-hour TTL)
    - Environment variable fallback
    
    Args:
        key: Secret key/path (e.g., 'projects/123/secrets/name/versions/1')
        auth_type: Authentication type to determine field mapping
        oauth_credential: Optional OAuth credential name for authentication
        execution_id: Optional execution ID (integer) for caching
        
    Returns:
        Secret value or None if not found
    """
    # Check cache first if execution_id provided
    if execution_id:
        try:
            from noetl.worker.credential_cache import CredentialCache
            cached = await CredentialCache.get_cached(
                credential_name=key,
                execution_id=execution_id
            )
            if cached and isinstance(cached, dict):
                secret_value = cached.get('value')
                if secret_value:
                    logger.debug(f"AUTH: Retrieved secret '{key}' from cache (execution {execution_id})")
                    return secret_value
        except Exception as e:
            logger.debug(f"AUTH: Cache lookup failed for '{key}': {e}")
    
    # Try Google Secret Manager if key looks like a GCP resource path
    if key.startswith('projects/') and '/secrets/' in key:
        try:
            secret_value = _fetch_google_secret(key, oauth_credential)
            if secret_value:
                # Cache the secret if execution_id provided
                if execution_id:
                    try:
                        from noetl.worker.credential_cache import CredentialCache
                        await CredentialCache.set_cached(
                            credential_name=key,
                            credential_type='secret_manager',
                            data={'value': secret_value},
                            cache_type='secret',
                            execution_id=execution_id,
                            ttl_seconds=3600  # 1 hour cache
                        )
                        logger.info(f"AUTH: Cached secret '{key}' for execution {execution_id}")
                    except Exception as e:
                        logger.warning(f"AUTH: Failed to cache secret '{key}': {e}")
                
                return secret_value
        except Exception as e:
            logger.warning(f"AUTH: Failed to fetch from Google Secret Manager: {e}")
    
    # Fallback to environment variables
    env_key = f"NOETL_SECRET_{key.upper().replace('/', '_').replace('-', '_')}"
    value = os.getenv(env_key)
    if value:
        logger.debug(f"AUTH: Retrieved secret '{key}' from environment")
        return value
    
    logger.debug(f"AUTH: Secret '{key}' not found")
    return None


def _fetch_google_secret(secret_path: str, oauth_credential: Optional[str] = None) -> Optional[str]:
    """
    Fetch secret from Google Secret Manager using OAuth token.
    
    Args:
        secret_path: Full secret path (projects/PROJECT/secrets/NAME/versions/VERSION)
        oauth_credential: OAuth credential name for authentication
        
    Returns:
        Decoded secret value or None
    """
    import base64
    try:
        import httpx
    except ImportError:
        logger.error("AUTH: httpx not installed, cannot fetch from Google Secret Manager")
        return None
    
    # Get OAuth token if credential provided
    auth_header = None
    if oauth_credential:
        try:
            from noetl.core.auth.token_resolver import resolve_token
            token = resolve_token(oauth_credential)
            auth_header = f"Bearer {token}"
        except Exception as e:
            logger.error(f"AUTH: Failed to resolve OAuth token for '{oauth_credential}': {e}")
            return None
    
    # Call Secret Manager API
    url = f"https://secretmanager.googleapis.com/v1/{secret_path}:access"
    headers = {}
    if auth_header:
        headers['Authorization'] = auth_header
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # Decode base64 payload
            payload_data = data.get('payload', {}).get('data', '')
            if payload_data:
                secret_value = base64.b64decode(payload_data).decode('UTF-8')
                logger.info(f"AUTH: Successfully fetched secret from Google Secret Manager")
                return secret_value
            else:
                logger.warning(f"AUTH: Empty payload in Secret Manager response")
                return None
                
    except httpx.HTTPError as e:
        logger.error(f"AUTH: HTTP error fetching secret: {e}")
        return None
    except Exception as e:
        logger.error(f"AUTH: Error fetching secret: {e}")
        return None
