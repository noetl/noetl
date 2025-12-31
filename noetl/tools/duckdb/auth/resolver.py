"""
Credential resolution for DuckDB authentication.
"""

import os
from typing import Dict, Any, Optional, List

import httpx

from noetl.core.logger import setup_logger
from noetl.worker.auth_resolver import resolve_auth

from noetl.tools.duckdb.types import JinjaEnvironment, ContextDict, CredentialData, AuthType
from noetl.tools.duckdb.errors import AuthenticationError

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
