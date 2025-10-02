"""
Cloud credential processing and auto-configuration.
"""

import os
import re
from typing import Dict, Any, Optional, Set

import httpx

from noetl.core.logger import setup_logger

from ..sql.rendering import escape_sql
from ..errors import CloudStorageError, AuthenticationError

logger = setup_logger(__name__, include_location=True)


def configure_cloud_credentials(
    connection: Any,
    uri_scopes: Dict[str, Set[str]],
    task_config: Dict[str, Any],
    task_with: Dict[str, Any]
) -> int:
    """
    Auto-configure cloud credentials for detected URI scopes.
    
    Args:
        connection: DuckDB connection
        uri_scopes: Detected URI scopes by scheme
        task_config: Task configuration
        task_with: Task with parameters
        
    Returns:
        Number of secrets configured
        
    Raises:
        CloudStorageError: If credential configuration fails
    """
    secrets_created = 0
    
    try:
        # Configure GCS credentials
        if uri_scopes.get('gs'):
            gcs_count = _configure_gcs_credentials(connection, uri_scopes['gs'], task_config, task_with)
            secrets_created += gcs_count
            
        # Configure S3 credentials  
        if uri_scopes.get('s3'):
            s3_count = _configure_s3_credentials(connection, uri_scopes['s3'], task_config, task_with)
            secrets_created += s3_count
            
        return secrets_created
        
    except Exception as e:
        raise CloudStorageError(f"Failed to configure cloud credentials: {e}")


def _configure_gcs_credentials(
    connection: Any,
    gcs_scopes: Set[str],
    task_config: Dict[str, Any],
    task_with: Dict[str, Any]
) -> int:
    """
    Configure GCS credentials for detected scopes.
    
    Args:
        connection: DuckDB connection
        gcs_scopes: Set of GCS URI scopes
        task_config: Task configuration
        task_with: Task with parameters
        
    Returns:
        Number of GCS secrets created
    """
    if not gcs_scopes:
        return 0
        
    # Determine credential name from various sources
    cred_name = (
        task_config.get('gcs_credential') or 
        task_with.get('gcs_credential') or
        task_config.get('cloud_credential') or 
        task_with.get('cloud_credential') or
        os.environ.get('NOETL_GCS_CREDENTIAL')
    )
    
    logger.debug(f"Auto-configuring GCS credentials with cred_name={cred_name}")
    
    if not cred_name:
        logger.warning("No GCS credential name found, skipping GCS auto-configuration")
        return 0
        
    try:
        credential_data = _fetch_credential(cred_name)
        if not credential_data:
            return 0
            
        key_id = credential_data.get('key_id')
        secret = credential_data.get('secret_key') or credential_data.get('secret')
        endpoint = credential_data.get('endpoint') or 'storage.googleapis.com'
        region = credential_data.get('region') or 'auto'
        url_style = credential_data.get('url_style') or 'path'
        scope_from_cred = credential_data.get('scope')
        
        if not (key_id and secret):
            logger.warning("GCS credential missing key_id or secret, skipping auto-configuration")
            return 0
            
        # Ensure httpfs extension is loaded
        try:
            connection.execute("LOAD httpfs;")
        except Exception:
            pass
            
        # Use credential scope if provided, otherwise use detected scopes
        scopes_to_configure = [scope_from_cred] if scope_from_cred else sorted(gcs_scopes)
        secrets_created = 0
        
        for scope in scopes_to_configure:
            if not scope:
                continue
                
            scope_tag = re.sub(r"[^a-zA-Z0-9_]+", "_", scope)
            secret_name = f"noetl_auto_gcs_{scope_tag}"
            
            # Try GCS-specific secret type first
            ddl_gcs = f"""
                CREATE OR REPLACE SECRET {secret_name} (
                    TYPE GCS,
                    KEY_ID '{escape_sql(key_id)}',
                    SECRET '{escape_sql(secret)}',
                    SCOPE '{escape_sql(scope)}'
                );
            """
            
            try:
                connection.execute(ddl_gcs)
                logger.info(f"Auto-configured GCS secret {secret_name} for {scope}")
                secrets_created += 1
            except Exception:
                # Fallback to S3 provider syntax
                ddl_s3_provider = f"""
                    CREATE OR REPLACE SECRET {secret_name} (
                        TYPE S3,
                        PROVIDER GCS,
                        KEY_ID '{escape_sql(key_id)}',
                        SECRET '{escape_sql(secret)}',
                        REGION 'auto',
                        ENDPOINT 'storage.googleapis.com',
                        URL_STYLE 'path',
                        SCOPE '{escape_sql(scope)}'
                    );
                """
                connection.execute(ddl_s3_provider)
                logger.info(f"Auto-configured GCS secret (S3 provider fallback) {secret_name} for {scope}")
                secrets_created += 1
                
        return secrets_created
        
    except Exception as e:
        logger.warning(f"Failed to auto-configure GCS credentials from '{cred_name}': {e}")
        return 0


