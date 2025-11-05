"""
Legacy credential system compatibility for DuckDB.

This module maintains backward compatibility with the old credential system
while the new unified auth system is being adopted.
"""

import os
from typing import Dict, Any, List, Optional, Callable

import httpx

from noetl.core.logger import setup_logger

from noetl.plugin.actions.duckdb.sql.rendering import escape_sql, render_deep
from noetl.plugin.actions.duckdb.types import JinjaEnvironment, ContextDict
from noetl.plugin.actions.duckdb.errors import AuthenticationError

logger = setup_logger(__name__, include_location=True)


def build_legacy_credential_prelude(
    task_config: Dict[str, Any],
    params: Dict[str, Any],
    jinja_env: JinjaEnvironment,
    context: ContextDict,
    fetch_fn: Callable[[str], Dict[str, Any]]
) -> List[str]:
    """
    Build DuckDB CREATE SECRET prelude statements from legacy credentials configuration.
    
    This function maintains exact compatibility with the original credential system format.
    
    Args:
        task_config: Task configuration containing credentials
        params: Rendered 'with' parameters dictionary
        jinja_env: Jinja2 environment for template rendering
        context: Context for rendering templates
        fetch_fn: Function to fetch credentials by key
        
    Returns:
        List of SQL statements to create DuckDB secrets and load extensions
    """
    from noetl.plugin.actions.duckdb.cloud.scopes import infer_object_store_scope
    
    params = dict(params or {})
    step_creds = (task_config or {}).get("credentials") or {}
    with_creds = (params.get("credentials") or {})
    creds_cfg = {**step_creds, **with_creds}
    creds_cfg = render_deep(jinja_env, context, creds_cfg)
    
    prelude = []
    need_httpfs = False
    need_pg = False

    for alias, spec in (creds_cfg or {}).items():
        if not isinstance(spec, dict): 
            continue
            
        try:
            key = spec.get("key")
            rec = {}
            if key:
                rec = fetch_fn(key) or {}
            merged = {**rec, **{k:v for k,v in spec.items() if k != "key"}}
            service = (merged.get("service") or merged.get("type") or "").lower()

            # Infer service by fields if not provided
            if not service:
                if {"db_host","db_name","db_user","db_password"} & set(merged.keys()):
                    service = "postgres"
                elif {"key_id","secret_key"} <= set(merged.keys()):
                    service = "gcs"

            secret_name = merged.get("secret_name") or alias

            if service == "gcs":
                need_httpfs = True
                key_id = merged.get("key_id")
                secret = merged.get("secret_key")
                if not (key_id and secret):
                    raise ValueError(f"GCS secret '{alias}' missing key_id/secret_key (HMAC required).")
                scope = merged.get("scope") or infer_object_store_scope(params, "gcs")
                stmt = (
                    f"CREATE OR REPLACE SECRET {secret_name} (\n"
                    f"  TYPE gcs,\n"
                    f"  KEY_ID '{escape_sql(key_id)}',\n"
                    f"  SECRET '{escape_sql(secret)}'"
                    + (f",\n  SCOPE '{escape_sql(scope)}'" if scope else "")
                    + "\n);"
                )
                prelude.append(stmt)

            elif service == "postgres":
                need_pg = True
                host = merged.get("db_host") or merged.get("host")
                port = int(merged.get("db_port") or merged.get("port") or 5432)
                db   = merged.get("db_name") or merged.get("database") or merged.get("dbname")
                user = merged.get("db_user") or merged.get("user") or merged.get("username")
                pwd  = merged.get("db_password") or merged.get("password")
                sslm = merged.get("sslmode")
                for val in (host, db, user, pwd):
                    if val in (None, ""):
                        raise ValueError(f"Postgres secret '{alias}' incomplete (need host, database, user, password).")
                stmt = (
                    f"CREATE OR REPLACE SECRET {secret_name} (\n"
                    f"  TYPE postgres,\n"
                    f"  HOST '{escape_sql(host)}',\n"
                    f"  PORT {port},\n"
                    f"  DATABASE '{escape_sql(db)}',\n"
                    f"  USER '{escape_sql(user)}',\n"
                    f"  PASSWORD '{escape_sql(pwd)}'"
                    + (f",\n  SSLMODE '{escape_sql(sslm)}'" if sslm else "")
                    + "\n);"
                )
                prelude.append(stmt)
                
        except Exception as e:
            logger.warning(f"Failed to build legacy credential for alias '{alias}': {e}")
            # Re-raise the exception for proper test behavior
            raise e

    # Add extension loading statements
    if need_httpfs:
        prelude.insert(0, "INSTALL httpfs; LOAD httpfs;")
    if need_pg:
        prelude.insert(0, "INSTALL postgres; LOAD postgres;")

    return prelude


