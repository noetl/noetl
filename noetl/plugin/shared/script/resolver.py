"""
Main script resolution logic.

Coordinates source-specific handlers to fetch script content from:
- Local filesystem
- Google Cloud Storage (GCS)
- AWS S3
- HTTP/HTTPS endpoints
"""

from typing import Dict, Any
from jinja2 import Environment

from noetl.core.logger import setup_logger
from .validation import validate_script_config
from .sources import file, gcs, s3, http as http_source

logger = setup_logger(__name__, include_location=True)


def resolve_script(
    script_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment
) -> str:
    """
    Resolve script content from configured source.
    
    Priority order:
    1. script attribute (external source)
    2. code_b64/command_b64 (base64 encoded inline)
    3. code/command (plain inline)
    
    Args:
        script_config: Script configuration with source details
        context: Execution context for Jinja2 rendering
        jinja_env: Jinja2 environment for template rendering
        
    Returns:
        Script content as string
        
    Raises:
        ValueError: Invalid configuration
        FileNotFoundError: Script file not found
        ConnectionError: Network/cloud storage error
        PermissionError: Authentication/authorization failed
        
    Example:
        >>> script_config = {
        ...     'path': 'scripts/transform.py',
        ...     'source': {
        ...         'type': 'gcs',
        ...         'bucket': 'my-scripts',
        ...         'auth': 'gcp_service_account'
        ...     }
        ... }
        >>> content = resolve_script(script_config, context, jinja_env)
    """
    # Validate configuration
    validate_script_config(script_config)
    
    source_type = script_config['source']['type']
    logger.info(f"Resolving script from {source_type} source")
    
    # Dispatch to source-specific handler
    try:
        if source_type == 'file':
            content = file.fetch_from_file(
                path=script_config['path'],
                encoding=script_config.get('encoding', 'utf-8')
            )
        
        elif source_type == 'gcs':
            content = gcs.fetch_from_gcs(
                path=script_config['path'],
                bucket=script_config['source']['bucket'],
                credential=script_config['source'].get('auth'),
                context=context,
                jinja_env=jinja_env
            )
        
        elif source_type == 's3':
            content = s3.fetch_from_s3(
                path=script_config['path'],
                bucket=script_config['source']['bucket'],
                region=script_config['source'].get('region'),
                credential=script_config['source'].get('auth'),
                context=context,
                jinja_env=jinja_env
            )
        
        elif source_type == 'http':
            content = http_source.fetch_from_http(
                endpoint=script_config['source'].get('endpoint'),
                path=script_config.get('path'),
                method=script_config['source'].get('method', 'GET'),
                headers=script_config['source'].get('headers', {}),
                timeout=script_config['source'].get('timeout', 30),
                context=context,
                jinja_env=jinja_env
            )
        
        else:
            raise ValueError(f"Unsupported source type: {source_type}")
        
        logger.info(f"Successfully resolved script ({len(content)} bytes) from {source_type}")
        return content
    
    except Exception as e:
        logger.error(f"Failed to resolve script from {source_type}: {e}")
        raise
