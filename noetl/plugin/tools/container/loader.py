"""
Script and file loading utilities for container tasks.

Supports loading scripts and files from multiple sources:
- file: Local filesystem (with catalog path resolution)
- gcs: Google Cloud Storage
- s3: AWS S3
- http: HTTP/HTTPS endpoints
"""

import os
import base64
from pathlib import Path
from typing import Dict, Any
from jinja2 import Environment
from noetl.core.logger import setup_logger
from noetl.plugin.shared.script.resolver import resolve_script

logger = setup_logger(__name__, include_location=True)


def load_script(script_config: Dict[str, Any], context: Dict, jinja_env: Environment) -> str:
    """
    Load script content from configured source using shared resolver.

    Args:
        script_config: Script configuration with 'uri' and 'source'
        context: Execution context for template rendering
        jinja_env: Jinja2 environment

    Returns:
        Script content as string

    Raises:
        ValueError: If script configuration is invalid
        FileNotFoundError: If file source not found
    """
    if not script_config or 'uri' not in script_config:
        raise ValueError("Script configuration requires 'uri' field")

    # Use shared script resolver
    try:
        content = resolve_script(script_config, context, jinja_env)
        logger.info(f"Loaded script: {len(content)} bytes from {script_config.get('source', {}).get('type', 'unknown')}")
        return content
    except Exception as e:
        logger.error(f"Failed to load script from {script_config.get('uri')}: {e}")
        raise


def load_files(files_config: list, context: Dict, jinja_env: Environment) -> Dict[str, str]:
    """
    Load multiple files from configured sources.

    Args:
        files_config: List of file configurations with 'uri', 'source', and 'mountPath'
        context: Execution context
        jinja_env: Jinja2 environment

    Returns:
        Dictionary mapping mountPath to file content
    """
    files = {}
    
    for file_config in files_config:
        uri = file_config.get('uri')
        if not uri:
            logger.warning("Skipping file with missing 'uri'")
            continue

        mount_path = file_config.get('mountPath')
        if not mount_path:
            # Use basename of URI as mount path
            mount_path = os.path.basename(uri)

        # Render mount path with Jinja2
        mount_path = jinja_env.from_string(mount_path).render(context)

        logger.debug(f"Loading file: {uri} -> {mount_path}")

        try:
            # Use shared script resolver for each file
            content = resolve_script(file_config, context, jinja_env)
            files[mount_path] = content
            logger.info(f"Loaded file: {mount_path} ({len(content)} bytes)")
        except Exception as e:
            logger.error(f"Failed to load file {uri}: {e}")
            raise

    return files