def _build_legacy_secret_statement(
    alias: str, 
    spec: Dict[str, Any], 
    fetch_fn: Callable[[str], Dict[str, Any]]
) -> Optional[str]:
    """
    Build a single legacy credential secret statement.
    
    Args:
        alias: Credential alias
        spec: Credential specification
        fetch_fn: Function to fetch credential data
        
    Returns:
        CREATE SECRET SQL statement or None if not applicable
    """
    service = spec.get("service", "").lower()
    
    if service == "gcs":
        return _build_legacy_gcs_secret(alias, spec, fetch_fn)
    elif service == "postgres":
        return _build_legacy_postgres_secret(alias, spec, fetch_fn)
    elif service == "s3":
        return _build_legacy_s3_secret(alias, spec, fetch_fn)
    else:
        logger.debug(f"Unknown legacy service type '{service}' for alias '{alias}'")
        return None


def _build_legacy_gcs_secret(
    alias: str, 
    spec: Dict[str, Any], 
    fetch_fn: Callable[[str], Dict[str, Any]]
) -> str:
    """Build legacy GCS secret statement."""
    key_ref = spec.get("key")
    if not key_ref:
        raise AuthenticationError(f"GCS credential '{alias}' missing 'key' reference")
        
    try:
        cred_data = fetch_fn(key_ref)
        
        key_id = cred_data.get("key_id")
        secret_key = cred_data.get("secret_key")
        
        if not (key_id and secret_key):
            raise AuthenticationError(f"GCS credential '{key_ref}' missing key_id/secret_key")
            
        # Handle scope from spec or credential
        scope = spec.get("scope") or cred_data.get("scope")
        
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
        
    except Exception as e:
        raise AuthenticationError(f"Failed to build GCS secret '{alias}': {e}")


def _build_legacy_postgres_secret(
    alias: str, 
    spec: Dict[str, Any], 
    fetch_fn: Callable[[str], Dict[str, Any]]
) -> str:
    """Build legacy PostgreSQL secret statement."""
    key_ref = spec.get("key")
    if not key_ref:
        raise AuthenticationError(f"PostgreSQL credential '{alias}' missing 'key' reference")
        
    try:
        cred_data = fetch_fn(key_ref)
        
        # Extract connection parameters
        host = cred_data.get("db_host") or cred_data.get("host")
        port = int(cred_data.get("db_port") or cred_data.get("port") or 5432)
        database = cred_data.get("db_name") or cred_data.get("database") or cred_data.get("dbname")
        user = cred_data.get("db_user") or cred_data.get("user")
        password = cred_data.get("db_password") or cred_data.get("password")
        sslmode = cred_data.get("sslmode")
        
        # Validate required fields
        for field_name, value in [("host", host), ("database", database), ("user", user), ("password", password)]:
            if not value:
                raise AuthenticationError(f"PostgreSQL credential '{key_ref}' missing {field_name}")
                
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
        
    except Exception as e:
        raise AuthenticationError(f"Failed to build PostgreSQL secret '{alias}': {e}")


def _build_legacy_s3_secret(
    alias: str, 
    spec: Dict[str, Any], 
    fetch_fn: Callable[[str], Dict[str, Any]]
) -> str:
    """Build legacy S3 secret statement."""
    key_ref = spec.get("key")
    if not key_ref:
        raise AuthenticationError(f"S3 credential '{alias}' missing 'key' reference")
        
    try:
        cred_data = fetch_fn(key_ref)
        
        access_key_id = cred_data.get("access_key_id") or cred_data.get("key_id")
        secret_access_key = cred_data.get("secret_access_key") or cred_data.get("secret_key")
        region = cred_data.get("region")
        endpoint = cred_data.get("endpoint")
        
        if not (access_key_id and secret_access_key):
            raise AuthenticationError(f"S3 credential '{key_ref}' missing access_key_id/secret_access_key")
            
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
        
    except Exception as e:
        raise AuthenticationError(f"Failed to build S3 secret '{alias}': {e}")