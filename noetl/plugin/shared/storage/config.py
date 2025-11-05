"""
Save configuration extraction and parsing.

Handles extracting save configuration from task_config with support for
both flat and nested structures.
"""

from typing import Dict, Any, Optional, Tuple

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def parse_storage_config(storage_value: Any) -> Tuple[str, Dict[str, Any]]:
    """
    Parse storage configuration from storage value.
    
    Supports both flat string format and nested dict format:
    - Flat: storage: "postgres"
    - Nested: storage: { type: "postgres", table: "mytable", ... }
    
    Args:
        storage_value: Storage specification (string or dict)
        
    Returns:
        Tuple of (kind, storage_config)
        
    Raises:
        ValueError: If storage_value format invalid
    """
    storage_config = {}
    
    if isinstance(storage_value, str):
        # Flat structure: storage: "postgres"
        kind = storage_value.strip().lower()
    elif isinstance(storage_value, dict):
        # Nested structure: storage: { type: "postgres", ... }
        kind = storage_value.get('type', 'event').strip().lower()
        storage_config = storage_value.copy()
        # Remove 'type' from config as it's already extracted
        storage_config.pop('type', None)
    else:
        raise ValueError(
            "save.storage must be a string (e.g., 'postgres') or dict with "
            "'type' field (e.g., {type: 'postgres', ...})"
        )
    
    return kind, storage_config


def get_config_value(
    key: str,
    storage_value: Any,
    payload: Dict[str, Any],
    default: Any = None
) -> Any:
    """
    Get configuration value, preferring nested storage over top-level.
    
    Args:
        key: Configuration key to retrieve
        storage_value: Storage specification (may be dict with config)
        payload: Top-level payload dict
        default: Default value if not found
        
    Returns:
        Configuration value
    """
    if isinstance(storage_value, dict) and key in storage_value:
        return storage_value.get(key, default)
    return payload.get(key, default)


def extract_save_config(
    task_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Extract save configuration from task_config.
    
    Handles both direct save config and nested save: { ... } format.
    
    Args:
        task_config: Task configuration dictionary
        
    Returns:
        Dictionary with extracted configuration:
        - kind: Storage kind (postgres, duckdb, python, http, event)
        - storage_config: Nested storage configuration
        - data_spec: Data specification
        - statement: SQL statement (if provided)
        - params: Parameters (legacy)
        - mode, key_cols, fmt, table, batch, chunk_size, concurrency
        - auth_config: Authentication configuration
        - credential_ref: Credential reference (if string auth)
        - spec: Additional specifications
    """
    # Support nested save: { save: { storage, data, statement, params, ... } }
    payload = task_config.get('save') or task_config
    
    # Get storage - support both flat string and nested structure
    storage_value = payload.get('storage') or 'event'
    
    # Parse storage configuration
    kind, storage_config = parse_storage_config(storage_value)
    
    # Get save configuration attributes
    # Prefer nested storage.data/args over top-level data/args for nested structure
    # Support both 'data' and 'args' for flexibility
    if isinstance(storage_value, dict):
        data_spec = storage_value.get('data') or storage_value.get('args')
    else:
        data_spec = payload.get('data') or payload.get('args')
    
    # Statement can come from nested storage or top-level
    if isinstance(storage_value, dict) and 'statement' in storage_value:
        statement = storage_value.get('statement')
    else:
        statement = payload.get('statement')
    
    # Extract configuration parameters
    params = get_config_value('params', storage_value, payload, {})
    mode = get_config_value('mode', storage_value, payload)
    key_cols = (get_config_value('key', storage_value, payload) or 
                get_config_value('keys', storage_value, payload))
    fmt = get_config_value('format', storage_value, payload)
    table = get_config_value('table', storage_value, payload)
    batch = get_config_value('batch', storage_value, payload)
    chunk_size = (get_config_value('chunk_size', storage_value, payload) or 
                  get_config_value('chunksize', storage_value, payload))
    concurrency = get_config_value('concurrency', storage_value, payload)
    
    # Get auth configuration
    auth_config = get_config_value('auth', storage_value, payload)
    credential_ref = None
    
    # Handle auth configuration
    if isinstance(auth_config, dict):
        # Unified auth dictionary
        logger.debug("SAVE: Using unified auth dictionary")
    elif isinstance(auth_config, str):
        # String reference to credential
        credential_ref = auth_config
        logger.debug("SAVE: Using auth string reference")
    
    # Get spec configuration
    spec = get_config_value('spec', storage_value, payload, {})
    
    return {
        'kind': kind,
        'storage_config': storage_config,
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
    }
