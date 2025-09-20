"""
NoETL Auth Schema Validation

This module provides schema validation for the unified auth attribute.
It defines the validation rules and provides helper functions for plugins.
"""
from typing import Dict, Any, List, Union, Optional
import logging

logger = logging.getLogger(__name__)

# Plugin auth requirements
PLUGIN_AUTH_ARITY = {
    'postgres': 'single',
    'http': 'single', 
    'save': 'single',
    'duckdb': 'multi'
}

# Reserved keys that indicate single auth object vs alias map
RESERVED_SINGLE_AUTH_KEYS = {
    'source', 'key', 'name', 'service', 'secret_name', 'scope', 
    'fields', 'inject', 'type'
}

# Valid auth sources
VALID_AUTH_SOURCES = {'credential', 'secret', 'env', 'inline'}

# Service type mappings for different auth sources
SERVICE_TYPE_MAPPINGS = {
    'postgres': ['postgresql', 'pg'],
    'gcs': ['google_cloud_storage', 'google_storage'],
    's3': ['amazon_s3', 'aws_s3'],
    'hmac': ['hmac_key', 'gcs_hmac', 's3_hmac']
}


class AuthValidationError(ValueError):
    """Raised when auth configuration is invalid."""
    pass


def _normalize_service_type(service: str) -> str:
    """
    Normalize service type to standard name.
    
    Args:
        service: Service type string
        
    Returns:
        Normalized service type
    """
    if not service:
        return service
    
    service_lower = service.lower()
    
    for standard, aliases in SERVICE_TYPE_MAPPINGS.items():
        if service_lower == standard or service_lower in aliases:
            return standard
    
    return service_lower


def validate_auth_single(auth_config: Union[str, Dict[str, Any]], context: str = "") -> List[str]:
    """
    Validate single auth configuration.
    
    Args:
        auth_config: Auth configuration (string credential key or dict)
        context: Context for error messages
        
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    prefix = f"{context}: " if context else ""
    
    if isinstance(auth_config, str):
        # String credential key - minimal validation
        if not auth_config.strip():
            errors.append(f"{prefix}credential key cannot be empty")
        return errors
    
    if not isinstance(auth_config, dict):
        errors.append(f"{prefix}auth must be string or dict, got {type(auth_config)}")
        return errors
    
    # Validate source
    source = auth_config.get('source', 'credential')
    if source not in VALID_AUTH_SOURCES:
        errors.append(f"{prefix}invalid source '{source}', must be one of {VALID_AUTH_SOURCES}")
    
    # Source-specific validation
    if source == 'credential':
        key = auth_config.get('key')
        if not key or not isinstance(key, str) or not key.strip():
            errors.append(f"{prefix}credential source requires non-empty 'key'")
    
    elif source == 'secret':
        name = auth_config.get('name')
        if not name or not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix}secret source requires non-empty 'name'")
    
    elif source == 'env':
        name = auth_config.get('name')
        if not name or not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix}env source requires non-empty 'name'")
    
    elif source == 'inline':
        fields = auth_config.get('fields')
        if not fields or not isinstance(fields, dict):
            errors.append(f"{prefix}inline source requires non-empty 'fields' dict")
    
    # Validate service type if provided
    service = auth_config.get('service') or auth_config.get('type')
    if service:
        if not isinstance(service, str) or not service.strip():
            errors.append(f"{prefix}service/type must be non-empty string")
        else:
            # Normalize and warn about unknown services (but don't error)
            normalized = _normalize_service_type(service)
            if normalized != service:
                logger.debug(f"Normalized service '{service}' → '{normalized}'")
    
    # Validate inject configuration if present
    inject = auth_config.get('inject')
    if inject is not None:
        if not isinstance(inject, dict):
            errors.append(f"{prefix}inject must be dict")
        else:
            kind = inject.get('kind')
            if kind and kind not in ['http_header']:
                errors.append(f"{prefix}inject.kind '{kind}' not supported (supported: http_header)")
            
            if kind == 'http_header':
                header = inject.get('header')
                if not header or not isinstance(header, str):
                    errors.append(f"{prefix}inject.kind=http_header requires 'header' string")
                
                scheme = inject.get('scheme', '')
                if scheme and not isinstance(scheme, str):
                    errors.append(f"{prefix}inject.scheme must be string")
    
    return errors


def validate_auth_multi(auth_config: Dict[str, Any], context: str = "") -> List[str]:
    """
    Validate multi-auth configuration (alias map).
    
    Args:
        auth_config: Dict mapping alias → auth spec
        context: Context for error messages
        
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    prefix = f"{context}: " if context else ""
    
    if not isinstance(auth_config, dict):
        errors.append(f"{prefix}multi-auth must be dict mapping alias → auth spec")
        return errors
    
    if not auth_config:
        errors.append(f"{prefix}multi-auth cannot be empty")
        return errors
    
    # Validate each alias
    for alias, auth_spec in auth_config.items():
        if not isinstance(alias, str) or not alias.strip():
            errors.append(f"{prefix}auth alias must be non-empty string")
            continue
        
        # Validate the auth spec for this alias
        alias_errors = validate_auth_single(auth_spec, f"{context}auth.{alias}" if context else f"auth.{alias}")
        errors.extend(alias_errors)
    
    return errors


