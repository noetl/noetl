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
        List of CREATE SECRET SQL statements
        
    Raises:
        AuthenticationError: If secret generation fails
    """
    statements = []
    
    if not resolved_auth_map:
        return statements
        
    try:
        for alias, auth_item in resolved_auth_map.items():
            if not auth_item:
                continue
                
            try:
                stmt = _generate_single_secret(alias, auth_item)
                if stmt:
                    statements.append(stmt)
                    
            except Exception as e:
                logger.warning(f"Failed to generate secret for alias '{alias}': {e}")
                
        logger.debug(f"Generated {len(statements)} DuckDB secret statements")
        return statements
        
    except Exception as e:
        raise AuthenticationError(f"Failed to generate DuckDB secrets: {e}")


def _generate_single_secret(alias: str, auth_item: Any) -> str:
    """
    Generate a single DuckDB CREATE SECRET statement.
    
    Args:
        alias: Secret alias/name
        auth_item: Resolved auth item
        
    Returns:
        CREATE SECRET SQL statement
        
    Raises:
        AuthenticationError: If secret generation fails for this auth item
    """
    try:
        config = auth_item.payload
        auth_type = auth_item.service
        
        if auth_type in ("gcs", "hmac"):
            return _generate_gcs_secret(alias, config)
        elif auth_type == "postgres":
            return _generate_postgres_secret(alias, config)
        elif auth_type == "snowflake":
            return _generate_snowflake_secret(alias, config)
        elif auth_type == "s3":
            return _generate_s3_secret(alias, config)
        else:
            logger.warning(f"Unsupported auth type '{auth_type}' for alias '{alias}'")
            return ""
            
    except Exception as e:
        raise AuthenticationError(f"Failed to generate secret for alias '{alias}': {e}")


def _generate_gcs_secret(alias: str, config: Dict[str, Any]) -> str:
    """
    Generate GCS/HMAC DuckDB secret.
    
    Args:
        alias: Secret alias
        config: GCS credential configuration
        
    Returns:
        CREATE SECRET statement for GCS
    """
    key_id = config.get("key_id")
    secret_key = config.get("secret_key") or config.get("secret")
    scope = config.get("scope")
    
    if not (key_id and secret_key):
        raise AuthenticationError(f"GCS secret '{alias}' missing key_id/secret_key (HMAC required)")
    
    parts = [
        "TYPE gcs",
        f"KEY_ID '{escape_sql(key_id)}'",
        f"SECRET '{escape_sql(secret_key)}'"
    ]
    
    if scope:
        parts.append(f"SCOPE '{escape_sql(scope)}'")
    
    stmt = (
        f"CREATE OR REPLACE SECRET {alias} (\n"
        f"  {',\n  '.join(parts)}\n"
        f");"
    )
    
    return stmt


def _generate_postgres_secret(alias: str, config: Dict[str, Any]) -> str:
    """
    Generate PostgreSQL DuckDB secret.
    
    Args:
        alias: Secret alias
        config: PostgreSQL credential configuration
        
    Returns:
        CREATE SECRET statement for PostgreSQL
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
    
    stmt = (
        f"CREATE OR REPLACE SECRET {alias} (\n"
        f"  {',\n  '.join(parts)}\n"
        f");"
    )
    
    return stmt


def _generate_snowflake_secret(alias: str, config: Dict[str, Any]) -> str:
    """
    Generate Snowflake DuckDB secret.
    
    Args:
        alias: Secret alias
        config: Snowflake credential configuration
        
    Returns:
        CREATE SECRET statement for Snowflake
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
    
    stmt = (
        f"CREATE OR REPLACE SECRET {alias} (\n"
        f"  {',\n  '.join(parts)}\n"
        f");"
    )
    
    return stmt


def _generate_s3_secret(alias: str, config: Dict[str, Any]) -> str:
    """
    Generate S3 DuckDB secret.
    
    Args:
        alias: Secret alias
        config: S3 credential configuration
        
    Returns:
        CREATE SECRET statement for S3
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
    
    stmt = (
        f"CREATE OR REPLACE SECRET {alias} (\n"
        f"  {',\n  '.join(parts)}\n"
        f");"
    )
    
    return stmt