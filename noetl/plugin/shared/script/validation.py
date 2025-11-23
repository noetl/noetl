"""
Script configuration validation.
"""

from typing import Dict, Any


def validate_script_config(script_config: Dict[str, Any]) -> None:
    """
    Validate script configuration structure.
    
    Args:
        script_config: Script configuration dictionary
        
    Raises:
        ValueError: If configuration is invalid
    """
    if not isinstance(script_config, dict):
        raise ValueError("script must be a dictionary")
    
    # Validate required fields
    if 'source' not in script_config:
        raise ValueError("script.source is required")
    
    source = script_config['source']
    if not isinstance(source, dict):
        raise ValueError("script.source must be a dictionary")
    
    if 'type' not in source:
        raise ValueError("script.source.type is required")
    
    source_type = source['type']
    valid_types = ['gcs', 's3', 'file', 'http']
    if source_type not in valid_types:
        raise ValueError(f"script.source.type must be one of: {', '.join(valid_types)}")
    
    # Validate source-specific requirements
    if source_type in ['gcs', 's3']:
        if 'bucket' not in source:
            raise ValueError(f"script.source.bucket is required for {source_type} source")
        if 'path' not in script_config:
            raise ValueError(f"script.path is required for {source_type} source")
    
    elif source_type == 'file':
        if 'path' not in script_config:
            raise ValueError("script.path is required for file source")
    
    elif source_type == 'http':
        if 'endpoint' not in source and 'path' not in script_config:
            raise ValueError("script.source.endpoint or script.path is required for http source")
    
    # Validate S3-specific fields
    if source_type == 's3' and 'region' not in source:
        # Region is optional but recommended
        pass
    
    # Validate HTTP-specific fields
    if source_type == 'http':
        method = source.get('method', 'GET')
        if method not in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
            raise ValueError(f"script.source.method must be valid HTTP method, got: {method}")
