"""
Core authentication resolution logic.
"""

import copy
from typing import Dict, Any
from jinja2 import Environment

from noetl.core.logger import setup_logger
from noetl.worker.secrets import fetch_credential_by_key
from .constants import AUTH_TYPES
from .utils import deep_render_template, redact_dict, fetch_secret_manager_value
from .normalize import normalize_postgres_fields, normalize_hmac_fields

logger = setup_logger(__name__, include_location=True)


def convert_legacy_auth(step_config: Dict, task_with: Dict) -> Dict:
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
    auth_config = convert_legacy_auth(step_config, task_with)
    
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
    rendered_auth = deep_render_template(jinja_env, context, merged_auth)
    
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
                        normalized = normalize_postgres_fields(record_data)
                        # Merge normalized fields, but spec overrides
                        for field_key, field_value in normalized.items():
                            if field_key not in resolved_spec:
                                resolved_spec[field_key] = field_value
                    elif auth_type == 'hmac':
                        service = spec.get('service', 'gcs')
                        normalized = normalize_hmac_fields(record_data, service)
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
            secret_value = fetch_secret_manager_value(key, auth_type)
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
        logger.debug(f"AUTH: Resolved alias '{alias}': {redact_dict(resolved_spec)}")
    
    return resolved_auth
