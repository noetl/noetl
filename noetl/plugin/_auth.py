"""
Unified authentication system for NoETL plugins.

This module provides a unified way to handle authentication across all plugin types,
replacing the previous split between auth (single), credentials (map), and secret (external).

The new system uses a single `auth:` dictionary attribute that maps aliases to typed
credential specifications, supporting various authentication types and providers.
"""

import base64
import copy
import os
from typing import Dict, Any, Optional, List, Union
from jinja2 import Environment

from noetl.utils.auth_normalize import as_mapping

from noetl.core.logger import setup_logger
from noetl.worker.secrets import fetch_credential_by_key

logger = setup_logger(__name__, include_location=True)

# Supported authentication types
AUTH_TYPES = {
    "postgres",
    "hmac", 
    "s3",
    "bearer",
    "basic", 
    "header",
    "api_key"
}

# Supported providers
AUTH_PROVIDERS = {
    "credential_store",  # Default: NoETL credential store
    "secret_manager",    # External secret manager
    "inline"            # Inline in playbook (not recommended for secrets)
}

# Fields that should be redacted in logs
REDACTED_FIELDS = {
    "db_password", "password", "secret_key", "token", "value", 
    "access_token", "refresh_token", "client_secret"
}


def _deep_render_template(jinja_env: Environment, context: Dict, obj: Any) -> Any:
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
        return {k: _deep_render_template(jinja_env, context, v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_deep_render_template(jinja_env, context, item) for item in obj]
    else:
        return obj


def _redact_dict(data: Dict) -> Dict:
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
            result[key] = _redact_dict(value)
        else:
            result[key] = value
    return result


def _fetch_secret_manager_value(key: str, auth_type: str) -> Optional[str]:
    """
    Fetch a scalar value from an external secret manager.
    
    Args:
        key: Secret key/name
        auth_type: Authentication type to determine field mapping
        
    Returns:
        Secret value or None if not found
    """
    # TODO: Implement actual secret manager integration
    # For now, check environment variables as a fallback
    env_key = f"NOETL_SECRET_{key.upper()}"
    value = os.getenv(env_key)
    if value:
        logger.debug(f"AUTH: Retrieved secret '{key}' from environment")
        return value
    
    logger.debug(f"AUTH: Secret '{key}' not found in environment")
    return None


def _normalize_postgres_fields(record: Dict) -> Dict:
    """
    Normalize postgres credential fields to standard names.
    
    Args:
        record: Raw credential record
        
    Returns:
        Normalized postgres fields
    """
    normalized = {}
    
    # Map common field variations to standard names
    field_mapping = {
        'host': 'db_host',
        'hostname': 'db_host', 
        'server': 'db_host',
        'port': 'db_port',
        'database': 'db_name',
        'db': 'db_name',
        'user': 'db_user',
        'username': 'db_user',
        'password': 'db_password',
        'ssl': 'sslmode',
        'sslmode': 'sslmode'
    }
    
    for key, value in record.items():
        mapped_key = field_mapping.get(key, key)
        if mapped_key.startswith('db_') or mapped_key == 'sslmode':
            normalized[mapped_key] = value
        elif key in field_mapping.values():
            normalized[key] = value
    
    return normalized


def _normalize_hmac_fields(record: Dict, service: str) -> Dict:
    """
    Normalize HMAC credential fields for GCS/S3.
    
    Args:
        record: Raw credential record
        service: Service type (gcs or s3)
        
    Returns:
        Normalized HMAC fields
    """
    normalized = {'service': service}
    
    # Map common field variations
    field_mapping = {
        'access_key_id': 'key_id',
        'access_key': 'key_id',
        'secret_access_key': 'secret_key',
        'secret': 'secret_key'
    }
    
    for key, value in record.items():
        mapped_key = field_mapping.get(key, key)
        normalized[mapped_key] = value
    
    return normalized


def resolve_auth_map(
    step_config: Dict, 
    task_with: Dict, 
    jinja_env: Environment, 
    context: Dict
) -> Dict[str, Dict]:
    """
    Resolve the unified auth map from step config and task_with parameters.
    
    This function:
    1. Merges auth from step (preferred) and task_with (overrides)
    2. Deep-renders templates using Jinja
    3. Fetches credential records from providers
    4. Normalizes fields according to type
    5. Returns resolved auth map ready for plugin use
    
    Args:
        step_config: Step configuration containing auth
        task_with: Rendered 'with' parameters (may override auth)
        jinja_env: Jinja2 environment for template rendering
        context: Context for rendering templates
        
    Returns:
        Dictionary mapping alias -> resolved credential dict
    """
    # Handle backward compatibility - convert old formats to new unified format
    auth_config = _convert_legacy_auth(step_config, task_with)
    
    # Merge auth from step and task_with (task_with overrides)
    step_auth = auth_config.get('auth', {})
    with_auth = task_with.get('auth', {})
    
    # Handle legacy single string auth (deprecated but supported)
    if isinstance(step_auth, str):
        logger.warning(f"AUTH: Simple string auth format is deprecated. Use dictionary format instead: auth: {{alias: {{type: 'postgres', key: '{step_auth}'}}}}")
        step_auth = {'default': {'type': 'postgres', 'key': step_auth}}
    if isinstance(with_auth, str):
        logger.warning(f"AUTH: Simple string auth format is deprecated. Use dictionary format instead: auth: {{alias: {{type: 'postgres', key: '{with_auth}'}}}}")
        with_auth = {'default': {'type': 'postgres', 'key': with_auth}}
    
    # Merge auth configs
    merged_auth = copy.deepcopy(step_auth)
    for alias, spec in (with_auth or {}).items():
        if alias in merged_auth:
            # Merge spec into existing alias
            merged_auth[alias].update(spec)
        else:
            merged_auth[alias] = spec
    
    if not merged_auth:
        return {}
    
    # Deep render templates in auth config
    rendered_auth = _deep_render_template(jinja_env, context, merged_auth)
    
    resolved_auth = {}
    
    for alias, spec in rendered_auth.items():
        if not isinstance(spec, dict):
            logger.warning(f"AUTH: Invalid auth spec for alias '{alias}': expected dict, got {type(spec)}")
            continue
            
        auth_type = spec.get('type')
        if not auth_type:
            logger.warning(f"AUTH: Missing 'type' for auth alias '{alias}'")
            continue
            
        if auth_type not in AUTH_TYPES:
            logger.warning(f"AUTH: Unknown auth type '{auth_type}' for alias '{alias}'")
            continue
        
        # Start with the spec as base
        resolved_spec = copy.deepcopy(spec)
        
        # Fetch from provider if key is specified
        provider = spec.get('provider', 'credential_store')
        key = spec.get('key')
        
        if key and provider == 'credential_store':
            try:
                record = fetch_credential_by_key(str(key))
                if record and isinstance(record, dict):
                    # Extract the actual credential data
                    record_data = record
                    if 'data' in record and isinstance(record['data'], dict):
                        record_data = record['data']
                    
                    # Normalize fields based on type
                    if auth_type == 'postgres':
                        normalized = _normalize_postgres_fields(record_data)
                        # Merge normalized fields, but spec overrides
                        for field_key, field_value in normalized.items():
                            if field_key not in resolved_spec:
                                resolved_spec[field_key] = field_value
                    elif auth_type == 'hmac':
                        service = spec.get('service', 'gcs')
                        normalized = _normalize_hmac_fields(record_data, service)
                        for field_key, field_value in normalized.items():
                            if field_key not in resolved_spec:
                                resolved_spec[field_key] = field_value
                    else:
                        # For other types, merge record data directly
                        for field_key, field_value in record_data.items():
                            if field_key not in resolved_spec:
                                resolved_spec[field_key] = field_value
                                
                    logger.debug(f"AUTH: Resolved credential '{key}' for alias '{alias}'")
                else:
                    logger.warning(f"AUTH: Failed to fetch credential '{key}' for alias '{alias}'")
            except Exception as e:
                logger.warning(f"AUTH: Error fetching credential '{key}' for alias '{alias}': {e}")
                
        elif key and provider == 'secret_manager':
            # Fetch scalar value from secret manager
            secret_value = _fetch_secret_manager_value(key, auth_type)
            if secret_value:
                # Map to appropriate field based on type
                if auth_type == 'bearer':
                    resolved_spec['token'] = secret_value
                elif auth_type == 'basic':
                    # For basic auth, we expect username:password or just password
                    if ':' in secret_value:
                        username, password = secret_value.split(':', 1)
                        resolved_spec['username'] = username
                        resolved_spec['password'] = password
                    else:
                        resolved_spec['password'] = secret_value
                elif auth_type == 'api_key':
                    resolved_spec['value'] = secret_value
                elif auth_type == 'header':
                    resolved_spec['value'] = secret_value
                    
                logger.debug(f"AUTH: Retrieved secret for alias '{alias}' from secret manager")
            else:
                logger.warning(f"AUTH: Failed to retrieve secret '{key}' for alias '{alias}'")
        
        # Set default secret_name for DuckDB
        if 'secret_name' not in resolved_spec:
            resolved_spec['secret_name'] = alias
            
        resolved_auth[alias] = resolved_spec
        
        # Log resolved spec (redacted)
        logger.debug(f"AUTH: Resolved alias '{alias}': {_redact_dict(resolved_spec)}")
    
    return resolved_auth


def _convert_legacy_auth(step_config: Dict, task_with: Dict) -> Dict:
    """
    Convert legacy auth/credentials/secret formats to unified auth format.
    
    Args:
        step_config: Step configuration
        task_with: Task with parameters
        
    Returns:
        Converted configuration with unified auth format
    """
    converted = copy.deepcopy(step_config)
    
    # Handle legacy 'credentials' map
    if 'credentials' in step_config:
        credentials = step_config['credentials']
        if isinstance(credentials, dict):
            auth_map = {}
            for alias, cred_spec in credentials.items():
                if isinstance(cred_spec, dict) and 'key' in cred_spec:
                    # Convert old format to new format
                    new_spec = {
                        'type': cred_spec.get('type', 'postgres'),  # Default to postgres
                        'key': cred_spec['key']
                    }
                    # Copy other fields
                    for key, value in cred_spec.items():
                        if key not in ['key', 'type']:
                            new_spec[key] = value
                    auth_map[alias] = new_spec
                elif isinstance(cred_spec, str):
                    # Simple string key reference
                    auth_map[alias] = {
                        'type': 'postgres',  # Assume postgres for legacy
                        'key': cred_spec
                    }
            
            if auth_map:
                converted['auth'] = auth_map
                logger.debug("AUTH: Converted legacy 'credentials' to unified 'auth'")
    
    return converted


def get_postgres_auth(resolved_auth: Dict[str, Dict], use_auth: Optional[str] = None) -> Optional[Dict]:
    """
    Get postgres authentication from resolved auth map.
    
    Args:
        resolved_auth: Resolved auth map from resolve_auth_map
        use_auth: Specific alias to use, or None to auto-detect
        
    Returns:
        Postgres auth dict or None if not found
    """
    postgres_auths = {alias: spec for alias, spec in resolved_auth.items() 
                     if spec.get('type') == 'postgres'}
    
    if not postgres_auths:
        return None
        
    if use_auth:
        return postgres_auths.get(use_auth)
    elif len(postgres_auths) == 1:
        return list(postgres_auths.values())[0]
    else:
        # Multiple postgres auths found, need explicit selection
        logger.warning(f"AUTH: Multiple postgres auths found: {list(postgres_auths.keys())}. Use 'use_auth' to specify.")
        return None


def build_http_headers(resolved_auth: Dict[str, Dict], use_auth: Optional[str] = None) -> Dict[str, str]:
    """
    Build HTTP headers from resolved auth map.
    
    Args:
        resolved_auth: Resolved auth map from resolve_auth_map  
        use_auth: Specific alias to use, or None to use all applicable auths
        
    Returns:
        Dictionary of HTTP headers
    """
    headers = {}
    
    auth_aliases = [use_auth] if use_auth else resolved_auth.keys()
    
    for alias in auth_aliases:
        if alias not in resolved_auth:
            continue
            
        spec = resolved_auth[alias]
        auth_type = spec.get('type')
        
        if auth_type == 'bearer':
            token = spec.get('token')
            if token:
                headers['Authorization'] = f'Bearer {token}'
        elif auth_type == 'basic':
            username = spec.get('username', '')
            password = spec.get('password', '')
            if username or password:
                credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
                headers['Authorization'] = f'Basic {credentials}'
        elif auth_type == 'api_key':
            header_name = spec.get('header', 'X-API-Key')
            value = spec.get('value')
            if value:
                headers[header_name] = value
        elif auth_type == 'header':
            name = spec.get('name')
            value = spec.get('value')
            if name and value:
                headers[name] = value
    
    return headers


def get_duckdb_secrets(resolved_auth: Dict[str, Dict]) -> List[str]:
    """
    Generate DuckDB CREATE SECRET statements from resolved auth map.
    
    Args:
        resolved_auth: Resolved auth map from resolve_auth_map
        
    Returns:
        List of SQL statements to create DuckDB secrets
    """
    statements = []
    
    for alias, spec in resolved_auth.items():
        auth_type = spec.get('type')
        secret_name = spec.get('secret_name', alias)
        
        if auth_type == 'postgres':
            parts = []
            if spec.get('db_host'):
                parts.append(f"HOST '{spec['db_host']}'")
            if spec.get('db_port'):
                parts.append(f"PORT {spec['db_port']}")  
            if spec.get('db_name'):
                parts.append(f"DATABASE '{spec['db_name']}'")
            if spec.get('db_user'):
                parts.append(f"USER '{spec['db_user']}'")
            if spec.get('db_password'):
                parts.append(f"PASSWORD '{spec['db_password']}'")
            if spec.get('sslmode'):
                parts.append(f"SSLMODE '{spec['sslmode']}'")
                
            if parts:
                statement = f"CREATE OR REPLACE SECRET {secret_name} (\n  TYPE postgres,\n  {',\n  '.join(parts)}\n);"
                statements.append(statement)
                
        elif auth_type == 'hmac':
            service = spec.get('service', 'gcs')
            if service == 'gcs':
                parts = []
                if spec.get('key_id'):
                    parts.append(f"KEY_ID '{spec['key_id']}'")
                if spec.get('secret_key'):
                    parts.append(f"SECRET '{spec['secret_key']}'")
                if spec.get('scope'):
                    parts.append(f"SCOPE '{spec['scope']}'")
                    
                if parts:
                    statement = f"CREATE OR REPLACE SECRET {secret_name} (\n  TYPE gcs,\n  {',\n  '.join(parts)}\n);"
                    statements.append(statement)
            elif service == 's3':
                parts = []
                if spec.get('key_id'):
                    parts.append(f"KEY_ID '{spec['key_id']}'")
                if spec.get('secret_key'):
                    parts.append(f"SECRET '{spec['secret_key']}'")
                if spec.get('region'):
                    parts.append(f"REGION '{spec['region']}'")
                if spec.get('endpoint'):
                    parts.append(f"ENDPOINT '{spec['endpoint']}'")
                if spec.get('scope'):
                    parts.append(f"SCOPE '{spec['scope']}'")
                    
                if parts:
                    statement = f"CREATE OR REPLACE SECRET {secret_name} (\n  TYPE s3,\n  {',\n  '.join(parts)}\n);"
                    statements.append(statement)
    
    return statements


def get_required_extensions(resolved_auth: Dict[str, Any]) -> List[str]:
    """
    Get list of DuckDB extensions required for the given auth map.
    
    Args:
        resolved_auth: Resolved auth map - can contain dicts or ResolvedAuthItem objects
        
    Returns:
        List of extension names to install/load
    """
    # Map auth types to required extensions
    EXTS_BY_TYPE = {
        "postgres": {"postgres"},
        "pg": {"postgres"},
        "mysql": {"mysql"},
        "hmac": {"httpfs"},          # for GCS/S3-style signed access
        "gcs": {"httpfs"},
        "s3": {"httpfs"},
        "azure": {"azure", "httpfs"},
    }
    
    extensions = set()
    
    if not resolved_auth:
        return list(extensions)

    for alias, item in resolved_auth.items():
        # Normalize item to dict regardless of input type
        normalized = as_mapping(item)
        
        # Try multiple fields to determine the auth type
        auth_type = (
            normalized.get("type") or 
            normalized.get("kind") or 
            normalized.get("engine") or 
            normalized.get("provider") or 
            normalized.get("service") or
            normalized.get("source")
        )
        
        if not auth_type:
            # Log debug message with class name for diagnostics
            item_type = type(item).__name__ if item is not None else "None"
            logger.debug(
                "Auth alias '%s' missing type/kind/provider; item=%r (%s)", 
                alias, item, item_type
            )
            continue
            
        auth_type_str = str(auth_type).lower()
        required_exts = EXTS_BY_TYPE.get(auth_type_str)
        
        if not required_exts:
            logger.debug(
                "No extension mapping for auth alias '%s' (type=%s); normalized=%r", 
                alias, auth_type_str, normalized
            )
            continue
            
        extensions.update(required_exts)
        logger.debug(
            "Auth alias '%s' type '%s' requires extensions: %s", 
            alias, auth_type_str, sorted(required_exts)
        )
    
    result = sorted(extensions)
    logger.debug("Total required extensions: %s", result)
    return result
