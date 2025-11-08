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
    params: Dict[str, Any],
    payload: Any
) -> Dict[str, Any]:
    """
    Build HTTP request arguments from task configuration.
    
    Supports two configuration styles:
    1. Unified data model: step.data with optional data.query/data.body
    2. Direct params/payload: step.params and step.payload
    
    Priority/fallback chain:
    - GET/DELETE: data.query → data (auto) → params → nothing
    - POST/PUT/PATCH: data.body → data (auto) → payload → nothing
    
    Args:
        endpoint: Target URL
        method: HTTP method (GET, POST, PUT, DELETE, PATCH)
        headers: HTTP headers
        data_map: Unified data from step.data
        params: Direct params from step.params (query parameters)
        payload: Direct payload from step.payload (request body)
        
    Returns:
        Dictionary of request arguments for httpx
    """
    request_args = {
        'url': endpoint,
        'headers': headers,
    }
    
    # Route data to query/body automatically with overrides
    query_params = None
    json_body = None
    
    # Explicit overrides from data.query/data.body
    if not isinstance(data_map, dict):
        raise ValueError(f"data_map must be a dict, got {type(data_map).__name__}")
    
    if 'query' in data_map:
        query_params = data_map.get('query') if isinstance(data_map.get('query'), dict) else None
    if 'body' in data_map:
        json_body = data_map.get('body')
    
    if method in ['GET', 'DELETE']:
        # GET/DELETE methods use query parameters
        if query_params is None:  # Auto-route: use whole data_map as query when no explicit query/body
            if 'query' not in data_map and 'body' not in data_map:
                query_params = {k: v for k, v in data_map.items()}
        # Fallback to direct params configuration if data_map is empty
        if (not query_params) and isinstance(params, dict) and params:
            query_params = params
        if query_params:
            request_args['params'] = query_params
    else:
        # POST/PUT/PATCH methods use request body
        if json_body is None:
            if 'query' not in data_map and 'body' not in data_map:
                json_body = data_map
            elif isinstance(payload, (dict, list)) and not json_body:
                json_body = payload
        
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
