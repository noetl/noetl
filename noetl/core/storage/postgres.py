"""
PostgreSQL storage delegation for save operations.

Handles building SQL statements and delegating to postgres plugin.
"""

import base64
from typing import Any, Callable, Dict, Optional

from jinja2 import Environment

from noetl.core.config import get_worker_settings
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def resolve_credential(
    credential_ref: Optional[str], spec: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Resolve credential from server and merge with spec.

    Uses centralized worker settings for server API URL.

    Args:
        credential_ref: Credential key reference
        spec: Specification dictionary to merge with

    Returns:
        Merged specification dictionary
    """
    if not credential_ref:
        return spec

    try:
        # Get credential URL from worker settings
        cred_key = str(credential_ref)
        import httpx

        try:
            worker_settings = get_worker_settings()
            url = worker_settings.endpoint_credential_by_key(
                cred_key, include_data=True
            )
        except Exception:
            # Fallback for cases where settings aren't initialized
            url = f"http://localhost:8082/api/credentials/{cred_key}?include_data=true"

        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                body = resp.json() or {}
                cdata = body.get("data") or {}
                if isinstance(cdata, dict):
                    merged = dict(cdata)
                    if isinstance(spec, dict):
                        for k, v in spec.items():
                            if v is not None:
                                merged[k] = v
                    return merged
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        logger.warning(f"Could not resolve credential for postgres save: {e}")

    return spec


def build_sql_statement(
    statement: Optional[str],
    table: Optional[str],
    mode: Optional[str],
    key_cols: Any,
    rendered_data: Dict[str, Any],
    rendered_params: Dict[str, Any],
) -> str:
    """
    Build SQL statement from configuration.

    Args:
        statement: Explicit SQL statement (if provided)
        table: Target table name
        mode: Operation mode (insert, upsert)
        key_cols: Key columns for upsert
        rendered_data: Rendered data mapping
        rendered_params: Rendered parameters (legacy)

    Returns:
        SQL statement string

    Raises:
        ValueError: If configuration invalid
    """
    if isinstance(statement, str) and statement.strip():
        # Use provided statement
        sql_text = statement

        # If the statement isn't templated, allow :name style by mapping to Jinja data
        bind_keys = []
        try:
            if isinstance(rendered_data, dict):
                bind_keys = list(rendered_data.keys())
            elif isinstance(rendered_params, dict):
                bind_keys = list(rendered_params.keys())
        except Exception:
            bind_keys = []

        if ("{{" not in sql_text) and bind_keys:
            try:
                for k in bind_keys:
                    sql_text = sql_text.replace(f":{k}", f"{{{{ data.{k} }}}}")
            except (TypeError, ValueError, AttributeError) as e:
                logger.warning(f"Could not replace bind parameters in SQL: {e}")

        return sql_text
    else:
        # Build a basic INSERT (or UPSERT) template from declarative mapping
        if not table or not isinstance(rendered_data, dict):
            raise ValueError(
                "postgres save requires 'table' and mapping 'data' when "
                "no 'statement' provided"
            )

        cols = list(rendered_data.keys())

        # Use Jinja to render values from data mapping we pass via with
        # Wrap values in single quotes and escape to ensure valid SQL for text values
        vals = []
        for c in cols:
            vals.append('{{"\'" ~ (data["%s"]|string)|replace("\'", "\'\'") ~ "\'"}}' % c)

        insert_sql = (
            f"INSERT INTO {table} (" + ", ".join(cols) + ") "
            f"VALUES (" + ", ".join(vals) + ")"
        )

        # Add UPSERT clause if mode=upsert
        if (mode or "").lower() == "upsert" and key_cols:
            key_list = key_cols if isinstance(key_cols, (list, tuple)) else [key_cols]
            set_parts = []

            for c in cols:
                if c not in key_list:
                    set_parts.append(f"{c} = EXCLUDED.{c}")

            if set_parts:
                insert_sql += (
                    f" ON CONFLICT (" + ", ".join(key_list) + ") "
                    f"DO UPDATE SET " + ", ".join(set_parts)
                )
            else:
                insert_sql += f" ON CONFLICT (" + ", ".join(key_list) + ") DO NOTHING"

        return insert_sql


def build_postgres_with_params(
    task_with: Optional[Dict[str, Any]],
    spec: Dict[str, Any],
    rendered_data: Dict[str, Any],
    rendered_params: Dict[str, Any],
    auth_config: Any,
    credential_ref: Optional[str],
) -> Dict[str, Any]:
    """
    Build with-parameters for postgres plugin.

    Args:
        task_with: Task with-parameters
        spec: Specification dictionary
        rendered_data: Rendered data mapping
        rendered_params: Rendered parameters (legacy)
        auth_config: Authentication configuration
        credential_ref: Credential reference

    Returns:
        With-parameters dictionary for postgres plugin
    """
    pg_with = {}

    # Start with provided 'with' for DB creds passthrough
    try:
        if isinstance(task_with, dict):
            pg_with.update(task_with)
    except (TypeError, ValueError, AttributeError) as e:
        logger.warning(f"Could not merge task_with into pg_with: {e}")

    # Map storage spec to expected postgres plugin keys
    try:
        if isinstance(spec, dict):
            # Allow direct connection string when provided
            if spec.get("dsn"):
                pg_with["db_conn_string"] = spec.get("dsn")

            for src, dst in (
                ("db_host", "db_host"),
                ("host", "db_host"),
                ("pg_host", "db_host"),
                ("db_port", "db_port"),
                ("port", "db_port"),
                ("db_user", "db_user"),
                ("user", "db_user"),
                ("db_password", "db_password"),
                ("password", "db_password"),
                ("db_name", "db_name"),
                ("dbname", "db_name"),
            ):
                if spec.get(src) is not None and not pg_with.get(dst):
                    pg_with[dst] = spec.get(src)
    except (TypeError, AttributeError, KeyError) as e:
        logger.warning(f"Could not map storage spec to postgres plugin keys: {e}")

    # Provide data to rendering context for the postgres plugin renderer
    # Canonical mapping: pass as 'data' for the postgres plugin to render
    if isinstance(rendered_data, dict) and rendered_data:
        pg_with["data"] = rendered_data
    elif isinstance(rendered_params, dict) and rendered_params:
        # Legacy: still allow 'params' to be passed for old statements
        pg_with["data"] = rendered_params

    # Pass through unified auth or legacy credential reference
    if isinstance(auth_config, dict) and "auth" not in pg_with:
        pg_with["auth"] = auth_config
    elif credential_ref and "auth" not in pg_with:
        pg_with["auth"] = credential_ref

    return pg_with


def handle_postgres_storage(
    storage_config: Dict[str, Any],
    rendered_data: Dict[str, Any],
    rendered_params: Dict[str, Any],
    statement: Optional[str],
    table: Optional[str],
    mode: Optional[str],
    key_cols: Any,
    auth_config: Any,
    credential_ref: Optional[str],
    spec: Dict[str, Any],
    task_with: Optional[Dict[str, Any]],
    context: Dict[str, Any],
    jinja_env: Environment,
    log_event_callback: Optional[Callable],
) -> Dict[str, Any]:
    """
    Handle postgres storage type delegation.

    This function:
    1. Resolves credentials if reference provided
    2. Builds SQL statement (from explicit statement or declarative mapping)
    3. Builds postgres plugin with-parameters
    4. Delegates to postgres plugin executor
    5. Returns normalized save result envelope

    Args:
        storage_config: Storage configuration
        rendered_data: Rendered data mapping
        rendered_params: Rendered parameters (legacy)
        statement: SQL statement (if provided)
        table: Target table name
        mode: Operation mode (insert, upsert)
        key_cols: Key columns for upsert
        auth_config: Authentication configuration
        credential_ref: Credential reference string
        spec: Additional specifications
        task_with: Task with-parameters
        context: Execution context
        jinja_env: Jinja2 environment
        log_event_callback: Event logging callback

    Returns:
        Save result envelope with status, data, and meta
    """
    logger.critical(f"SINK.POSTGRES: handle_postgres_storage CALLED | table={table} | mode={mode} | credential_ref={credential_ref} | rendered_data={rendered_data}")

    # Resolve credential alias if provided (best-effort)
    spec = resolve_credential(credential_ref, spec)

    # Build SQL statement
    sql_text = build_sql_statement(
        statement, table, mode, key_cols, rendered_data, rendered_params
    )

    # Migration helper: if the statement still refers to params.*, rewrite to data.*
    if isinstance(sql_text, str) and ("params." in sql_text):
        sql_text = sql_text.replace("params.", "data.")

    # Build task config for postgres plugin
    pg_task = {
        "tool": "postgres",
        "task": "save_postgres",
        "command_b64": base64.b64encode(sql_text.encode("utf-8")).decode("ascii"),
    }

    # Build with-parameters
    pg_with = build_postgres_with_params(
        task_with, spec, rendered_data, rendered_params, auth_config, credential_ref
    )

    # DEBUG: Log context keys before calling postgres plugin
    logger.debug(
        f"SINK: Calling postgres plugin with context keys: "
        f"{list(context.keys()) if isinstance(context, dict) else type(context)}"
    )
    if isinstance(context, dict) and "result" in context:
        result_val = context["result"]
        logger.debug(
            f"SINK: Found 'result' in context - type: {type(result_val)}, "
            f"keys: {list(result_val.keys()) if isinstance(result_val, dict) else 'not dict'}"
        )
    else:
        logger.debug("SINK: No 'result' found in context")

    # Delegate to postgres plugin
    try:
        from noetl.tools.postgres import execute_postgres_task

        pg_result = execute_postgres_task(
            pg_task, context, jinja_env, pg_with, log_event_callback
        )
    except Exception as e:
        logger.error(f"SINK: Failed delegating to postgres plugin: {e}")
        pg_result = {"status": "error", "error": str(e)}

    # Normalize into save envelope
    if isinstance(pg_result, dict) and pg_result.get("status") == "success":
        return {
            "status": "success",
            "data": {
                "saved": "postgres",
                "table": table,
                "task_result": pg_result.get("data"),
            },
            "meta": {
                "tool_kind": "postgres",
                "credential_ref": credential_ref,
                "save_spec": {
                    "mode": mode,
                    "key": key_cols,
                    "statement_present": bool(statement),
                    "param_keys": (
                        list(rendered_params.keys())
                        if isinstance(rendered_params, dict)
                        else None
                    ),
                },
            },
        }
    else:
        return {
            "status": "error",
            "data": None,
            "meta": {"tool_kind": "postgres"},
            "error": (
                (pg_result or {}).get("error")
                if isinstance(pg_result, dict)
                else "postgres save failed"
            ),
        }
