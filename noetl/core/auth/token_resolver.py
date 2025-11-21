"""
Token resolution utilities for Jinja2 templates.

Provides functions to resolve tokens dynamically in playbook templates.
"""

from typing import Dict, Any, Optional
from noetl.core.logger import setup_logger
from noetl.worker.secrets import fetch_credential_by_key
from noetl.core.secret import decrypt_json
from .providers import get_token_provider

logger = setup_logger(__name__, include_location=True)


def resolve_token(credential_name: str, audience: Optional[str] = None) -> str:
    """
    Resolve a token from a credential by name.
    
    This function is designed to be used in Jinja2 templates:
    {{ token('my_credential') }}
    {{ token('my_credential', 'https://example.com') }}
    
    Args:
        credential_name: Name of the credential to fetch
        audience: Optional audience for ID tokens
        
    Returns:
        Valid token string
        
    Raises:
        Exception: If credential not found or token fetch fails
    """
    try:
        logger.debug(f"Resolving token for credential: {credential_name}")
        
        # Fetch credential from database (with decrypted data)
        credential = fetch_credential_by_key(credential_name)
        if not credential:
            raise ValueError(f"Credential not found: {credential_name}")
        
        credential_type = credential.get('type', 'generic')
        
        # Get credential data (already decrypted by fetch_credential_by_key)
        credential_data = credential.get('data')
        if not credential_data:
            raise ValueError(f"Credential {credential_name} has no data")
        
        # Get appropriate token provider
        provider = get_token_provider(credential_type, credential_data)
        
        # Fetch token
        token = provider.fetch_token(audience)
        
        logger.info(f"Token resolved successfully for credential: {credential_name}")
        return token
        
    except Exception as e:
        logger.error(f"Failed to resolve token for credential {credential_name}: {e}")
        raise


def create_token_jinja_function(credential_name: str):
    """
    Create a Jinja2-compatible token resolution function.
    
    Returns a function that can be added to Jinja2 environment globals.
    
    Example:
        jinja_env.globals['token'] = create_token_jinja_function
        
    Usage in template:
        {{ token('my_credential') }}
        {{ token('my_credential', 'https://example.com') }}
    
    Args:
        credential_name: Name of the credential
        
    Returns:
        Function that resolves tokens
    """
    def token_function(audience: Optional[str] = None) -> str:
        return resolve_token(credential_name, audience)
    
    return token_function


def register_token_functions(jinja_env, context: Dict[str, Any]):
    """
    Register token resolution functions in Jinja2 environment.
    
    Adds global 'token' function that can be used in templates.
    
    Args:
        jinja_env: Jinja2 environment to register functions in
        context: Execution context (unused, for compatibility)
    """
    jinja_env.globals['token'] = resolve_token
    logger.debug("Registered 'token' function in Jinja2 environment")
