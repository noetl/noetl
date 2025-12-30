"""
DuckDB secret generation from resolved authentication data.
"""

from typing import List, Dict, Any

from noetl.core.logger import setup_logger

from noetl.tools.duckdb.sql.rendering import escape_sql
from noetl.tools.duckdb.errors import AuthenticationError

logger = setup_logger(__name__, include_location=True)


def generate_duckdb_secrets(resolved_auth_map: Dict[str, Any]) -> List[str]:
    """
    Generate DuckDB CREATE SECRET statements from resolved auth.
    
    Args:
        resolved_auth_map: Dictionary mapping alias to resolved auth data
        
    Returns:
        List of SQL statements for secret creation
    """
    statements = []
    
    if not resolved_auth_map:
        return statements
        
    try:
        for alias, auth_item in resolved_auth_map.items():
            if not auth_item:
                continue
                
            try:
                # _generate_single_secret now returns a list of statements
                stmts = _generate_single_secret(alias, auth_item)
                if stmts:
                    if isinstance(stmts, list):
                        statements.extend(stmts)
                    else:
                        statements.append(stmts)
                    
            except Exception as e:
                logger.warning(f"Failed to generate secret for alias '{alias}': {e}")
        
        if statements:
            logger.debug(f"Generated {len(statements)} DuckDB secret statements")
        return statements
        
    except Exception as e:
        raise AuthenticationError(f"Failed to generate DuckDB secrets: {e}")


def _generate_single_secret(alias: str, auth_item: Any) -> List[str]:
    """
    Generate DuckDB CREATE SECRET statements for a single auth alias.

    Args:
        alias: Secret alias/name
        auth_item: Resolved auth item (object or dict)

    Returns:
        List of SQL statements

    Raises:
        AuthenticationError: If secret generation fails for this auth item
    """
    try:
        if hasattr(auth_item, 'payload') and hasattr(auth_item, 'service'):
            config = auth_item.payload or {}
            auth_type = auth_item.service
            scope = getattr(auth_item, 'scope', None)
        elif isinstance(auth_item, dict):
            config = auth_item.get('payload') or auth_item.get('data') or auth_item
            auth_type = auth_item.get('service') or auth_item.get('type')
            scope = auth_item.get('scope')
        else:
            logger.warning(f"Unknown auth item type for alias '{alias}': {type(auth_item)}")
            return []

        if not auth_type:
            logger.warning(f"No auth type/service found for alias '{alias}'")
            return []

        auth_type = auth_type.lower()
        
        # Merge scope into config if not already present
        if scope and 'scope' not in config:
            config = {**config, 'scope': scope}
        
        if auth_type in ("gcs", "hmac", "gcs_service_account", "google_service_account"):
            return _generate_gcs_secret(alias, config)
        elif auth_type == "postgres":
            return _generate_postgres_secret(alias, config)
        elif auth_type == "snowflake":
            return _generate_snowflake_secret(alias, config)
        elif auth_type == "s3":
            return _generate_s3_secret(alias, config)
        else:
            logger.warning(f"Unsupported auth type '{auth_type}' for alias '{alias}'")
            return []
            
    except Exception as e:
        raise AuthenticationError(f"Failed to generate secret for alias '{alias}': {e}")


