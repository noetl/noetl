"""
Main script resolution logic.

Coordinates source-specific handlers to fetch script content from:
- Local filesystem
- Google Cloud Storage (GCS)
- AWS S3
- HTTP/HTTPS endpoints
"""

from typing import Dict, Any, Tuple, Optional
from jinja2 import Environment

from noetl.core.logger import setup_logger
from .validation import validate_script_config
from .sources import file, gcs, s3, http as http_source

logger = setup_logger(__name__, include_location=True)


def _parse_uri(uri: str, source_type: str) -> Tuple[str, str]:
    """
    Parse cloud URI to extract bucket and path.
    
    Required formats:
    - gs://bucket-name/path/to/script.py
    - s3://bucket-name/path/to/script.py
    
    Args:
        uri: Full cloud URI with scheme
        source_type: 'gcs' or 's3'
        
    Returns:
        Tuple of (bucket_name, path)
        
    Raises:
        ValueError: If URI format is invalid
    """
    prefix = "gs://" if source_type == 'gcs' else "s3://"
    
    if not uri.startswith(prefix):
        raise ValueError(
            f"Invalid {source_type.upper()} URI format. "
            f"Expected format: {prefix}bucket-name/path/to/script"
        )
    
    # Remove prefix: gs://bucket/path -> bucket/path
    without_prefix = uri[len(prefix):]
    
    # Split on first /: bucket/path -> (bucket, path)
    parts = without_prefix.split('/', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    elif len(parts) == 1 and parts[0]:
        # Just bucket, no path
        raise ValueError(
            f"URI must include path after bucket: {prefix}{parts[0]}/path/to/script"
        )
    else:
        raise ValueError(f"Invalid URI format: {uri}")


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
        ...     'uri': 'gs://my-scripts/transform.py',
        ...     'source': {
        ...         'type': 'gcs',
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
                path=script_config['uri'],
                encoding=script_config.get('encoding', 'utf-8')
            )
        
        elif source_type == 'gcs':
            # Parse gs://bucket/path URI
            uri = script_config['uri']
            bucket, path = _parse_uri(uri, 'gcs')
            logger.debug(f"Parsed GCS URI: bucket={bucket}, path={path}")
            
            content = gcs.fetch_from_gcs(
                path=path,
                bucket=bucket,
                credential=script_config['source'].get('auth'),
                context=context,
                jinja_env=jinja_env
            )
        
        elif source_type == 's3':
            # Parse s3://bucket/path URI
            uri = script_config['uri']
            bucket, path = _parse_uri(uri, 's3')
            logger.debug(f"Parsed S3 URI: bucket={bucket}, path={path}")
            
            content = s3.fetch_from_s3(
                path=path,
                bucket=bucket,
                region=script_config['source'].get('region'),
                credential=script_config['source'].get('auth'),
                context=context,
                jinja_env=jinja_env
            )
        
        elif source_type == 'http':
            content = http_source.fetch_from_http(
                endpoint=script_config['source'].get('endpoint'),
                path=script_config.get('uri'),
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
