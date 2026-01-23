"""
PostgreSQL authentication and connection parameter resolution.

This module handles:
- Unified auth system resolution
- Legacy credential fallback
- Connection parameter mapping and validation
- Connection string building
"""

from typing import Dict, Tuple
from jinja2 import Environment
from noetl.core.logger import setup_logger
from noetl.core.dsl.render import render_template
from noetl.worker.secrets import fetch_credential_by_key
from noetl.worker.auth_resolver import resolve_auth
from noetl.worker.auth_compatibility import transform_credentials_to_auth, validate_auth_transition

logger = setup_logger(__name__, include_location=True)


def resolve_postgres_auth(task_config: Dict, task_with: Dict, jinja_env: Environment, context: Dict) -> Tuple[Dict, Dict]:
    """
    Resolve PostgreSQL authentication and apply backwards compatibility transformations.
    
    Args:
        task_config: The task configuration
        task_with: The rendered 'with' parameters dictionary
        jinja_env: The Jinja2 environment for template rendering
        context: The context for rendering templates
        
    Returns:
        Tuple of (updated task_config, updated task_with)
    """
    # Apply backwards compatibility transformation for deprecated 'credentials' field
    validate_auth_transition(task_config, task_with)
    task_config, task_with = transform_credentials_to_auth(task_config, task_with)

    # Resolve unified auth system
    postgres_auth = None
    try:
        auth_config = task_config.get('auth') or task_with.get('auth')
        if auth_config:
            logger.debug("POSTGRES: Using unified auth system")
            mode, resolved_items = resolve_auth(auth_config, jinja_env, context)
            
            # For Postgres, we expect single auth mode or use the first resolved item
            resolved_auth = None
            if resolved_items:
                resolved_auth = list(resolved_items.values())[0]
            
            if resolved_auth:
                logger.debug(f"POSTGRES: Resolved auth service: '{resolved_auth.service}', payload keys: {list(resolved_auth.payload.keys()) if resolved_auth.payload else 'None'}")
                
                if resolved_auth.service == 'postgres':
                    postgres_auth = resolved_auth.payload
                    logger.debug(f"POSTGRES: Using postgres auth with fields: {list(postgres_auth.keys())}")
                    
                    # Map auth fields to Postgres connection parameters
                    field_mapping = {
                        # Direct field names (already correct)
                        'db_host': 'db_host',
                        'db_port': 'db_port', 
                        'db_user': 'db_user',
                        'db_password': 'db_password',
                        'db_name': 'db_name',
                        # Alternative field names that might need mapping
                        'host': 'db_host',
                        'port': 'db_port',
                        'user': 'db_user',
                        'username': 'db_user',
                        'password': 'db_password',
                        'database': 'db_name',
                        'dbname': 'db_name',
                        'sslmode': 'sslmode',
                        'dsn': 'db_conn_string',
                        'connection_string': 'db_conn_string'
                    }
                    
                    # Apply resolved auth to task_with (task_with takes precedence)
                    for auth_key, task_key in field_mapping.items():
                        if task_key not in task_with and postgres_auth.get(auth_key) is not None:
                            task_with[task_key] = postgres_auth[auth_key]
                            # Mask sensitive values in logs to prevent credential leakage
                            sensitive_terms = ('password', 'secret', 'token', 'key', 'credential')
                            value_display = '***' if any(term in auth_key.lower() for term in sensitive_terms) else postgres_auth[auth_key]
                            logger.debug(f"POSTGRES: Mapped {auth_key}={value_display} -> {task_key}")
                else:
                    logger.warning(f"POSTGRES: Expected 'postgres' service, got '{resolved_auth.service}'")
            else:
                logger.debug(f"POSTGRES: Auth resolved but not postgres type: {resolved_auth.service if resolved_auth else 'None'}")
    except Exception as e:
        logger.debug(f"POSTGRES: Unified auth processing failed: {e}", exc_info=True)
    
    # Legacy fallback: resolve single auth/credential reference 
    if not postgres_auth:
        try:
            # Check for legacy credential field (with deprecation warning)
            cred_ref = task_with.get('credential') or task_config.get('credential')
            if cred_ref:
                logger.warning("POSTGRES: 'credential' is deprecated; use 'auth' instead")
            
            # Also try auth if credential not found
            if not cred_ref:
                cred_ref = task_with.get('auth') or task_config.get('auth')
            
            if cred_ref and isinstance(cred_ref, str):
                logger.debug("POSTGRES: Using legacy auth system")
                try:
                    data = fetch_credential_by_key(str(cred_ref))
                except Exception:
                    data = {}
                if isinstance(data, dict):
                    # Map credential fields to Postgres connection parameters
                    field_mapping = {
                        'dsn': 'db_conn_string',
                        'db_conn_string': 'db_conn_string',
                        'db_host': 'db_host', 
                        'host': 'db_host', 
                        'pg_host': 'db_host',
                        'db_port': 'db_port', 
                        'port': 'db_port',
                        'db_user': 'db_user', 
                        'user': 'db_user',
                        'username': 'db_user',
                        'db_password': 'db_password', 
                        'password': 'db_password',
                        'db_name': 'db_name', 
                        'dbname': 'db_name',
                        'database': 'db_name',
                        'sslmode': 'sslmode'
                    }
                    
                    # Apply only missing keys in task_with
                    for src, dst in field_mapping.items():
                        if dst not in task_with and data.get(src) is not None:
                            task_with[dst] = data.get(src)
        except Exception:
            logger.debug("POSTGRES: failed to resolve legacy auth credential", exc_info=True)
    
    return task_config, task_with


