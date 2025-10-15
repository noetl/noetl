"""
HTTP authentication handling for HTTP plugin.

Processes authentication configurations and builds appropriate HTTP headers.
"""

import base64
from typing import Dict, Any

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def build_auth_headers(resolved_items: Dict[str, Any], mode: str) -> Dict[str, str]:
    """
    Build authentication headers from resolved auth items.
    
    Args:
        resolved_items: Dictionary of resolved authentication items
        mode: Auth mode ('single' or 'multiple')
        
    Returns:
        Dictionary of authentication headers
    """
    auth_headers = {}
    
    # For HTTP plugin, we expect single auth mode or use the first resolved item
    resolved_auth = None
    if mode == 'single' or len(resolved_items) == 1:
        resolved_auth = list(resolved_items.values())[0]
    
    if not resolved_auth:
        logger.debug("HTTP: No resolved auth available")
        return auth_headers
    
    service = resolved_auth.service
    payload = resolved_auth.payload
    
    if service == 'bearer':
        # Bearer token authentication
        token = payload.get('token')
        if token:
            auth_headers['Authorization'] = f'Bearer {token}'
            logger.debug("HTTP: Added Bearer authorization header")
            
    elif service == 'basic':
        # Basic authentication
        username = payload.get('username') or payload.get('user')
        password = payload.get('password')
        if username and password:
            credentials = base64.b64encode(f'{username}:{password}'.encode()).decode()
            auth_headers['Authorization'] = f'Basic {credentials}'
            logger.debug("HTTP: Added Basic authorization header")
            
    elif service == 'api_key':
        # API key authentication
        key = payload.get('key')
        value = payload.get('value')
        if key and value:
            auth_headers[key] = value
            logger.debug(f"HTTP: Added API key header: {key}")
            
    elif service == 'header':
        # Direct header injection
        if isinstance(payload, dict):
            auth_headers.update(payload)
            logger.debug(f"HTTP: Added custom headers: {list(payload.keys())}")
    else:
        logger.debug(f"HTTP: Unsupported auth type for HTTP injection: {resolved_auth.auth_type}")
    
    return auth_headers
