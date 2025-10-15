"""
HTTP authentication functions.
"""

import base64
from typing import Dict, Optional

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


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