def is_single_auth_config(auth_config: Any) -> bool:
    """
    Determine if auth config is single-auth vs multi-auth (alias map).
    
    Args:
        auth_config: Auth configuration to check
        
    Returns:
        True if single auth, False if multi-auth (alias map)
    """
    if isinstance(auth_config, str):
        return True
    
    if not isinstance(auth_config, dict):
        return True  # Invalid, but treat as single for error handling
    
    # If any reserved key is present, it's single auth
    return bool(RESERVED_SINGLE_AUTH_KEYS.intersection(auth_config.keys()))


def validate_auth_for_plugin(
    plugin_type: str, 
    auth_config: Any, 
    context: str = ""
) -> List[str]:
    """
    Validate auth configuration for a specific plugin type.
    
    Args:
        plugin_type: Plugin type (postgres, http, duckdb, etc.)
        auth_config: Auth configuration
        context: Context for error messages
        
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    prefix = f"{context}: " if context else ""
    
    if auth_config is None:
        errors.append(f"{prefix}auth is required for {plugin_type} steps")
        return errors
    
    # Get expected auth arity for plugin
    expected_arity = PLUGIN_AUTH_ARITY.get(plugin_type)
    if not expected_arity:
        logger.warning(f"Unknown plugin type '{plugin_type}' for auth validation")
        expected_arity = 'single'  # Default to single
    
    # Determine actual auth mode
    is_single = is_single_auth_config(auth_config)
    actual_arity = 'single' if is_single else 'multi'
    
    # Validate arity match
    if expected_arity == 'single' and actual_arity == 'multi':
        errors.append(f"{prefix}{plugin_type} steps require single auth (string or single auth object), got multi-auth (alias map)")
        return errors
    
    if expected_arity == 'multi' and actual_arity == 'single':
        # DuckDB allows single auth (auto-wraps to {auth: single})
        if plugin_type == 'duckdb':
            logger.debug(f"DuckDB step using single auth - will auto-wrap to multi-auth")
        else:
            errors.append(f"{prefix}{plugin_type} steps require multi-auth (alias map), got single auth")
            return errors
    
    # Validate the auth configuration
    if actual_arity == 'single':
        errors.extend(validate_auth_single(auth_config, context))
    else:
        errors.extend(validate_auth_multi(auth_config, context))
    
    return errors


def validate_step_auth(step: Dict[str, Any]) -> List[str]:
    """
    Validate auth configuration for a workflow step.
    
    Args:
        step: Step configuration dict
        
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    step_name = step.get('step') or step.get('name') or '<unnamed>'
    step_type = step.get('type', '').lower()
    
    if not step_type:
        return errors  # No type, can't validate auth
    
    # Check if plugin needs auth
    if step_type not in PLUGIN_AUTH_ARITY:
        return errors  # Unknown plugin, skip validation
    
    auth_config = step.get('auth')
    
    # Handle nested auth (e.g., in save.storage.auth)
    if auth_config is None and step_type == 'save':
        save_config = step.get('save', {})
        if isinstance(save_config, dict):
            storage_config = save_config.get('storage', {})
            if isinstance(storage_config, dict):
                auth_config = storage_config.get('auth')
    
    # Handle nested auth in task (for iterator steps)
    task = step.get('task')
    if isinstance(task, dict):
        task_type = task.get('type', '').lower()
        if task_type in PLUGIN_AUTH_ARITY:
            task_auth = task.get('auth')
            if task_auth is not None:
                task_context = f"step '{step_name}' task"
                errors.extend(validate_auth_for_plugin(task_type, task_auth, task_context))
            
            # Check nested save auth
            if task_type != 'save':
                task_save = task.get('save', {})
                if isinstance(task_save, dict):
                    task_storage = task_save.get('storage', {})
                    if isinstance(task_storage, dict):
                        task_save_auth = task_storage.get('auth')
                        if task_save_auth is not None:
                            save_context = f"step '{step_name}' task save"
                            errors.extend(validate_auth_for_plugin('save', task_save_auth, save_context))
    
    # Validate step-level auth
    if auth_config is not None:
        context = f"step '{step_name}'"
        errors.extend(validate_auth_for_plugin(step_type, auth_config, context))
    
    return errors


def validate_playbook_auth(playbook: Dict[str, Any]) -> List[str]:
    """
    Validate auth configuration for an entire playbook.
    
    Args:
        playbook: Playbook configuration dict
        
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    workflow = playbook.get('workflow', [])
    if not isinstance(workflow, list):
        return errors
    
    for step in workflow:
        if isinstance(step, dict):
            errors.extend(validate_step_auth(step))
    
    return errors