def _configure_s3_credentials(
    connection: Any,
    s3_scopes: Set[str],
    task_config: Dict[str, Any],
    task_with: Dict[str, Any]
) -> int:
    """
    Configure S3 credentials for detected scopes.
    
    Args:
        connection: DuckDB connection
        s3_scopes: Set of S3 URI scopes
        task_config: Task configuration
        task_with: Task with parameters
        
    Returns:
        Number of S3 secrets created
    """
    if not s3_scopes:
        return 0
        
    # Determine credential name from various sources
    cred_name = (
        task_config.get('s3_credential') or 
        task_with.get('s3_credential') or
        task_config.get('cloud_credential') or 
        task_with.get('cloud_credential') or
        os.environ.get('NOETL_S3_CREDENTIAL')
    )
    
    logger.debug(f"Auto-configuring S3 credentials with cred_name={cred_name}")
    
    if not cred_name:
        logger.warning("No S3 credential name found, skipping S3 auto-configuration")
        return 0
        
    try:
        credential_data = _fetch_credential(cred_name)
        if not credential_data:
            return 0
            
        key_id = credential_data.get('key_id') or credential_data.get('access_key_id')
        secret = (credential_data.get('secret_key') or 
                 credential_data.get('secret_access_key') or 
                 credential_data.get('secret'))
        region = credential_data.get('region') or 'us-east-1'
        endpoint = credential_data.get('endpoint')
        scope_from_cred = credential_data.get('scope')
        
        if not (key_id and secret):
            logger.warning("S3 credential missing key_id or secret, skipping auto-configuration")
            return 0
            
        # Ensure httpfs extension is loaded
        try:
            connection.execute("LOAD httpfs;")
        except Exception:
            pass
            
        # Use credential scope if provided, otherwise use detected scopes
        scopes_to_configure = [scope_from_cred] if scope_from_cred else sorted(s3_scopes)
        secrets_created = 0
        
        for scope in scopes_to_configure:
            if not scope:
                continue
                
            scope_tag = re.sub(r"[^a-zA-Z0-9_]+", "_", scope)
            secret_name = f"noetl_auto_s3_{scope_tag}"
            
            # Build S3 secret DDL
            parts = [
                "TYPE S3",
                f"KEY_ID '{escape_sql(key_id)}'",
                f"SECRET '{escape_sql(secret)}'",
                f"REGION '{escape_sql(region)}'"
            ]
            
            if endpoint:
                parts.append(f"ENDPOINT '{escape_sql(endpoint)}'")
                
            parts.append(f"SCOPE '{escape_sql(scope)}'")
            
            ddl_s3 = f"""
                CREATE OR REPLACE SECRET {secret_name} (
                    {',\n                    '.join(parts)}
                );
            """
            
            try:
                connection.execute(ddl_s3)
                logger.info(f"Auto-configured S3 secret {secret_name} for {scope}")
                secrets_created += 1
            except Exception as e:
                logger.warning(f"Failed to create S3 secret {secret_name}: {e}")
                
        return secrets_created
        
    except Exception as e:
        logger.warning(f"Failed to auto-configure S3 credentials from '{cred_name}': {e}")
        return 0


def _fetch_credential(credential_name: str) -> Optional[Dict[str, Any]]:
    """
    Fetch credential data from the NoETL server.
    
    Args:
        credential_name: Name of the credential to fetch
        
    Returns:
        Credential data dictionary or None if not found
        
    Raises:
        AuthenticationError: If credential fetch fails
    """
    try:
        base_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
        if not base_url.endswith('/api'):
            base_url = base_url + '/api'
            
        url = f"{base_url}/credentials/{credential_name}?include_data=true"
        
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url)
            
            if response.status_code == 200:
                body = response.json() or {}
                raw = body.get('data') or {}
                
                # Handle nested data structure
                if isinstance(raw, dict) and isinstance(raw.get('data'), dict):
                    payload = raw.get('data')
                else:
                    payload = raw
                    
                return payload if isinstance(payload, dict) else {}
            else:
                logger.warning(f"Failed to fetch credential '{credential_name}': HTTP {response.status_code}")
                return None
                
    except Exception as e:
        raise AuthenticationError(f"Failed to fetch credential '{credential_name}': {e}")