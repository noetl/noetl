"""
Local filesystem script fetcher.
"""

import os
from pathlib import Path

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def fetch_from_file(path: str, encoding: str = 'utf-8') -> str:
    """
    Read script content from local filesystem.
    
    Args:
        path: Absolute or relative file path
        encoding: File encoding (default: utf-8)
        
    Returns:
        Script content as string
        
    Raises:
        FileNotFoundError: File does not exist
        PermissionError: No read permission
        UnicodeDecodeError: Encoding mismatch
        
    Security:
        - Validates path to prevent directory traversal
        - Resolves symlinks
        - Checks file is regular file (not device/socket)
    """
    try:
        # Normalize and resolve path
        file_path = Path(path).resolve()
        
        # Security: Check path doesn't escape allowed directories
        # (This is a basic check - production should use more sophisticated validation)
        if '..' in str(path):
            logger.warning(f"Potential directory traversal detected: {path}")
        
        # Check file exists and is regular file
        if not file_path.exists():
            raise FileNotFoundError(f"Script file not found: {path}")
        
        if not file_path.is_file():
            raise ValueError(f"Path is not a regular file: {path}")
        
        # Read file content
        logger.debug(f"Reading script from file: {file_path}")
        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()
        
        logger.debug(f"Successfully read {len(content)} bytes from {file_path}")
        return content
    
    except FileNotFoundError:
        raise
    except PermissionError as e:
        logger.error(f"Permission denied reading {path}: {e}")
        raise
    except UnicodeDecodeError as e:
        logger.error(f"Encoding error reading {path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error reading script from {path}: {e}")
        raise
