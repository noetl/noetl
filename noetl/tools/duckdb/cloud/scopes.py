"""
Cloud storage scope detection and validation.
"""

import re
from typing import Dict, Set, List, Optional

from noetl.core.logger import setup_logger

from noetl.tools.duckdb.types import CloudScope
from noetl.tools.duckdb.errors import CloudStorageError

logger = setup_logger(__name__, include_location=True)


def detect_uri_scopes(commands: List[str]) -> Dict[str, Set[str]]:
    """
    Extract cloud URI scopes mentioned in SQL commands.
    
    Supports gs://, gcs:// (normalized to gs://), and s3:// URIs.
    
    Args:
        commands: List of SQL commands to analyze
        
    Returns:
        Dictionary mapping scheme ('gs', 's3') to set of bucket URIs
    """
    uri_scopes = {"gs": set(), "s3": set()}
    
    try:
        for cmd in commands:
            if not isinstance(cmd, str):
                continue
                
            for match in re.finditer(r"\b(gs|gcs|s3)://([^/'\s)]+)(/|\b)", cmd):
                scheme = match.group(1)
                bucket = match.group(2)
                
                # Normalize gcs:// to gs://
                if scheme == 'gcs':
                    scheme = 'gs'
                    
                # Use bucket-level scope; DuckDB matches on prefix
                scope = f"{scheme}://{bucket}"
                uri_scopes.setdefault(scheme, set()).add(scope)
                
        logger.debug(f"Detected URI scopes - gs: {sorted(uri_scopes.get('gs', []))}, s3: {sorted(uri_scopes.get('s3', []))}")
        return uri_scopes
        
    except Exception as e:
        logger.warning(f"Failed to detect URI scopes: {e}")
        return {"gs": set(), "s3": set()}


def infer_object_store_scope(params: Optional[Dict], service: str) -> Optional[str]:
    """
    Infer cloud storage scope from output_uri_base parameter.
    
    Args:
        params: Task parameters containing output_uri_base
        service: Service type ('gcs' or 's3')
        
    Returns:
        Inferred scope URI or None
    """
    if not params:
        return None
        
    base = params.get("output_uri_base")
    if not isinstance(base, str):
        return None
        
    if service == "gcs" and (base.startswith("gs://") or base.startswith("gcs://")):
        # Keep bucket only (gs://bucket)
        parts = base.split("/")
        if len(parts) >= 3:
            return "/".join(parts[:3])  # gs://bucket
            
    elif service == "s3" and base.startswith("s3://"):
        # Keep bucket only (s3://bucket)
        parts = base.split("/")
        if len(parts) >= 3:
            return "/".join(parts[:3])  # s3://bucket
            
    return None


def create_cloud_scope(scheme: str, bucket: str) -> CloudScope:
    """
    Create a CloudScope object from scheme and bucket.
    
    Args:
        scheme: URI scheme ('gs' or 's3')
        bucket: Bucket name
        
    Returns:
        CloudScope instance
        
    Raises:
        CloudStorageError: If parameters are invalid
    """
    if not scheme or not bucket:
        raise CloudStorageError("Both scheme and bucket are required for cloud scope")
        
    if scheme not in ['gs', 's3']:
        raise CloudStorageError(f"Unsupported cloud scheme: {scheme}")
        
    full_uri = f"{scheme}://{bucket}"
    
    return CloudScope(
        scheme=scheme,
        bucket=bucket,
        full_uri=full_uri
    )


def validate_cloud_output_requirement(
    commands: List[str], 
    require_cloud_output: bool = False
) -> bool:
    """
    Validate that cloud output is present when required.
    
    Args:
        commands: SQL commands to check for cloud COPY statements
        require_cloud_output: Whether cloud output is required
        
    Returns:
        True if validation passes
        
    Raises:
        CloudStorageError: If cloud output is required but not found
    """
    if not require_cloud_output:
        return True
        
    # Check for cloud COPY statements in commands
    cloud_copy_found = False
    
    for cmd in commands:
        if not isinstance(cmd, str):
            continue
            
        # Look for COPY statements with cloud URIs
        if 'COPY' in cmd.upper() and ('gs://' in cmd or 's3://' in cmd):
            cloud_copy_found = True
            break
            
    if require_cloud_output and not cloud_copy_found:
        raise CloudStorageError("No cloud COPY targets detected (gs:// or s3://) while require_cloud_output=true")
        
    return True