def validate_and_render_connection_params(task_with: Dict, jinja_env: Environment, context: Dict) -> Tuple[str, str, str, str, str, str]:
    """
    Validate and render PostgreSQL connection parameters.
    
    Args:
        task_with: The rendered 'with' parameters dictionary
        jinja_env: The Jinja2 environment for template rendering
        context: The context for rendering templates
        
    Returns:
        Tuple of (host, port, user, password, database, connection_string)
        
    Raises:
        ValueError: If required parameters are missing or empty after rendering
    """
    logger.debug(f"POSTGRES: Final task_with keys: {list(task_with.keys())}")
    logger.debug(f"POSTGRES: Final task_with db params: db_host={task_with.get('db_host')}, db_port={task_with.get('db_port')}, db_user={task_with.get('db_user')}, db_password={'***' if task_with.get('db_password') else None}, db_name={task_with.get('db_name')}")
    
    # Get raw connection parameters
    pg_host_raw = task_with.get('db_host')
    pg_port_raw = task_with.get('db_port')
    pg_user_raw = task_with.get('db_user')
    pg_password_raw = task_with.get('db_password')
    pg_db_raw = task_with.get('db_name')
    
    # Validate required parameters
    _missing = []
    if not pg_host_raw: _missing.append('db_host')
    if not pg_port_raw: _missing.append('db_port')
    if not pg_user_raw: _missing.append('db_user')
    if not pg_password_raw: _missing.append('db_password')
    if not pg_db_raw: _missing.append('db_name')
    if _missing:
        raise ValueError(
            "Postgres connection is not configured. Missing: " + ", ".join(_missing) +
            ". Use `auth: <credential_key>` or `auth: {type: postgres, host: ..., user: ..., password: ..., database: ...}` on the step, or provide explicit db_* fields in `with:`."
        )

    # Build a rendering context that includes a 'workload' alias for compatibility
    render_ctx = dict(context) if isinstance(context, dict) else {}
    try:
        if isinstance(context, dict):
            if 'workload' not in render_ctx:
                render_ctx['workload'] = context
            if 'work' not in render_ctx:
                render_ctx['work'] = context
        # Also make with-params visible for simple substitutions if needed
        if isinstance(task_with, dict):
            for _k, _v in task_with.items():
                if _k not in render_ctx:
                    render_ctx[_k] = _v
    except Exception:
        # Best-effort enrichment; fall back to whatever context we have
        pass

    # Render database connection parameters with strict mode to catch undefined variables
    pg_host = render_template(jinja_env, pg_host_raw, render_ctx, strict_keys=True) if isinstance(pg_host_raw, str) and '{{' in pg_host_raw else pg_host_raw
    pg_port = render_template(jinja_env, pg_port_raw, render_ctx, strict_keys=True) if isinstance(pg_port_raw, str) and '{{' in pg_port_raw else pg_port_raw
    pg_user = render_template(jinja_env, pg_user_raw, render_ctx, strict_keys=True) if isinstance(pg_user_raw, str) and '{{' in pg_user_raw else pg_user_raw
    pg_password = render_template(jinja_env, pg_password_raw, render_ctx, strict_keys=True) if isinstance(pg_password_raw, str) and '{{' in pg_password_raw else pg_password_raw
    pg_db = render_template(jinja_env, pg_db_raw, render_ctx, strict_keys=True) if isinstance(pg_db_raw, str) and '{{' in pg_db_raw else pg_db_raw
    
    # Validate rendered values
    if not pg_host or str(pg_host).strip() == '':
        raise ValueError("Database host is empty after rendering")
    if not pg_port or str(pg_port).strip() == '':
        raise ValueError("Database port is empty after rendering")
    if not pg_user or str(pg_user).strip() == '':
        raise ValueError("Database user is empty after rendering")
    if not pg_password or str(pg_password).strip() == '':
        raise ValueError("Database password is empty after rendering")
    if not pg_db or str(pg_db).strip() == '':
        raise ValueError("Database name is empty after rendering")

    # Build or render connection string
    if 'db_conn_string' in task_with:
        conn_string_raw = task_with.get('db_conn_string')
        pg_conn_string = render_template(jinja_env, conn_string_raw, render_ctx, strict_keys=True) if isinstance(conn_string_raw, str) and '{{' in conn_string_raw else conn_string_raw
        if not pg_conn_string or str(pg_conn_string).strip() == '':
            raise ValueError("Database connection string is empty after rendering")
    else:
        # Build connection string with connect_timeout to prevent DNS hangs
        pg_conn_string = f"dbname={pg_db} user={pg_user} password={pg_password} host={pg_host} port={pg_port} connect_timeout=10"

    return pg_host, pg_port, pg_user, pg_password, pg_db, pg_conn_string
