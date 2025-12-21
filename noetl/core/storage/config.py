"""
Sink configuration extraction and parsing.

Handles extracting sink configuration from task_config with support for
both flat and nested structures.
"""

from typing import Dict, Any, Optional, Tuple

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def parse_tool_config(tool_value: Any) -> Tuple[str, Dict[str, Any]]:
    """
    Parse tool configuration from tool value.
    
    Supports both flat string format and nested dict format:
    - Flat: tool: "postgres"
    - Nested: tool: { type: "postgres", table: "mytable", ... }
    
    Args:
        tool_value: Tool specification (string or dict)
        
    Returns:
        Tuple of (kind, tool_config)
        
    Raises:
        ValueError: If tool_value format invalid
    """
    tool_config = {}
    
    if isinstance(tool_value, str):
        # Flat structure: tool: "postgres"
        kind = tool_value.strip().lower()
    elif isinstance(tool_value, dict):
        # Nested structure: tool: { type: "postgres", ... } or { kind: "postgres", ... }
        kind = (tool_value.get('type') or tool_value.get('kind') or 'event').strip().lower()
        tool_config = tool_value.copy()
        # Remove 'type' and 'kind' from config as they're already extracted
        tool_config.pop('type', None)
        tool_config.pop('kind', None)
    else:
        raise ValueError(
            "sink.tool must be a string (e.g., 'postgres') or dict with "
            "'type' field (e.g., {type: 'postgres', ...})"
        )
    
    return kind, tool_config


def get_config_value(
    key: str,
    tool_value: Any,
    payload: Dict[str, Any],
    default: Any = None
) -> Any:
    """
    Get configuration value, preferring nested tool over top-level.
    
    Args:
        key: Configuration key to retrieve
        tool_value: Tool specification (may be dict with config)
        payload: Top-level payload dict
        default: Default value if not found
        
    Returns:
        Configuration value
    """
    if isinstance(tool_value, dict) and key in tool_value:
        return tool_value.get(key, default)
    return payload.get(key, default)


def extract_sink_config(
    task_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Extract sink configuration from task_config.
    
    Handles both direct sink config and nested sink: { ... } format.
    
    Args:
        task_config: Task configuration dictionary
        
    Returns:
        Dictionary with extracted configuration:
        - kind: Tool kind (postgres, duckdb, python, http, event)
        - tool_config: Nested tool configuration
        - data_spec: Data specification
        - statement: SQL statement/commands/sql (unified extraction)
        - params: Parameters (legacy)
        - mode, key_cols, fmt, table, batch, chunk_size, concurrency
        - auth_config: Authentication configuration
        - credential_ref: Credential reference (if string auth)
        - spec: Additional specifications
        
    Note:
        'statement' field consolidates 'statement', 'commands', and 'sql' 
        from the configuration for broader compatibility across tools.
    """
    # Support nested sink: { sink: { tool, data, statement, params, ... } }
    payload = task_config.get('sink') or task_config
    
    # Get tool - support both flat string and nested structure
    tool_value = payload.get('tool') or 'event'
    
    # Parse tool configuration
    kind, tool_config = parse_tool_config(tool_value)
    
    # Get sink configuration attributes
    # Prefer nested tool.data/args over top-level data/args for nested structure
    # Support both 'data' and 'args' for flexibility
    # For HTTP sinks, 'payload' is an alias for 'data'
    if isinstance(tool_value, dict):
        data_spec = (tool_value.get('data') or 
                    tool_value.get('args') or
                    tool_value.get('payload'))
    else:
        data_spec = (payload.get('data') or 
                    payload.get('args') or
                    payload.get('payload'))
    
    # Statement can come from nested tool or top-level
    # Also support 'commands' and 'sql' aliases (for DuckDB compatibility)
    if isinstance(tool_value, dict):
        statement = (tool_value.get('statement') or 
                    tool_value.get('commands') or 
                    tool_value.get('sql'))
    else:
        statement = (payload.get('statement') or 
                    payload.get('commands') or 
                    payload.get('sql'))
    
    # Extract configuration parameters
    params = get_config_value('params', tool_value, payload, {})
    mode = get_config_value('mode', tool_value, payload)
    key_cols = (get_config_value('key', tool_value, payload) or 
                get_config_value('keys', tool_value, payload))
    fmt = get_config_value('format', tool_value, payload)
    table = get_config_value('table', tool_value, payload)
    batch = get_config_value('batch', tool_value, payload)
    chunk_size = (get_config_value('chunk_size', tool_value, payload) or 
                  get_config_value('chunksize', tool_value, payload))
    concurrency = get_config_value('concurrency', tool_value, payload)
    
    # Extract HTTP-specific fields
    endpoint = (get_config_value('endpoint', tool_value, payload) or
                get_config_value('url', tool_value, payload))
    method = get_config_value('method', tool_value, payload)
    headers = get_config_value('headers', tool_value, payload)
    payload_data = get_config_value('payload', tool_value, payload)
    
    # Get auth configuration
    auth_config = get_config_value('auth', tool_value, payload)
    credential_ref = None
    
    # Handle auth configuration
    if isinstance(auth_config, dict):
        # Unified auth dictionary
        logger.debug("SINK: Using unified auth dictionary")
    elif isinstance(auth_config, str):
        # String reference to credential
        credential_ref = auth_config
        logger.debug("SINK: Using auth string reference")
    
    # Get spec configuration
    spec = get_config_value('spec', tool_value, payload, {})
    
    # Populate tool_config with extracted fields (for flat tool: "string" format)
    # When tool is already a dict, tool_config already has these fields
    if not isinstance(tool_value, dict):
        tool_config.update({
            k: v for k, v in {
                'endpoint': endpoint,
                'url': endpoint,  # Alias
                'method': method,
                'headers': headers,
                'payload': payload_data,
                'statement': statement,
                'commands': statement,  # Alias
                'sql': statement,  # Alias
                'params': params,
                'mode': mode,
                'key': key_cols,
                'keys': key_cols,  # Alias
                'format': fmt,
                'table': table,
                'batch': batch,
                'chunk_size': chunk_size,
                'chunksize': chunk_size,  # Alias
                'concurrency': concurrency,
                'auth': auth_config,
                'spec': spec,
            }.items() if v is not None
        })
    
    return {
        'kind': kind,
        'tool_config': tool_config,
        'data_spec': data_spec,
        'statement': statement,
        'params': params,
        'mode': mode,
        'key_cols': key_cols,
        'fmt': fmt,
        'table': table,
        'batch': batch,
        'chunk_size': chunk_size,
        'concurrency': concurrency,
        'auth_config': auth_config,
        'credential_ref': credential_ref,
        'spec': spec,
        # HTTP-specific fields
        'endpoint': endpoint,
        'method': method,
        'headers': headers,
        'payload': payload_data,
    }
