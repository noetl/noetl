"""
Credential resolution for DuckDB authentication.
"""

import os
from typing import Dict, Any, Optional, List

import httpx

from noetl.core.logger import setup_logger
from noetl.worker.auth_resolver import resolve_auth

from noetl.plugin.tools.duckdb.types import JinjaEnvironment, ContextDict, CredentialData, AuthType
from noetl.plugin.tools.duckdb.errors import AuthenticationError

logger = setup_logger(__name__, include_location=True)


def resolve_unified_auth(
    auth_config: Dict[str, Any],
    jinja_env: JinjaEnvironment,
    context: ContextDict
) -> Dict[str, Any]:
    """
    Resolve unified authentication configuration.
    
    Args:
        auth_config: Authentication configuration
        jinja_env: Jinja2 environment for template rendering
        context: Context for rendering
        
    Returns:
        Dictionary mapping auth alias to resolved auth data
        
    Raises:
        AuthenticationError: If auth resolution fails
    """
    try:
        resolved_auth_map = {}
        
        if not auth_config:
            logger.debug("No auth configuration provided")
            return resolved_auth_map
            
        logger.debug("Resolving unified auth system")
        
        # Handle single auth config vs alias map
        if isinstance(auth_config, dict) and not any(
            isinstance(v, dict) and ('type' in v or 'credential' in v or 'secret' in v or 'env' in v or 'inline' in v)
            for v in auth_config.values()
        ):
            # Single auth config - auto-wrap as 'default' alias
            logger.debug("Auto-wrapping single auth config as 'default' alias")
            mode, resolved_items = resolve_auth(auth_config, jinja_env, context)
            if mode == 'single' and resolved_items:
                resolved_auth_map['default'] = list(resolved_items.values())[0]
            elif resolved_items:
                resolved_auth_map = resolved_items
        else:
            # Alias map - resolve each alias
            mode, resolved_items = resolve_auth(auth_config, jinja_env, context)
            resolved_auth_map = resolved_items
            
        logger.debug(f"Resolved unified auth with {len(resolved_auth_map)} aliases")
        return resolved_auth_map
        
    except Exception as e:
        raise AuthenticationError(f"Failed to resolve unified auth: {e}")


def resolve_credentials(
    credentials_config: Optional[Dict[str, Any]],
    jinja_env: JinjaEnvironment,
    context: ContextDict
) -> Dict[str, CredentialData]:
    """
    Resolve legacy credentials configuration.
    
    Args:
        credentials_config: Legacy credentials configuration  
        jinja_env: Jinja2 environment for template rendering
        context: Context for rendering
        
    Returns:
        Dictionary mapping alias to CredentialData
        
    Raises:
        AuthenticationError: If credential resolution fails
    """
    resolved_creds = {}
    
    if not credentials_config:
        return resolved_creds
        
    try:
        # Normalize mapping -> list with alias injected
        normalized_list = []
        if isinstance(credentials_config, dict):
            for alias, spec in credentials_config.items():
                if isinstance(spec, dict):
                    entry = dict(spec)
                    entry.setdefault('alias', alias)
                    normalized_list.append(entry)
        elif isinstance(credentials_config, list):
            normalized_list = [e for e in credentials_config if isinstance(e, dict)]
            
        # Fetch each referenced credential
        if normalized_list:
            for entry in normalized_list:
                try:
                    cred_data = _resolve_single_credential(entry)
                    if cred_data:
                        resolved_creds[cred_data.alias] = cred_data
                except Exception as e:
                    logger.warning(f"Failed to resolve credential entry {entry}: {e}")
                    
        logger.debug(f"Resolved {len(resolved_creds)} legacy credentials")
        return resolved_creds
        
    except Exception as e:
        raise AuthenticationError(f"Failed to resolve legacy credentials: {e}")


def _resolve_single_credential(entry: Dict[str, Any]) -> Optional[CredentialData]:
    """
    Resolve a single credential entry.
    
    Args:
        entry: Credential entry configuration
        
    Returns:
        CredentialData instance or None if resolution fails
    """
    alias = entry.get('alias') or 'cred'
    ref = entry.get('key') or entry.get('credential') or entry.get('credentialRef')
    
    if not isinstance(ref, str) or not ref:
        return None
        
    try:
        credential_payload = _fetch_credential_from_server(ref)
        if not credential_payload:
            return None
            
        # Determine auth type from credential
        auth_type = _determine_auth_type(credential_payload)
        
        # Enhance payload with additional metadata
        enhanced_payload = dict(credential_payload)
        
        # Add connection string for Postgres credentials
        if auth_type == AuthType.POSTGRES:
            conn_str = _build_postgres_connection_string(enhanced_payload)
            if conn_str:
                enhanced_payload['connstr'] = conn_str
                
        # Expose intended DuckDB secret name
        enhanced_payload['secret'] = alias
        
        return CredentialData(
            alias=alias,
            auth_type=auth_type,
            data=enhanced_payload,
            scope=entry.get('scope')
        )
        
    except Exception as e:
        logger.warning(f"Failed to resolve credential '{ref}': {e}")
        return None


def _fetch_credential_from_server(credential_ref: str) -> Optional[Dict[str, Any]]:
    """
    Fetch credential data from NoETL server.
    
    Args:
        credential_ref: Credential reference/key
        
    Returns:
        Credential data or None if not found
    """
    try:
        base_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
        if not base_url.endswith('/api'):
            base_url = base_url + '/api'
            
        url = f"{base_url}/credentials/{credential_ref}?include_data=true"
        
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url)
            
            if response.status_code == 200:
                body = response.json() or {}
                raw = body.get('data') or {}
                
                # Handle nested data structure
                payload = raw.get('data') if isinstance(raw, dict) and isinstance(raw.get('data'), dict) else raw
                return payload if isinstance(payload, dict) else {}
            else:
                logger.warning(f"Credential '{credential_ref}' not found: HTTP {response.status_code}")
                return None
                
    except Exception as e:
        logger.warning(f"Failed to fetch credential '{credential_ref}': {e}")
        return None


def _determine_auth_type(credential_data: Dict[str, Any]) -> AuthType:
    """
    Determine authentication type from credential data.
    
    Args:
        credential_data: Credential payload
        
    Returns:
        AuthType enum value
    """
    # Look for type indicators in the credential data
    if any(k in credential_data for k in ['db_host', 'db_port', 'db_user', 'db_password']):
        return AuthType.POSTGRES
    elif any(k in credential_data for k in ['key_id', 'secret_key']) and 'host' not in credential_data:
        # Likely cloud HMAC credentials
        if 'gcs' in str(credential_data).lower():
            return AuthType.GCS_HMAC
        else:
            return AuthType.S3_HMAC
    else:
        # Default fallback
        return AuthType.POSTGRES


def _build_postgres_connection_string(payload: Dict[str, Any]) -> Optional[str]:
    """
    Build PostgreSQL connection string from credential payload.
    
    Args:
        payload: Credential data
        
    Returns:
        Connection string or None if incomplete
    """
    host = payload.get('db_host') or payload.get('host')
    port = payload.get('db_port') or payload.get('port')
    user = payload.get('db_user') or payload.get('user')
    password = payload.get('db_password') or payload.get('password')
    dbname = payload.get('db_name') or payload.get('dbname') or payload.get('database')
    
    if all([host, port, user, password, dbname]):
        return f"dbname={dbname} user={user} password={password} host={host} port={port}"
    
    return None