def _generate_gcs_secret(alias: str, config: Dict[str, Any]) -> List[str]:
    """
    Generate GCS/HMAC or Service Account DuckDB secret statements.
    
    Args:
        alias: Secret alias
        config: GCS credential configuration
        
    Returns:
        List of CREATE SECRET statements for GCS
    """
    print(f"[GCS SECRET DEBUG] Generating secret for alias '{alias}'", flush=True)
    print(f"[GCS SECRET DEBUG] Config keys: {list(config.keys())}", flush=True)
    
    # Check for service account credentials
    service_account_json = (
        config.get("service_account_json") or 
        config.get("service_account_key") or
        config.get("token")
    )
    scope = config.get("scope")
    
    print(f"[GCS SECRET DEBUG] service_account_json: {bool(service_account_json)}, scope: {scope}", flush=True)
    
    statements = []
    
    if service_account_json:
        import json
        # If it's already a dict, convert to string
        if isinstance(service_account_json, dict):
            service_account_json = json.dumps(service_account_json)
        
        # Escape for SQL
        escaped_json = service_account_json.replace("'", "''")
        
        # Ensure scope has a trailing slash for prefix matching
        actual_scope = scope
        if actual_scope and actual_scope.startswith('gs://') and not actual_scope.endswith('/'):
            actual_scope = f"{actual_scope}/"
        
        parts = [
            "TYPE gcs",
            "PROVIDER CONFIG",
            f"KEY_ID '{escaped_json}'"
        ]
        
        if actual_scope:
            parts.append(f"SCOPE '{escape_sql(actual_scope)}'")
            
        # Extension management statements
        # Note: httpfs is required, gcs extension is optional and handled separately
        statements.extend([
            "INSTALL httpfs;",
            "LOAD httpfs;"
        ])
        
        # Main GCS secret
        gcs_stmt = f"CREATE OR REPLACE SECRET {alias} (\n  {',\n  '.join(parts)}\n);"
        statements.append(gcs_stmt)
        
        # Configure global S3 settings for GCS compatibility via httpfs
        statements.extend([
            "SET s3_url_style='path';",
            "SET s3_endpoint='storage.googleapis.com';",
            "SET s3_region='auto';",
            "SET s3_use_ssl=true;"
        ])

        # ALSO create an S3 secret with GCS provider as fallback for httpfs
        # We try both PROVIDER GCS and simple S3 secret fallbacks
        try:
            s3_alias = f"{alias}_s3_fallback"
            s3_https_alias = f"{alias}_s3_https_fallback"
            
            # Try PROVIDER GCS first
            statements.append(f"CREATE OR REPLACE SECRET {s3_alias} (TYPE S3, PROVIDER CONFIG, KEY_ID '{escaped_json}'{f', SCOPE {chr(39)}{escape_sql(actual_scope)}{chr(39)}' if actual_scope else ''}, ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
            
            # And another simple S3 secret fallback using JSON as KEY_ID (some httpfs versions prefer this)
            statements.append(f"CREATE OR REPLACE SECRET {s3_alias}_simple (TYPE S3, KEY_ID '{escaped_json}'{f', SCOPE {chr(39)}{escape_sql(actual_scope)}{chr(39)}' if actual_scope else ''}, ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")

            # ALSO create a generic S3 secret without scope for storage.googleapis.com
            statements.append(f"CREATE OR REPLACE SECRET {s3_alias}_generic (TYPE S3, KEY_ID '{escaped_json}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")

            # If we have a gs:// scope, also create fallbacks for the translated https:// URL
            if actual_scope and actual_scope.startswith('gs://'):
                https_scope = actual_scope.replace('gs://', 'https://storage.googleapis.com/')
                
                # Provider GCS for HTTPS
                statements.append(f"CREATE OR REPLACE SECRET {s3_https_alias} (TYPE S3, PROVIDER CONFIG, KEY_ID '{escaped_json}', SCOPE '{escape_sql(https_scope)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
                
                # Simple S3 for HTTPS
                statements.append(f"CREATE OR REPLACE SECRET {s3_https_alias}_simple (TYPE S3, KEY_ID '{escaped_json}', SCOPE '{escape_sql(https_scope)}', ENDPOINT 'storage.googleapis.com', REGION 'auto', URL_STYLE 'path', USE_SSL 'true');")
        except Exception:
            pass

        return statements

    # Fallback to HMAC keys
    key_id = config.get("key_id")
    secret_key = config.get("secret_key") or config.get("secret")
    
    print(f"[GCS SECRET DEBUG] Using HMAC: key_id={bool(key_id)}, secret={bool(secret_key)}, scope={scope}", flush=True)
    
    if not (key_id and secret_key):
        raise AuthenticationError(f"GCS secret '{alias}' missing key_id/secret_key or service_account_json")
    
    # Ensure scope has a trailing slash for prefix matching
    actual_scope = scope
    if actual_scope and actual_scope.startswith('gs://') and not actual_scope.endswith('/'):
        actual_scope = f"{actual_scope}/"
    
    print(f"[GCS SECRET DEBUG] Normalized scope: {actual_scope}", flush=True)
    
    statements = [
        "INSTALL httpfs;",
        "LOAD httpfs;"
    ]
    
    # Configure global S3 settings for GCS compatibility via httpfs
    statements.extend([
        "SET s3_url_style='path';",
        "SET s3_endpoint='storage.googleapis.com';",
        "SET s3_region='auto';",
        "SET s3_use_ssl=true;"
    ])

    # Create GCS secret with HMAC credentials
    parts = [
        "TYPE gcs",
        f"KEY_ID '{escape_sql(key_id)}'",
        f"SECRET '{escape_sql(secret_key)}'"
    ]
    
    if actual_scope:
        parts.append(f"SCOPE '{escape_sql(actual_scope)}'")
    
    gcs_stmt = f"CREATE OR REPLACE SECRET {alias} (\n  {',\n  '.join(parts)}\n);"
    statements.append(gcs_stmt)
    
    print(f"[GCS SECRET DEBUG] Created {len(statements)} statements for HMAC secret", flush=True)
    
    return statements


def _generate_postgres_secret(alias: str, config: Dict[str, Any]) -> List[str]:
    """
    Generate PostgreSQL DuckDB secret statements.
    
    Args:
        alias: Secret alias
        config: PostgreSQL credential configuration
        
    Returns:
        List of SQL statements for PostgreSQL
    """
    host = config.get("host") or config.get("db_host")
    port = int(config.get("port") or config.get("db_port") or 5432)
    database = config.get("database") or config.get("db_name") or config.get("dbname")
    user = config.get("user") or config.get("db_user") or config.get("username")
    password = config.get("password") or config.get("db_password")
    sslmode = config.get("sslmode")
    
    # Validate required fields
    for field_name, value in [("host", host), ("database", database), ("user", user), ("password", password)]:
        if not value:
            raise AuthenticationError(f"Postgres secret '{alias}' missing required field: {field_name}")
    
    parts = [
        "TYPE postgres",
        f"HOST '{escape_sql(host)}'",
        f"PORT {port}",
        f"DATABASE '{escape_sql(database)}'",
        f"USER '{escape_sql(user)}'",
        f"PASSWORD '{escape_sql(password)}'"
    ]
    
    if sslmode:
        parts.append(f"SSLMODE '{escape_sql(sslmode)}'")
    
    return [
        "INSTALL postgres;",
        "LOAD postgres;",
        f"CREATE OR REPLACE SECRET {alias} (\n  {',\n  '.join(parts)}\n);"
    ]


def _generate_snowflake_secret(alias: str, config: Dict[str, Any]) -> List[str]:
    """
    Generate Snowflake DuckDB secret statements.
    
    Args:
        alias: Secret alias
        config: Snowflake credential configuration
        
    Returns:
        List of SQL statements for Snowflake
    """
    account = config.get("account") or config.get("sf_account")
    user = config.get("user") or config.get("username") or config.get("sf_user")
    password = config.get("password") or config.get("sf_password")
    database = config.get("database") or config.get("sf_database")
    schema = config.get("schema") or config.get("sf_schema", "PUBLIC")
    warehouse = config.get("warehouse") or config.get("sf_warehouse")
    role = config.get("role") or config.get("sf_role")
    
    # Validate required fields
    for field_name, value in [("account", account), ("user", user), ("password", password)]:
        if not value:
            raise AuthenticationError(f"Snowflake secret '{alias}' missing required field: {field_name}")
    
    parts = [
        "TYPE snowflake",
        f"ACCOUNT '{escape_sql(account)}'",
        f"USER '{escape_sql(user)}'",
        f"PASSWORD '{escape_sql(password)}'"
    ]
    
    if database:
        parts.append(f"DATABASE '{escape_sql(database)}'")
    if schema:
        parts.append(f"SCHEMA '{escape_sql(schema)}'")
    if warehouse:
        parts.append(f"WAREHOUSE '{escape_sql(warehouse)}'")
    if role:
        parts.append(f"ROLE '{escape_sql(role)}'")
    
    return [
        "INSTALL snowflake FROM community;",
        "LOAD snowflake;",
        f"CREATE OR REPLACE SECRET {alias} (\n  {',\n  '.join(parts)}\n);"
    ]


def _generate_s3_secret(alias: str, config: Dict[str, Any]) -> List[str]:
    """
    Generate S3 DuckDB secret statements.
    
    Args:
        alias: Secret alias
        config: S3 credential configuration
        
    Returns:
        List of SQL statements for S3
    """
    access_key_id = config.get("access_key_id") or config.get("key_id")
    secret_access_key = config.get("secret_access_key") or config.get("secret_key") or config.get("secret")
    region = config.get("region")
    endpoint = config.get("endpoint")
    
    if not (access_key_id and secret_access_key):
        raise AuthenticationError(f"S3 secret '{alias}' missing access_key_id/secret_access_key")
    
    parts = [
        "TYPE s3",
        f"KEY_ID '{escape_sql(access_key_id)}'",
        f"SECRET '{escape_sql(secret_access_key)}'"
    ]
    
    if region:
        parts.append(f"REGION '{escape_sql(region)}'")
    if endpoint:
        parts.append(f"ENDPOINT '{escape_sql(endpoint)}'")
    
    return [
        "INSTALL httpfs;",
        "LOAD httpfs;",
        f"CREATE OR REPLACE SECRET {alias} (\n  {',\n  '.join(parts)}\n);"
    ]
