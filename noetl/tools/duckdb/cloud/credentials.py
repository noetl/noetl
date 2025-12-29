"""
Cloud credential processing and auto-configuration.
"""

import os
import re
from typing import Dict, Any, Optional, Set

import httpx

from noetl.core.logger import setup_logger

from noetl.tools.duckdb.sql.rendering import escape_sql
from noetl.tools.duckdb.errors import CloudStorageError, AuthenticationError

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
    
    Supports both service account key files and HMAC keys:
    - Service account JSON: Uses TOKEN credential type with key file content
    - HMAC keys: Uses KEY_ID/SECRET credential type
    
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
    
    print(f"[GCS DEBUG] credential lookup: task_config.gcs_credential={task_config.get('gcs_credential')}, task_with.gcs_credential={task_with.get('gcs_credential')}, resolved cred_name={cred_name}", flush=True)
    logger.info(f"GCS credential lookup: task_config.gcs_credential={task_config.get('gcs_credential')}, task_with.gcs_credential={task_with.get('gcs_credential')}, resolved cred_name={cred_name}")
    logger.debug(f"Auto-configuring GCS credentials with cred_name={cred_name}")
    
    if not cred_name:
        logger.warning("No GCS credential name found, skipping GCS auto-configuration")
        return 0
        
    try:
        print(f"[GCS DEBUG] About to fetch credential: {cred_name}", flush=True)
        credential_data = _fetch_credential(cred_name)
        print(f"[GCS DEBUG] Fetched credential_data keys: {list(credential_data.keys()) if credential_data else 'None'}", flush=True)
        if not credential_data:
            print(f"[GCS DEBUG] No credential data returned for {cred_name}", flush=True)
            return 0
        
        # Ensure httpfs extension is loaded
        try:
            connection.execute("LOAD httpfs;")
        except Exception:
            pass
        
        # Check if this is a service account token/key file
        service_account_key = credential_data.get('service_account_key')
        service_account_json = credential_data.get('service_account_json')
        token = credential_data.get('token')
        
        print(f"[GCS DEBUG] Credential type check: sa_key={bool(service_account_key)}, sa_json={bool(service_account_json)}, token={bool(token)}", flush=True)
        logger.info(f"GCS credential type detection: service_account_key={bool(service_account_key)}, service_account_json={bool(service_account_json)}, token={bool(token)}")
        
        if service_account_key or service_account_json or token:
            # Use TOKEN-based authentication for service accounts
            return _configure_gcs_token_auth(
                connection, gcs_scopes, credential_data, cred_name
            )
        else:
            # Use HMAC key-based authentication (legacy)
            return _configure_gcs_hmac_auth(
                connection, gcs_scopes, credential_data, cred_name
            )
            
    except Exception as e:
        print(f"[GCS DEBUG] Exception in _configure_gcs_credentials: {type(e).__name__}: {e}", flush=True)
        logger.warning(f"Failed to auto-configure GCS credentials from '{cred_name}': {e}")
        import traceback
        traceback.print_exc()
        return 0


