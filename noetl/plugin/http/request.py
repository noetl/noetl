"""
HTTP request preparation for HTTP plugin.

Handles request configuration, parameter routing, and header management.
"""

from typing import Dict, Any, Optional

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def build_request_args(
    endpoint: str,
    method: str,
    headers: Dict[str, str],
    data_map: Dict[str, Any],
    params_legacy: Dict[str, Any],
    payload_legacy: Any
) -> Dict[str, Any]:
    """
    Build HTTP request arguments from task configuration.
    
    Args:
        endpoint: Target URL
        method: HTTP method (GET, POST, PUT, DELETE, PATCH)
        headers: HTTP headers
        data_map: Unified data map from task configuration
        params_legacy: Legacy params (backward compatibility)
        payload_legacy: Legacy payload (backward compatibility)
        
    Returns:
        Dictionary of request arguments for httpx
    """
    request_args = {
        'url': endpoint,
        'headers': headers,
    }
    
    # Route data to query/body automatically with overrides
    params = None
    json_body = None
    
    try:
        # Explicit overrides
        if 'query' in data_map:
            params = data_map.get('query') if isinstance(data_map.get('query'), dict) else None
        if 'body' in data_map:
            json_body = data_map.get('body')
    except Exception:
        pass
    
    if method in ['GET', 'DELETE']:
        # GET/DELETE methods use query parameters
        if params is None:  # default: use whole data_map as query when no explicit query/body
            if 'query' not in data_map and 'body' not in data_map:
                params = {k: v for k, v in data_map.items()}
        if params is None and isinstance(params_legacy, dict) and params_legacy:
            params = params_legacy
        if params:
            request_args['params'] = params
    else:
        # POST/PUT/PATCH methods use request body
        if json_body is None:
            if 'query' not in data_map and 'body' not in data_map:
                json_body = data_map
            elif isinstance(payload_legacy, (dict, list)) and not json_body:
                json_body = payload_legacy
        
        if json_body is not None:
            # Honor content-type if user set form/multipart; otherwise default to JSON
            content_type = headers.get('Content-Type', '').lower()
            if 'application/x-www-form-urlencoded' in content_type:
                request_args['data'] = json_body
            elif 'multipart/form-data' in content_type:
                request_args['files'] = json_body
            else:
                request_args['json'] = json_body
    
    return request_args


def redact_sensitive_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Create a redacted copy of headers for safe logging.
    
    Args:
        headers: Original headers dictionary
        
    Returns:
        Headers with sensitive values redacted
    """
    redacted = {}
    for k, v in (headers or {}).items():
        if any(sensitive in k.lower() for sensitive in ['authorization', 'token', 'key', 'secret', 'password']):
            redacted[k] = '[REDACTED]'
        else:
            redacted[k] = v
    return redacted
