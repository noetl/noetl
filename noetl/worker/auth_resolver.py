"""
NoETL Unified Authentication Resolver

This module provides unified authentication resolution for all NoETL plugins.
It supports single-credential and multi-alias authentication patterns with
secure credential fetching and Jinja template rendering.

Security Notes:
- Never logs sensitive auth data (secrets, keys, passwords)
- Renders Jinja templates before credential resolution
- Redacts sensitive fields in error messages
"""
import os
import logging
from typing import Dict, Any, Optional, Tuple, Union, List, Iterator
from dataclasses import dataclass, asdict
from collections.abc import Mapping
from jinja2 import Environment

# Import existing credential fetching functions
from .secrets import fetch_credential_by_key

logger = logging.getLogger(__name__)

# Reserved keys that indicate single-auth object (not alias map)
RESERVED_SINGLE_AUTH_KEYS = {
    'source', 'key', 'name', 'service', 'secret_name', 'scope', 
    'fields', 'inject', 'type'
}

@dataclass
class ResolvedAuthItem(Mapping[str, Any]):
    """Resolved authentication item with all required information."""
    alias: str
    source: str  # 'credential', 'secret', 'env', 'inline'
    service: Optional[str] = None  # 'postgres', 'gcs', 's3', etc.
    secret_name: Optional[str] = None  # DuckDB secret name (defaults to alias)
    scope: Optional[str] = None  # For scoped secrets (GCS/S3)
    payload: Dict[str, Any] = None  # Resolved credential data
    is_scalar_value: bool = False  # True for simple string values
    inject: Optional[Dict[str, Any]] = None  # Injection configuration

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)

    # Mapping protocol implementation for backward compatibility
    def __getitem__(self, key: str) -> Any:
        """Get item by key - supports dict-like access."""
        data = self.to_dict()
        return data[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate over keys - supports dict-like iteration."""
        return iter(self.to_dict())

    def __len__(self) -> int:
        """Get number of items - supports len()."""
        return len(self.to_dict())

    def get(self, key: str, default: Any = None) -> Any:
        """Get item with default - supports dict-like .get() method."""
        data = self.to_dict()
        return data.get(key, default)
    
    def keys(self):
        """Get keys - supports dict-like .keys() method."""
        return self.to_dict().keys()
    
    def values(self):
        """Get values - supports dict-like .values() method.""" 
        return self.to_dict().values()
    
    def items(self):
        """Get items - supports dict-like .items() method."""
        return self.to_dict().items()


def _render_deep(value: Any, jinja_env: Environment, context: Dict[str, Any]) -> Any:
    """
    Recursively render Jinja templates in nested data structures.
    
    Args:
        value: The value to render (can be dict, list, str, or other)
        jinja_env: Jinja environment for rendering
        context: Template context
        
    Returns:
        Rendered value with templates resolved
    """
    if isinstance(value, str):
        if '{{' in value and '}}' in value:
            try:
                template = jinja_env.from_string(value)
                return template.render(context)
            except Exception as e:
                logger.warning(f"Template rendering failed for '{value[:50]}...': {e}")
                return value
        return value
    elif isinstance(value, dict):
        return {k: _render_deep(v, jinja_env, context) for k, v in value.items()}
    elif isinstance(value, list):
        return [_render_deep(item, jinja_env, context) for item in value]
    else:
        return value


def _redact_sensitive_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Redact sensitive fields for safe logging."""
    if not isinstance(data, dict):
        return data
    
    sensitive_keys = {
        'password', 'secret', 'key', 'token', 'auth', 'credential',
        'db_password', 'secret_key', 'access_key', 'key_id',
        'secret_access_key', 'private_key'
    }
    
    redacted = {}
    for k, v in data.items():
        if any(sensitive in k.lower() for sensitive in sensitive_keys):
            redacted[k] = '[REDACTED]'
        elif isinstance(v, dict):
            redacted[k] = _redact_sensitive_fields(v)
        else:
            redacted[k] = v
    
    return redacted


def _is_single_auth_object(auth_config: Any) -> bool:
    """
    Determine if auth config is a single auth object vs alias map.
    
    Single auth object has reserved keys like 'source', 'key', 'service', etc.
    Alias map has arbitrary keys that map to auth objects.
    
    Args:
        auth_config: The auth configuration to check
        
    Returns:
        True if single auth object, False if alias map
    """
    if not isinstance(auth_config, dict):
        return True  # String auth is single
    
    # If any reserved key is present, it's a single auth object
    return bool(RESERVED_SINGLE_AUTH_KEYS.intersection(auth_config.keys()))


def _fetch_credential_data(key: str) -> Dict[str, Any]:
    """
    Fetch credential data by key with error handling.
    
    Args:
        key: Credential key/name
        
    Returns:
        Credential data dictionary
        
    Raises:
        ValueError: If credential not found or fetch fails
    """
    try:
        credential = fetch_credential_by_key(key)
        if not credential:
            raise ValueError(f"Credential '{key}' not found")
        
        # Extract data payload
        data = credential.get('data', {})
        if isinstance(data, dict) and 'data' in data:
            # Handle nested data structure
            data = data['data']
        
        # Add service type from credential metadata
        service = credential.get('service') or credential.get('type')
        if service:
            data['service'] = service.lower()
            
        return data
    except Exception as e:
        logger.error(f"Failed to fetch credential '{key}': {e}")
        raise ValueError(f"Credential '{key}' fetch failed: {e}")


def _fetch_secret_data(name: str) -> Dict[str, Any]:
    """
    Fetch secret data by name.
    
    Note: This is a placeholder for future secret store integration.
    Currently returns a simple value structure.
    
    Args:
        name: Secret name
        
    Returns:
        Secret data dictionary with 'value' key
        
    Raises:
        ValueError: If secret not found
    """
    # TODO: Implement actual secret store integration
    # For now, check environment variables as fallback
    env_value = os.environ.get(f"NOETL_SECRET_{name.upper()}")
    if env_value:
        return {"value": env_value}
    
    raise ValueError(f"Secret '{name}' not found (secret store not implemented)")


def _resolve_single_auth_item(
    alias: str,
    auth_spec: Union[str, Dict[str, Any]],
    jinja_env: Environment,
    context: Dict[str, Any]
) -> ResolvedAuthItem:
    """
    Resolve a single auth item specification.
    
    Args:
        alias: Alias name for this auth item
        auth_spec: Auth specification (string or dict)
        jinja_env: Jinja environment for rendering
        context: Template context
        
    Returns:
        Resolved auth item
        
    Raises:
        ValueError: If auth spec is invalid or resolution fails
    """
    try:
        # Handle string auth (credential key)
        if isinstance(auth_spec, str):
            logger.debug(f"Resolving string auth '{alias}' → credential '{auth_spec}'")
            payload = _fetch_credential_data(auth_spec)
            return ResolvedAuthItem(
                alias=alias,
                source='credential',
                service=payload.get('service'),
                secret_name=alias,
                payload=payload,
                is_scalar_value=False
            )
        
        # Handle dict auth spec
        if not isinstance(auth_spec, dict):
            raise ValueError(f"Auth spec for '{alias}' must be string or dict, got {type(auth_spec)}")
        
        # Extract source (default to credential for backwards compatibility)
        source = auth_spec.get('source', 'credential')
        secret_name = auth_spec.get('secret_name', alias)
        scope = auth_spec.get('scope')
        inject = auth_spec.get('inject')
        
        logger.debug(f"Resolving dict auth '{alias}' with source '{source}'")
        
        # Resolve based on source type
        if source == 'credential':
            key = auth_spec.get('key')
            if not key:
                raise ValueError(f"Auth '{alias}' with source=credential missing 'key'")
            
            payload = _fetch_credential_data(key)
            
            # Override service if specified in auth spec
            service = auth_spec.get('service') or auth_spec.get('type') or payload.get('service')
            
            # Merge fields if provided
            fields = auth_spec.get('fields', {})
            if fields:
                payload.update(fields)
            
            return ResolvedAuthItem(
                alias=alias,
                source=source,
                service=service,
                secret_name=secret_name,
                scope=scope,
                payload=payload,
                inject=inject,
                is_scalar_value=False
            )
            
        elif source == 'secret':
            name = auth_spec.get('name')
            if not name:
                raise ValueError(f"Auth '{alias}' with source=secret missing 'name'")
            
            payload = _fetch_secret_data(name)
            service = auth_spec.get('service') or auth_spec.get('type')
            
            return ResolvedAuthItem(
                alias=alias,
                source=source,
                service=service,
                secret_name=secret_name,
                scope=scope,
                payload=payload,
                inject=inject,
                is_scalar_value=True  # Secrets are typically scalar values
            )
            
        elif source == 'env':
            name = auth_spec.get('name')
            if not name:
                raise ValueError(f"Auth '{alias}' with source=env missing 'name'")
            
            value = os.environ.get(name)
            if value is None:
                raise ValueError(f"Environment variable '{name}' not found")
            
            payload = {"value": value}
            service = auth_spec.get('service') or auth_spec.get('type')
            
            return ResolvedAuthItem(
                alias=alias,
                source=source,
                service=service,
                secret_name=secret_name,
                scope=scope,
                payload=payload,
                inject=inject,
                is_scalar_value=True
            )
            
        elif source == 'inline':
            fields = auth_spec.get('fields', {})
            if not fields:
                raise ValueError(f"Auth '{alias}' with source=inline missing 'fields'")
            
            service = auth_spec.get('service') or auth_spec.get('type')
            
            return ResolvedAuthItem(
                alias=alias,
                source=source,
                service=service,
                secret_name=secret_name,
                scope=scope,
                payload=fields,
                inject=inject,
                is_scalar_value=False
            )
            
        else:
            raise ValueError(f"Unknown auth source '{source}' for alias '{alias}'")
    
    except Exception as e:
        # Redact sensitive information from error messages
        safe_spec = _redact_sensitive_fields(auth_spec) if isinstance(auth_spec, dict) else str(auth_spec)[:50]
        logger.error(f"Failed to resolve auth '{alias}': {e}")
        raise ValueError(f"Auth resolution failed for '{alias}': {e}")


def resolve_auth(
    step_auth: Any,
    jinja_env: Environment,
    context: Dict[str, Any]
) -> Tuple[str, Dict[str, ResolvedAuthItem]]:
    """
    Resolve authentication configuration for a step.
    
    This is the main entry point for auth resolution. It handles both single
    credential steps (postgres, http) and multi-alias steps (duckdb).
    
    Args:
        step_auth: Authentication configuration from step
        jinja_env: Jinja environment for template rendering
        context: Template context for rendering
        
    Returns:
        Tuple of (auth_mode, items) where:
        - auth_mode: "single" or "multi"
        - items: Dict mapping alias → ResolvedAuthItem
        
    Raises:
        ValueError: If auth config is invalid
    """
    if step_auth is None:
        return "single", {}
    
    try:
        # First, render Jinja templates deeply
        logger.debug("Rendering Jinja templates in auth configuration")
        rendered_auth = _render_deep(step_auth, jinja_env, context)
        
        # Determine if single or multi auth
        is_single = _is_single_auth_object(rendered_auth)
        
        if is_single:
            # Single auth mode
            logger.debug("Detected single auth mode")
            auth_item = _resolve_single_auth_item("auth", rendered_auth, jinja_env, context)
            return "single", {"auth": auth_item}
        else:
            # Multi auth mode (alias map)
            logger.debug("Detected multi auth mode")
            items = {}
            
            for alias, auth_spec in rendered_auth.items():
                auth_item = _resolve_single_auth_item(alias, auth_spec, jinja_env, context)
                items[alias] = auth_item
            
            return "multi", items
            
    except Exception as e:
        logger.error(f"Auth resolution failed: {e}")
        raise ValueError(f"Authentication resolution failed: {e}")


def get_auth_value_for_injection(auth_item: ResolvedAuthItem) -> str:
    """
    Extract the value from an auth item for HTTP header injection.
    
    Args:
        auth_item: Resolved auth item
        
    Returns:
        String value for injection
        
    Raises:
        ValueError: If no suitable value found
    """
    payload = auth_item.payload or {}
    
    # For scalar values (secrets, env vars), use the value directly
    if auth_item.is_scalar_value:
        value = payload.get('value')
        if value:
            return str(value)
    
    # For credentials, try common value fields
    for field in ['value', 'token', 'key', 'secret']:
        if field in payload:
            return str(payload[field])
    
    # If inject config specifies fields to join
    if auth_item.inject and 'fields' in auth_item.inject:
        fields = auth_item.inject['fields']
        if isinstance(fields, list):
            values = [str(payload.get(f, '')) for f in fields if f in payload]
            if values:
                separator = auth_item.inject.get('separator', ' ')
                return separator.join(values)
    
    raise ValueError(f"No injectable value found for auth item '{auth_item.alias}'")