def _configure_gcs_token_auth(
    connection: Any,
    gcs_scopes: Set[str],
    credential_data: Dict[str, Any],
    cred_name: str
) -> int:
    """
    Configure GCS using service account token/key file authentication.
    
    Args:
        connection: DuckDB connection
        gcs_scopes: Set of GCS URI scopes
        credential_data: Credential data
        cred_name: Credential name for logging
        
    Returns:
        Number of GCS secrets created
    """
    # Support multiple field names for service account credentials
    service_account_key = (
        credential_data.get('service_account_key') or 
        credential_data.get('service_account_json') or
        credential_data.get('token')
    )
    scope_from_cred = credential_data.get('scope')
    
    print(f"[TOKEN AUTH DEBUG] service_account_key type: {type(service_account_key)}, is_dict: {isinstance(service_account_key, dict)}", flush=True)
    
    if not service_account_key:
        print(f"[TOKEN AUTH DEBUG] No service_account_key found!", flush=True)
        logger.warning(f"GCS credential '{cred_name}' missing service_account_key, service_account_json, or token")
        return 0
    
    # If service_account_key is a dict (JSON object), convert to JSON string
    if isinstance(service_account_key, dict):
        import json
        service_account_key = json.dumps(service_account_key)
        print(f"[TOKEN AUTH DEBUG] Converted dict to JSON string, length: {len(service_account_key)}", flush=True)
    
    # Use credential scope if provided, otherwise use detected scopes
    scopes_to_configure = [scope_from_cred] if scope_from_cred else sorted(gcs_scopes)
    secrets_created = 0
    
    print(f"[TOKEN AUTH DEBUG] scopes_to_configure: {scopes_to_configure}", flush=True)
    
    # Write service account JSON to a temporary file
    import tempfile
    import os
    temp_key_file = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(service_account_key)
            temp_key_file = f.name
            print(f"[TOKEN AUTH DEBUG] Wrote service account JSON to {temp_key_file}", flush=True)
        
        for scope in scopes_to_configure:
            if not scope:
                continue
                
            scope_tag = re.sub(r"[^a-zA-Z0-9_]+", "_", scope)
            secret_name = f"noetl_auto_gcs_{scope_tag}"
            
            print(f"[TOKEN AUTH DEBUG] Creating secret {secret_name} for scope {scope}", flush=True)
            
            # Use TYPE GCS with KEYFILE parameter for service account authentication
            ddl_keyfile = f"""
                CREATE OR REPLACE SECRET {secret_name} (
                    TYPE GCS,
                    KEYFILE '{escape_sql(temp_key_file)}',
                    SCOPE '{escape_sql(scope)}'
                );
            """
            
            print(f"[TOKEN AUTH DEBUG] DDL command prepared", flush=True)
            
            try:
                connection.execute(ddl_keyfile)
                print(f"[TOKEN AUTH DEBUG] Secret created successfully!", flush=True)
                logger.info(f"Auto-configured GCS secret (KEY_ID) {secret_name} for {scope}")
                secrets_created += 1
            except Exception as e:
                print(f"[TOKEN AUTH DEBUG] Exception creating secret: {type(e).__name__}: {e}", flush=True)
                logger.warning(f"Failed to create GCS KEY_ID secret {secret_name}: {e}")
    finally:
        # Don't clean up temp file - DuckDB needs it to persist for the duration of the connection
        # The file will be cleaned up when the container/process exits
        if temp_key_file:
            print(f"[TOKEN AUTH DEBUG] Temp file {temp_key_file} will persist for connection lifetime", flush=True)
    
    print(f"[TOKEN AUTH DEBUG] Returning secrets_created={secrets_created}", flush=True)
    return secrets_created


def _configure_gcs_hmac_auth(
    connection: Any,
    gcs_scopes: Set[str],
    credential_data: Dict[str, Any],
    cred_name: str
) -> int:
    """
    Configure GCS using HMAC key-based authentication (legacy).
    
    Args:
        connection: DuckDB connection
        gcs_scopes: Set of GCS URI scopes
        credential_data: Credential data
        cred_name: Credential name for logging
        
    Returns:
        Number of GCS secrets created
    """
    key_id = credential_data.get('key_id')
    secret = credential_data.get('secret_key') or credential_data.get('secret')
    endpoint = credential_data.get('endpoint') or 'storage.googleapis.com'
    region = credential_data.get('region') or 'auto'
    url_style = credential_data.get('url_style') or 'path'
    scope_from_cred = credential_data.get('scope')
    
    if not (key_id and secret):
        logger.warning(f"GCS credential '{cred_name}' missing key_id or secret")
        return 0
    if not (key_id and secret):
        logger.warning(f"GCS credential '{cred_name}' missing key_id or secret")
        return 0
            
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
            logger.info(f"Auto-configured GCS secret (HMAC) {secret_name} for {scope}")
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