"""
HTTP storage delegation for save operations.

Handles delegating to http plugin for HTTP POST/PUT operations.
"""

from typing import Any, Callable, Dict, Optional

from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def handle_http_storage(
    storage_config: Dict[str, Any],
    rendered_data: Dict[str, Any],
    rendered_params: Dict[str, Any],
    auth_config: Any,
    credential_ref: Optional[str],
    spec: Dict[str, Any],
    task_with: Optional[Dict[str, Any]],
    context: Dict[str, Any],
    jinja_env: Environment,
    log_event_callback: Optional[Callable],
) -> Dict[str, Any]:
    """
    Handle http storage type delegation.

    Args:
        storage_config: Storage configuration
        rendered_data: Rendered data mapping
        rendered_params: Rendered parameters
        auth_config: Authentication configuration
        credential_ref: Credential reference
        spec: Additional specifications
        task_with: Task with-parameters
        context: Execution context
        jinja_env: Jinja2 environment
        log_event_callback: Event logging callback

    Returns:
        Save result envelope

    Raises:
        ValueError: If endpoint not provided
    """
    # Extract HTTP config from storage config
    endpoint = storage_config.get("endpoint") or storage_config.get("url")
    method = storage_config.get("method", "POST")
    headers = storage_config.get("headers", {})

    if not endpoint:
        raise ValueError("http save requires 'endpoint' or 'url' in storage config")

    # Build task config for http plugin
    http_task = {
        "tool": "http",
        "task": "save_http",
        "endpoint": endpoint,
        "method": method,
        "headers": headers,
    }

    # Use rendered data as request data/payload
    if isinstance(rendered_data, dict) and rendered_data:
        http_task["data"] = rendered_data
    elif isinstance(rendered_params, dict) and rendered_params:
        http_task["data"] = rendered_params

    # Build with-params for http plugin
    http_with = {}
    try:
        if isinstance(task_with, dict):
            http_with.update(task_with)
    except Exception:
        pass

    # Pass through auth config
    if isinstance(auth_config, dict) and "auth" not in http_with:
        http_with["auth"] = auth_config
    elif credential_ref and "auth" not in http_with:
        http_with["auth"] = credential_ref

    logger.debug(f"SINK: Calling http plugin for storage to {endpoint}")

    # Delegate to http plugin
    try:
        from noetl.plugin.tools.http import execute_http_task

        http_result = execute_http_task(
            http_task, context, jinja_env, http_with, log_event_callback
        )
        logger.critical(f"SINK.HTTP: http_result={http_result}")
    except Exception as e:
        logger.error(f"SINK: Failed delegating to http plugin: {e}")
        http_result = {"status": "error", "error": str(e)}

    # Normalize into save envelope
    if isinstance(http_result, dict) and http_result.get("status") == "success":
        return {
            "status": "success",
            "data": {
                "saved": "http",
                "endpoint": endpoint,
                "task_result": http_result.get("data"),
            },
            "meta": {
                "tool_kind": "http",
                "credential_ref": credential_ref,
            },
        }
    else:
        return {
            "status": "error",
            "data": None,
            "meta": {"tool_kind": "http"},
            "error": (
                (http_result or {}).get("error")
                if isinstance(http_result, dict)
                else "http save failed"
            ),
        }
