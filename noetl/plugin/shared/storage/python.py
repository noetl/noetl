"""
Python storage delegation for save operations.

Handles delegating to python plugin for data serialization/processing.
"""

import base64
from typing import Any, Callable, Dict, Optional

from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def handle_python_storage(
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
    Handle python storage type delegation.

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
    """
    # Extract code from storage config or use default data serialization
    code = storage_config.get("code") or storage_config.get("script")

    if not code:
        # Default python code to serialize data to JSON
        code = """
def main(data):
    import json
    result = json.dumps(data, indent=2, default=str)
    print(f"PYTHON_SAVE: {result}")
    return {"status": "success", "data": {"saved_data": data, "serialized": result}}
"""

    # Build task config for python plugin
    py_task = {
        "tool": "python",
        "task": "save_python",
        "code_b64": base64.b64encode(code.encode("utf-8")).decode("ascii"),
    }

    # Build with-params for python plugin
    py_with = {}
    try:
        if isinstance(task_with, dict):
            py_with.update(task_with)
    except Exception:
        pass

    # Pass rendered data as input to python code
    if isinstance(rendered_data, dict) and rendered_data:
        py_with["data"] = rendered_data
    elif isinstance(rendered_params, dict) and rendered_params:
        py_with["data"] = rendered_params
    else:
        py_with["data"] = {}

    # Pass through auth config
    if isinstance(auth_config, dict) and "auth" not in py_with:
        py_with["auth"] = auth_config
    elif credential_ref and "auth" not in py_with:
        py_with["auth"] = credential_ref

    logger.debug("SAVE: Calling python plugin for storage")

    # Delegate to python plugin
    try:
        from noetl.plugin.tools.python import execute_python_task

        py_result = execute_python_task(
            py_task, context, jinja_env, py_with, log_event_callback
        )
    except Exception as e:
        logger.error(f"SAVE: Failed delegating to python plugin: {e}")
        py_result = {"status": "error", "error": str(e)}

    # Normalize into save envelope
    if isinstance(py_result, dict) and py_result.get("status") == "success":
        return {
            "status": "success",
            "data": {"saved": "python", "task_result": py_result.get("data")},
            "meta": {
                "storage_kind": "python",
                "credential_ref": credential_ref,
            },
        }
    else:
        return {
            "status": "error",
            "data": None,
            "meta": {"storage_kind": "python"},
            "error": (
                (py_result or {}).get("error")
                if isinstance(py_result, dict)
                else "python save failed"
            ),
        }
