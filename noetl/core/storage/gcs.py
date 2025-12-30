"""
GCS storage delegation for sink operations.

Handles uploading files to Google Cloud Storage buckets.
"""

from typing import Any, Callable, Dict, Optional
from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def handle_gcs_storage(
    tool_config: Dict[str, Any],
    rendered_data: Dict[str, Any],
    rendered_params: Dict[str, Any],
    auth_config: Optional[Dict[str, Any]],
    credential_ref: Optional[str],
    spec: Dict[str, Any],
    task_with: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    log_event_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Handle GCS storage sink operation by delegating to GCS tool.

    Args:
        tool_config: Sink tool configuration (kind, source, destination, credential, etc.)
        rendered_data: Rendered data context (may contain file path)
        rendered_params: Rendered parameters
        auth_config: Optional authentication configuration
        credential_ref: Credential reference key
        spec: Specification dictionary
        task_with: Task-level parameters
        context: Execution context
        jinja_env: Jinja2 environment for templating
        log_event_callback: Optional event logging callback

    Returns:
        Result dictionary from GCS upload operation
    """
    logger.info(f"GCS.STORAGE: Starting GCS sink handler with config: {tool_config}")

    credential = None
    source = None
    destination = None

    try:
        from noetl.tools.gcs import execute_gcs_task

        # Resolve source path from explicit config or rendered payloads
        # Support both 'source' and 'source_path' fields
        source = tool_config.get("source") or tool_config.get("source_path")
        if not source:
            if isinstance(rendered_data, str):
                source = rendered_data
            elif isinstance(rendered_data, dict):
                for key in ("local_path", "path", "file", "filepath", "filename", "output_path", "source_path"):
                    if rendered_data.get(key):
                        source = rendered_data[key]
                        break
            if not source:
                raise ValueError("GCS sink requires a source file path")

        logger.info(f"GCS.STORAGE: Source file: {source}")

        # Resolve destination URI
        # Support both 'destination', 'uri', and 'destination_uri' fields
        destination = tool_config.get("destination") or tool_config.get("uri") or tool_config.get("destination_uri")
        if not destination:
            raise ValueError("GCS sink requires a destination GCS URI")

        logger.info(f"GCS.STORAGE: Destination URI: {destination}")

        # Resolve credential reference
        credential = tool_config.get("credential") or credential_ref
        if not credential and isinstance(auth_config, str):
            credential = auth_config
        if not credential and isinstance(auth_config, dict):
            credential = auth_config.get("credential") or auth_config.get("key")
        if not credential:
            raise ValueError("GCS sink requires a credential reference")

        logger.info(f"GCS.STORAGE: Using credential: {credential}")

        # Build task config passed to the GCS tool
        gcs_task_config: Dict[str, Any] = {
            "kind": "gcs",
            "source": source,
            "destination": destination,
            "credential": credential,
        }

        if "content_type" in tool_config:
            gcs_task_config["content_type"] = tool_config["content_type"]
        if "metadata" in tool_config:
            gcs_task_config["metadata"] = tool_config["metadata"]

        merged_task_with = {**(task_with or {}), **gcs_task_config}

        logger.info("GCS.STORAGE: Calling execute_gcs_task")
        result = execute_gcs_task(
            task_config=gcs_task_config,
            context=context,
            jinja_env=jinja_env,
            task_with=merged_task_with,
            log_event_callback=log_event_callback,
        )

        logger.info(f"GCS.STORAGE: Result: {result}")

        if not isinstance(result, dict):
            return {
                "status": "error",
                "data": None,
                "meta": {"tool_kind": "gcs", "credential_ref": credential},
                "error": "GCS tool returned non-dict result",
            }

        if result.get("status") == "error":
            return {
                "status": "error",
                "data": None,
                "meta": {"tool_kind": "gcs", "credential_ref": credential},
                "error": result.get("error") or result.get("message") or "GCS upload failed",
            }

        # Normalize success envelope
        return {
            "status": "success",
            "data": {
                "saved": "gcs",
                "uri": result.get("uri"),
                "bucket": result.get("bucket"),
                "blob": result.get("blob"),
                "size": result.get("size"),
                "content_type": result.get("content_type"),
                "task_result": result,
            },
            "meta": {
                "tool_kind": "gcs",
                "credential_ref": credential,
                "sink_spec": {
                    "source": source,
                    "destination": destination,
                },
            },
        }

    except Exception as e:
        logger.exception(f"GCS.STORAGE: Error in GCS sink handler: {e}")
        return {
            "status": "error",
            "data": None,
            "meta": {"tool_kind": "gcs", "credential_ref": credential},
            "error": str(e),
        }
