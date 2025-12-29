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
    task_with: Dict[str, Any],
    catalog_id: Optional[int] = None,
    execution_id: Optional[int] = None
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
            gcs_count = _configure_gcs_credentials(
                connection,
                uri_scopes['gs'],
                task_config,
                task_with,
                catalog_id=catalog_id,
                execution_id=execution_id,
            )
            secrets_created += gcs_count
            
        # Configure S3 credentials  
        if uri_scopes.get('s3'):
            s3_count = _configure_s3_credentials(
                connection,
                uri_scopes['s3'],
                task_config,
                task_with,
                catalog_id=catalog_id,
                execution_id=execution_id,
            )
            secrets_created += s3_count
            
        return secrets_created
        
    except Exception as e:
        raise CloudStorageError(f"Failed to configure cloud credentials: {e}")


def _configure_gcs_credentials(
    connection: Any,
    gcs_scopes: Set[str],
    task_config: Dict[str, Any],
    task_with: Dict[str, Any],
    catalog_id: Optional[int] = None,
    execution_id: Optional[int] = None
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
        credential_data = _fetch_credential(
            cred_name,
            catalog_id=catalog_id,
            execution_id=execution_id,
        )
        print(f"[GCS DEBUG] Fetched credential_data keys: {list(credential_data.keys()) if credential_data else 'None'}", flush=True)
        if not credential_data:
            print(f"[GCS DEBUG] No credential data returned for {cred_name}", flush=True)
            return 0
        
        # Ensure extensions are installed and loaded
        try:
            connection.execute("INSTALL httpfs; LOAD httpfs;")
            print("[GCS DEBUG] httpfs extension installed and loaded", flush=True)
        except Exception as e:
            print(f"[GCS DEBUG] Warning: failed to install/load httpfs: {e}", flush=True)

        # For modern DuckDB versions, we might also need the 'gcs' extension
        try:
            connection.execute("INSTALL gcs; LOAD gcs;")
            print("[GCS DEBUG] gcs extension installed and loaded", flush=True)
        except Exception as e:
            print(f"[GCS DEBUG] Warning: failed to install/load gcs: {e}", flush=True)
        
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
    
    DuckDB's httpfs extension supports GCS authentication via service account
    key files. We write the JSON to a temp file and configure httpfs to use it.

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
        service_account_key_str = json.dumps(service_account_key)
        print(f"[TOKEN AUTH DEBUG] Converted dict to JSON string, length: {len(service_account_key_str)}", flush=True)
    else:
        service_account_key_str = str(service_account_key)

    # Use credential scope if provided, otherwise use detected scopes
    scopes_to_configure = [scope_from_cred] if scope_from_cred else sorted(gcs_scopes)
    secrets_created = 0

    print(f"[TOKEN AUTH DEBUG] scopes_to_configure: {scopes_to_configure}", flush=True)

    # Write service account JSON to a persistent temp file
    import tempfile
    import os
    temp_key_file = None
    try:
        # Create temp file that persists for the process lifetime
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(service_account_key_str)
            temp_key_file = f.name
            print(f"[TOKEN AUTH DEBUG] Wrote service account JSON to {temp_key_file}", flush=True)

        # Set GOOGLE_APPLICATION_CREDENTIALS environment variable
        # This is required for DuckDB's GCS extension to find the credentials
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = temp_key_file
        print(f"[TOKEN AUTH DEBUG] Set GOOGLE_APPLICATION_CREDENTIALS={temp_key_file}", flush=True)
        logger.info(f"Configured Google ADC with service account key file: {temp_key_file}")

        # Configure httpfs to use the service account credentials
        # Use SET to configure the GCS authentication for httpfs extension
        try:
            # Set the GCS service account path for httpfs
            connection.execute("SET gcs_access_token='';")  # Clear any existing token
            print("[TOKEN AUTH DEBUG] Cleared GCS access token", flush=True)
            
            # Configure global S3 settings for GCS compatibility via httpfs
            connection.execute("SET s3_url_style='path';")
            connection.execute("SET s3_endpoint='storage.googleapis.com';")
            connection.execute("SET s3_region='auto';")
            connection.execute("SET s3_use_ssl=true;")
            print("[TOKEN AUTH DEBUG] Configured global S3 settings for GCS compatibility", flush=True)
        except Exception as e:
            print(f"[TOKEN AUTH DEBUG] Could not configure global S3 settings: {e}", flush=True)

        # Create DuckDB GCS secrets for each scope with explicit credential path
        for scope in scopes_to_configure:
            if not scope:
                continue

            # DuckDB scope matching is prefix-based.
            # We ensure the scope has the scheme and ends with a slash for better prefix matching.
            actual_scope = scope
            if actual_scope.startswith('gs://') and not actual_scope.endswith('/'):
                actual_scope = f"{actual_scope}/"
            
            # For S3 fallback, we also want to match the translated HTTPS URL
            https_scope = actual_scope.replace('gs://', 'https://storage.googleapis.com/')
            
            scope_tag = re.sub(r"[^a-zA-Z0-9_]+", "_", actual_scope.rstrip('/'))
            secret_name = f"noetl_auto_gcs_{scope_tag}"

            print(f"[TOKEN AUTH DEBUG] Creating secret {secret_name} for scope {actual_scope}", flush=True)

            # Fallback for when modern providers are not available or fail
            # We want to ensure S3 secrets are also created as fallbacks for httpfs
            # We will try to create them using whatever method we can
            
            # Helper to create S3 fallback secrets
            def create_s3_fallbacks(conn, name_base, sa_key, scope_gs, scope_https, key_file):
                s3_count = 0
                try:
                    s3_name = f"{name_base}_s3_fallback"
                    s3_https_name = f"{name_base}_s3_https_fallback"
                    
                    # Apply global S3 settings before creating secrets
                    try:
                        conn.execute("SET s3_url_style='path';")
                        conn.execute("SET s3_endpoint='storage.googleapis.com';")
                        conn.execute("SET s3_region='auto';")
                        conn.execute("SET s3_use_ssl=true;")
                    except Exception as set_ex:
                        print(f"[TOKEN AUTH DEBUG] S3 fallback: could not set global settings: {set_ex}", flush=True)

                    if isinstance(sa_key, dict):
                        import json
                        escaped_json = json.dumps(sa_key).replace("'", "''")
                        # Try PROVIDER GCS with JSON_KEY (requires httpfs + specific gcs bridge)
                        try:
                            conn.execute(f"CREATE OR REPLACE SECRET {s3_name} (TYPE S3, PROVIDER GCS, JSON_KEY '{escaped_json}', SCOPE '{escape_sql(scope_gs)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
                            conn.execute(f"CREATE OR REPLACE SECRET {s3_https_name} (TYPE S3, PROVIDER GCS, JSON_KEY '{escaped_json}', SCOPE '{escape_sql(scope_https)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
                            print(f"[TOKEN AUTH DEBUG] Created S3 fallback secrets with PROVIDER GCS for {scope_gs}", flush=True)
                            s3_count += 2
                        except Exception as e:
                            print(f"[TOKEN AUTH DEBUG] PROVIDER GCS failed, trying simple S3: {e}", flush=True)
                            # Try simple S3 secret with KEY_ID as JSON
                            ddl_s3 = f"CREATE OR REPLACE SECRET {s3_name} (TYPE S3, KEY_ID '{escaped_json}', SCOPE '{escape_sql(scope_gs)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');"
                            ddl_s3_https = f"CREATE OR REPLACE SECRET {s3_https_name} (TYPE S3, KEY_ID '{escaped_json}', SCOPE '{escape_sql(scope_https)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');"
                            print(f"[TOKEN AUTH DEBUG] Executing simple S3 fallback: {ddl_s3[:150]}...", flush=True)
                            conn.execute(ddl_s3)
                            conn.execute(ddl_s3_https)
                            print(f"[TOKEN AUTH DEBUG] Created simple S3 fallback secrets for {scope_gs}", flush=True)
                            s3_count += 2

                        # ALSO create a generic S3 secret without scope for storage.googleapis.com
                        try:
                            conn.execute(f"CREATE OR REPLACE SECRET {s3_name}_generic (TYPE S3, KEY_ID '{escaped_json}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
                            print(f"[TOKEN AUTH DEBUG] Created generic S3 fallback secret for storage.googleapis.com", flush=True)
                            s3_count += 1
                        except Exception as e:
                            print(f"[TOKEN AUTH DEBUG] Generic S3 fallback failed: {e}", flush=True)
                    else:
                        # Try PROVIDER GCS with KEY_FILE
                        try:
                            conn.execute(f"CREATE OR REPLACE SECRET {s3_name} (TYPE S3, PROVIDER GCS, KEY_FILE '{key_file}', SCOPE '{escape_sql(scope_gs)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
                            conn.execute(f"CREATE OR REPLACE SECRET {s3_https_name} (TYPE S3, PROVIDER GCS, KEY_FILE '{key_file}', SCOPE '{escape_sql(scope_https)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
                            print(f"[TOKEN AUTH DEBUG] Created S3 fallback secrets with PROVIDER GCS and KEY_FILE for {scope_gs}", flush=True)
                            s3_count += 2
                        except Exception as e:
                            print(f"[TOKEN AUTH DEBUG] PROVIDER GCS with KEY_FILE failed, trying simple S3: {e}", flush=True)
                            # Try simple S3 secret with KEY_ID as file path
                            ddl_s3 = f"CREATE OR REPLACE SECRET {s3_name} (TYPE S3, KEY_ID '{key_file}', SCOPE '{escape_sql(scope_gs)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');"
                            ddl_s3_https = f"CREATE OR REPLACE SECRET {s3_https_name} (TYPE S3, KEY_ID '{key_file}', SCOPE '{escape_sql(scope_https)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');"
                            print(f"[TOKEN AUTH DEBUG] Executing simple S3 fallback with KEY_FILE: {ddl_s3[:150]}...", flush=True)
                            conn.execute(ddl_s3)
                            conn.execute(ddl_s3_https)
                            print(f"[TOKEN AUTH DEBUG] Created simple S3 fallback secrets with KEY_FILE for {scope_gs}", flush=True)
                            s3_count += 2

                        # ALSO create a generic S3 secret without scope for storage.googleapis.com
                        try:
                            conn.execute(f"CREATE OR REPLACE SECRET {s3_name}_generic (TYPE S3, KEY_ID '{key_file}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
                            print(f"[TOKEN AUTH DEBUG] Created generic S3 fallback secret with KEY_FILE for storage.googleapis.com", flush=True)
                            s3_count += 1
                        except Exception as e:
                            print(f"[TOKEN AUTH DEBUG] Generic S3 fallback with KEY_FILE failed: {e}", flush=True)
                except Exception as ex:
                    print(f"[TOKEN AUTH DEBUG] S3 fallback creation failed: {ex}", flush=True)
                return s3_count

            # Try PROVIDER SERVICE_ACCOUNT first (Modern DuckDB 1.1+)
            try:
                # Use JSON_KEY if we have the dict, otherwise use KEY_FILE
                if isinstance(service_account_key, dict):
                    import json
                    escaped_json = json.dumps(service_account_key).replace("'", "''")
                    ddl_gcs_service_account = f"""
                        CREATE OR REPLACE SECRET {secret_name} (
                            TYPE GCS,
                            PROVIDER SERVICE_ACCOUNT,
                            JSON_KEY '{escaped_json}',
                            SCOPE '{escape_sql(actual_scope)}'
                        );
                    """
                else:
                    ddl_gcs_service_account = f"""
                        CREATE OR REPLACE SECRET {secret_name} (
                            TYPE GCS,
                            PROVIDER SERVICE_ACCOUNT,
                            KEY_FILE '{temp_key_file}',
                            SCOPE '{escape_sql(actual_scope)}'
                        );
                    """
                # Redact JSON_KEY for logging
                redacted_ddl = re.sub(r"JSON_KEY\s*'[^']*'", "JSON_KEY '[REDACTED]'", ddl_gcs_service_account)
                print(f"[TOKEN AUTH DEBUG] Executing: {redacted_ddl}", flush=True)
                connection.execute(ddl_gcs_service_account)
                
                print(f"[TOKEN AUTH DEBUG] Secret with PROVIDER=SERVICE_ACCOUNT created successfully!", flush=True)
                logger.info(f"Auto-configured GCS secret {secret_name} for {actual_scope} with PROVIDER=SERVICE_ACCOUNT")
                secrets_created += 1
            except Exception as e:
                print(f"[TOKEN AUTH DEBUG] PROVIDER=SERVICE_ACCOUNT failed: {e}", flush=True)

                # Try PROVIDER config method (uses GOOGLE_APPLICATION_CREDENTIALS)
                try:
                    ddl_gcs_provider = f"""
                        CREATE OR REPLACE SECRET {secret_name} (
                            TYPE GCS,
                            PROVIDER config,
                            SCOPE '{escape_sql(actual_scope)}'
                        );
                    """
                    print(f"[TOKEN AUTH DEBUG] Executing: {ddl_gcs_provider}", flush=True)
                    connection.execute(ddl_gcs_provider)
                    print(f"[TOKEN AUTH DEBUG] Secret with PROVIDER=config created successfully!", flush=True)
                    logger.info(f"Auto-configured GCS secret {secret_name} for {actual_scope} with PROVIDER=config")
                    secrets_created += 1
                except Exception as e:
                    print(f"[TOKEN AUTH DEBUG] PROVIDER=config method failed: {type(e).__name__}: {e}", flush=True)

                    # Fallback 1: try with KEY_ID parameter (for HMAC or legacy)
                    try:
                        # Don't use escape_sql on file path - it adds extra quotes
                        ddl_gcs_key = f"""
                            CREATE OR REPLACE SECRET {secret_name} (
                                TYPE GCS,
                                KEY_ID '{temp_key_file}',
                                SCOPE '{escape_sql(actual_scope)}'
                            );
                        """
                        print(f"[TOKEN AUTH DEBUG] Executing: {ddl_gcs_key}", flush=True)
                        connection.execute(ddl_gcs_key)
                        print(f"[TOKEN AUTH DEBUG] Secret with KEY_ID parameter created successfully!", flush=True)
                        logger.info(f"Auto-configured GCS secret {secret_name} for {actual_scope} with KEY_ID")
                        secrets_created += 1
                    except Exception as e2:
                        print(f"[TOKEN AUTH DEBUG] KEY_ID method failed: {type(e2).__name__}: {e2}", flush=True)

                        # Fallback 2: rely on environment variable only
                        try:
                            ddl_gcs_env = f"""
                                CREATE OR REPLACE SECRET {secret_name} (
                                    TYPE GCS,
                                    SCOPE '{escape_sql(actual_scope)}'
                                );
                            """
                            print(f"[TOKEN AUTH DEBUG] Executing: {ddl_gcs_env}", flush=True)
                            connection.execute(ddl_gcs_env)
                            print(f"[TOKEN AUTH DEBUG] Secret with env fallback created successfully!", flush=True)
                            logger.info(f"Auto-configured GCS secret {secret_name} for {actual_scope} using environment variable")
                            secrets_created += 1
                        except Exception as e3:
                            print(f"[TOKEN AUTH DEBUG] Final env fallback failed: {e3}", flush=True)
                            logger.warning(f"Failed to create GCS secret {secret_name}: {e3}")

            # ALWAYS create S3 fallback secrets regardless of GCS success
            # This is critical for httpfs compatibility when gcs extension is missing
            print(f"[TOKEN AUTH DEBUG] Creating S3 fallbacks for {actual_scope}", flush=True)
            secrets_created += create_s3_fallbacks(connection, secret_name, service_account_key, actual_scope, https_scope, temp_key_file)

        # ALWAYS create a default (unscoped) GCS secret as ultimate fallback
        # This ensures any GCS operation can succeed even if scope matching fails
        print(f"[TOKEN AUTH DEBUG] Creating default unscoped GCS secret", flush=True)
        default_secret_name = "noetl_auto_gcs_default"

        # Try PROVIDER SERVICE_ACCOUNT first
        try:
            if isinstance(service_account_key, dict):
                import json
                escaped_json = json.dumps(service_account_key).replace("'", "''")
                ddl_default_sa = f"""
                    CREATE OR REPLACE SECRET {default_secret_name} (
                        TYPE GCS,
                        PROVIDER SERVICE_ACCOUNT,
                        JSON_KEY '{escaped_json}'
                    );
                """
            else:
                ddl_default_sa = f"""
                    CREATE OR REPLACE SECRET {default_secret_name} (
                        TYPE GCS,
                        PROVIDER SERVICE_ACCOUNT,
                        KEY_FILE '{temp_key_file}'
                    );
                """
            connection.execute(ddl_default_sa)
            print(f"[TOKEN AUTH DEBUG] Default secret with PROVIDER=SERVICE_ACCOUNT created!", flush=True)
            logger.info(f"Auto-configured default GCS secret with PROVIDER=SERVICE_ACCOUNT")
            secrets_created += 1
        except Exception as e:
            print(f"[TOKEN AUTH DEBUG] Default PROVIDER=SERVICE_ACCOUNT failed: {e}", flush=True)

            # Try PROVIDER config method
            try:
                ddl_default_provider = f"""
                    CREATE OR REPLACE SECRET {default_secret_name} (
                        TYPE GCS,
                        PROVIDER config
                    );
                """
                connection.execute(ddl_default_provider)
                print(f"[TOKEN AUTH DEBUG] Default secret with PROVIDER=config created!", flush=True)
                logger.info(f"Auto-configured default GCS secret with PROVIDER=config")
                secrets_created += 1
            except Exception as e:
                print(f"[TOKEN AUTH DEBUG] Default PROVIDER=config failed: {e}", flush=True)

                # Fallback 1: try with KEY_ID
                try:
                    ddl_default_key = f"""
                        CREATE OR REPLACE SECRET {default_secret_name} (
                            TYPE GCS,
                            KEY_ID '{temp_key_file}'
                        );
                    """
                    connection.execute(ddl_default_key)
                    print(f"[TOKEN AUTH DEBUG] Default secret with KEY_ID created!", flush=True)
                    logger.info(f"Auto-configured default GCS secret with KEY_ID")
                    secrets_created += 1
                except Exception as e2:
                    print(f"[TOKEN AUTH DEBUG] Default KEY_ID failed: {e2}", flush=True)

                    # Fallback 2: environment variable
                    try:
                        ddl_default_env = f"""
                            CREATE OR REPLACE SECRET {default_secret_name} (
                                TYPE GCS
                            );
                        """
                        connection.execute(ddl_default_env)
                        print(f"[TOKEN AUTH DEBUG] Default secret with env created!", flush=True)
                        logger.info(f"Auto-configured default GCS secret using environment variable")
                        secrets_created += 1
                    except Exception as e3:
                        print(f"[TOKEN AUTH DEBUG] All default methods failed: {e3}", flush=True)
                        logger.warning(f"Failed to create default GCS secret: {e3}")

        # Also create unscoped S3 fallback secrets for storage.googleapis.com
        try:
            if isinstance(service_account_key, dict):
                import json
                escaped_json = json.dumps(service_account_key).replace("'", "''")
                connection.execute(f"CREATE OR REPLACE SECRET noetl_auto_gcs_s3_default (TYPE S3, KEY_ID '{escaped_json}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
                print(f"[TOKEN AUTH DEBUG] Created unscoped S3 fallback secret for storage.googleapis.com", flush=True)
                secrets_created += 1
            else:
                connection.execute(f"CREATE OR REPLACE SECRET noetl_auto_gcs_s3_default (TYPE S3, KEY_ID '{temp_key_file}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
                print(f"[TOKEN AUTH DEBUG] Created unscoped S3 fallback secret with KEY_FILE for storage.googleapis.com", flush=True)
                secrets_created += 1
        except Exception as e:
            print(f"[TOKEN AUTH DEBUG] Unscoped S3 fallback failed: {e}", flush=True)


    finally:
        # Keep temp file for process lifetime - DuckDB needs it
        if temp_key_file:
            print(f"[TOKEN AUTH DEBUG] Service account key file will persist at {temp_key_file}", flush=True)
    
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

    # Ensure extensions are installed and loaded
    try:
        connection.execute("INSTALL httpfs; LOAD httpfs;")
        connection.execute("INSTALL gcs; LOAD gcs;")
    except Exception:
        pass
            
    # Use credential scope if provided, otherwise use detected scopes
    scopes_to_configure = [scope_from_cred] if scope_from_cred else sorted(gcs_scopes)
    secrets_created = 0
    
    for scope in scopes_to_configure:
        if not scope:
            continue
            
        # DuckDB scope matching is prefix-based.
        # We ensure the scope has the scheme and ends with a slash for better prefix matching.
        actual_scope = scope
        if actual_scope.startswith('gs://') and not actual_scope.endswith('/'):
            actual_scope = f"{actual_scope}/"
        
        # For S3 fallback, we also want to match the translated HTTPS URL
        https_scope = actual_scope.replace('gs://', 'https://storage.googleapis.com/')
        
        scope_tag = re.sub(r"[^a-zA-Z0-9_]+", "_", actual_scope.rstrip('/'))
        secret_name = f"noetl_auto_gcs_{scope_tag}"
        
        # Configure global S3 settings for GCS compatibility via httpfs (HMAC case)
        try:
            connection.execute("SET s3_url_style='path';")
            connection.execute("SET s3_endpoint='storage.googleapis.com';")
            connection.execute("SET s3_region='auto';")
            connection.execute("SET s3_use_ssl=true;")
        except Exception:
            pass

        # Try GCS-specific secret type first
        ddl_gcs = f"""
            CREATE OR REPLACE SECRET {secret_name} (
                TYPE GCS,
                KEY_ID '{escape_sql(key_id)}',
                SECRET '{escape_sql(secret)}',
                SCOPE '{escape_sql(actual_scope)}'
            );
        """
        
        try:
            connection.execute(ddl_gcs)
            logger.info(f"Auto-configured GCS secret (HMAC) {secret_name} for {actual_scope}")
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
                    SCOPE '{escape_sql(actual_scope)}'
                );
            """
            connection.execute(ddl_s3_provider)
            logger.info(f"Auto-configured GCS secret (S3 provider fallback) {secret_name} for {actual_scope}")
            secrets_created += 1
            
        # ALSO create an S3 secret fallback using key/secret for this scope
        try:
            s3_name = f"{secret_name}_s3_fallback"
            s3_https_name = f"{secret_name}_s3_https_fallback"
            connection.execute(f"CREATE OR REPLACE SECRET {s3_name} (TYPE S3, KEY_ID '{escape_sql(key_id)}', SECRET '{escape_sql(secret)}', SCOPE '{escape_sql(actual_scope)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
            connection.execute(f"CREATE OR REPLACE SECRET {s3_https_name} (TYPE S3, KEY_ID '{escape_sql(key_id)}', SECRET '{escape_sql(secret)}', SCOPE '{escape_sql(https_scope)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
            secrets_created += 2
        except Exception:
            pass
            
    return secrets_created


def _configure_s3_credentials(
    connection: Any,
    s3_scopes: Set[str],
    task_config: Dict[str, Any],
    task_with: Dict[str, Any],
    catalog_id: Optional[int] = None,
    execution_id: Optional[int] = None
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
        credential_data = _fetch_credential(
            cred_name,
            catalog_id=catalog_id,
            execution_id=execution_id,
        )
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


def _fetch_credential(
    credential_name: str,
    catalog_id: Optional[int] = None,
    execution_id: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """Fetch credential or keychain data from the NoETL API.

    Tries the credentials API first. If the credential is missing or the
    caller explicitly requested a keychain entry (keychain: prefix), falls
    back to the keychain API using catalog_id/NOETL_CATALOG_ID.
    """
    try:
        print(f"[FETCH_CRED DEBUG] Starting credential fetch for '{credential_name}', catalog_id={catalog_id}, execution_id={execution_id}", flush=True)

        base_url = os.environ.get('NOETL_SERVER_URL', 'http://noetl.noetl.svc.cluster.local:8082').rstrip('/')
        if not base_url.endswith('/api'):
            base_url = base_url + '/api'

        print(f"[FETCH_CRED DEBUG] base_url={base_url}", flush=True)

        # Allow hints like "keychain:name" or "kc:name"
        use_keychain_hint = False
        name = credential_name
        if isinstance(name, str):
            lowered = name.lower()
            if lowered.startswith('keychain:') or lowered.startswith('kc:'):
                use_keychain_hint = True
                name = name.split(':', 1)[1]
                print(f"[FETCH_CRED DEBUG] Keychain hint detected, extracted name='{name}'", flush=True)

        def _parse_credential_response(resp_json: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            raw = (resp_json or {}).get('data') or {}
            if isinstance(raw, dict) and isinstance(raw.get('data'), dict):
                return raw.get('data')
            return raw if isinstance(raw, dict) else None

        with httpx.Client(timeout=5.0) as client:
            credential_payload: Optional[Dict[str, Any]] = None

            if not use_keychain_hint:
                print(f"[FETCH_CRED DEBUG] Trying credentials API for '{name}'", flush=True)
                cred_url = f"{base_url}/credentials/{name}?include_data=true"
                response = client.get(cred_url)
                print(f"[FETCH_CRED DEBUG] Credentials API response: {response.status_code}", flush=True)

                if response.status_code == 200:
                    credential_payload = _parse_credential_response(response.json())
                    print(f"[FETCH_CRED DEBUG] Credentials API returned payload: {bool(credential_payload)}", flush=True)
                elif response.status_code != 404:
                    print(f"[FETCH_CRED DEBUG] Credentials API error: {response.status_code}", flush=True)
                    logger.warning(
                        f"Failed to fetch credential '{name}': HTTP {response.status_code}"
                    )
                else:
                    print(f"[FETCH_CRED DEBUG] Credential not found (404), will try keychain", flush=True)

            # If credential fetch failed or keychain was requested, try keychain API
            if credential_payload is None:
                print(f"[FETCH_CRED DEBUG] Attempting keychain fallback...", flush=True)
                catalog_val = catalog_id or os.environ.get('NOETL_CATALOG_ID')
                print(f"[FETCH_CRED DEBUG] catalog_val={catalog_val}, catalog_id={catalog_id}, env={os.environ.get('NOETL_CATALOG_ID')}", flush=True)

                if catalog_val:
                    keychain_url = f"{base_url}/keychain/{catalog_val}/{name}"
                    params = {'scope_type': 'global'}
                    if execution_id:
                        params['execution_id'] = execution_id

                    print(f"[FETCH_CRED DEBUG] Keychain URL: {keychain_url}, params={params}", flush=True)

                    kc_resp = client.get(keychain_url, params=params)
                    print(f"[FETCH_CRED DEBUG] Keychain API response: {kc_resp.status_code}", flush=True)

                    if kc_resp.status_code == 200:
                        body = kc_resp.json() or {}
                        print(f"[FETCH_CRED DEBUG] Keychain response body keys: {list(body.keys())}", flush=True)
                        token_data = body.get('token_data') or body.get('data')
                        print(f"[FETCH_CRED DEBUG] token_data type: {type(token_data)}, is_dict: {isinstance(token_data, dict)}", flush=True)

                        # status=expired is still a miss for our purposes
                        status = body.get('status')
                        print(f"[FETCH_CRED DEBUG] Keychain status: {status}", flush=True)

                        if status == 'expired' and body.get('auto_renew'):
                            print(f"[FETCH_CRED DEBUG] Keychain entry is expired", flush=True)
                            logger.warning(
                                f"Keychain entry '{name}' for catalog {catalog_val} is expired"
                            )
                        else:
                            result = token_data if isinstance(token_data, dict) else None
                            print(f"[FETCH_CRED DEBUG] Returning keychain data: {bool(result)}", flush=True)
                            if result:
                                print(f"[FETCH_CRED DEBUG] Keychain data keys: {list(result.keys())}", flush=True)
                            return result
                    elif kc_resp.status_code != 404:
                        print(f"[FETCH_CRED DEBUG] Keychain API error: {kc_resp.status_code}, body: {kc_resp.text[:200]}", flush=True)
                        logger.warning(
                            f"Failed to fetch keychain '{name}' (catalog {catalog_val}): HTTP {kc_resp.status_code}"
                        )
                    else:
                        print(f"[FETCH_CRED DEBUG] Keychain entry not found (404)", flush=True)
                else:
                    print(f"[FETCH_CRED DEBUG] No catalog_id available for keychain lookup", flush=True)
                    logger.debug(
                        f"No catalog_id available for keychain lookup of '{name}', skipping keychain fallback"
                    )

            print(f"[FETCH_CRED DEBUG] Returning credential_payload: {bool(credential_payload)}", flush=True)
            return credential_payload if isinstance(credential_payload, dict) else None

    except Exception as e:
        print(f"[FETCH_CRED DEBUG] Exception during fetch: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise AuthenticationError(f"Failed to fetch credential '{credential_name}': {e}")
