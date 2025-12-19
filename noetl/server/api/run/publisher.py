"""
Queue publisher module for execution tasks.

Publishes actionable tasks to queue table for worker pools to consume.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row

from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def encode_task_for_queue(task_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply base64 encoding to multiline code in task configuration.
    
    IMPORTANT: command/commands fields are NOT encoded here because they contain
    Jinja2 templates that must be rendered by the worker with full execution context
    (including results from previous steps). The rendering happens via /context/render
    endpoint before task execution. The postgres/duckdb executors accept inline 'command'
    field directly without base64 encoding.

    Args:
        task_config: The original task configuration

    Returns:
        Modified task configuration with code_b64 field (if code present), command/commands unchanged
    """
    if not isinstance(task_config, dict):
        return task_config

    encoded_task = dict(task_config)

    try:
        # Encode Python code and remove original
        code_val = encoded_task.get("code")
        if isinstance(code_val, str) and code_val.strip():
            encoded_task["code_b64"] = base64.b64encode(
                code_val.encode("utf-8")
            ).decode("ascii")
            # Remove original to ensure only base64 is used
            encoded_task.pop("code", None)

        # DO NOT encode command/commands - they need to be rendered with Jinja2 first
        # The postgres/duckdb executors support inline 'command' field without base64 encoding

    except Exception:
        logger.debug("Failed to encode task fields", exc_info=True)

    return encoded_task


async def expand_workbook_reference(
    step_config: Dict[str, Any], catalog_id: str
) -> Dict[str, Any]:
    """
    Expand workbook action references by fetching the actual action definition from the playbook.

    If step_config has tool='workbook', this function:
    1. Fetches the playbook from catalog
    2. Looks up the action by name in the workbook section
    3. Merges the action definition into step_config
    4. Preserves step-level overrides (args, data)

    Args:
        step_config: Step configuration (tool='workbook' and name='action_name')
        catalog_id: Catalog entry ID to fetch playbook from

    Returns:
        Expanded step configuration with workbook action merged in
    """
    # Only expand if type is 'workbook'
    if not isinstance(step_config, dict):
        return step_config

    tool_raw = step_config.get("tool", "")
    # Handle both string tool names and dict tool definitions
    if isinstance(tool_raw, dict):
        step_tool = (tool_raw.get("kind") or tool_raw.get("type") or "").lower()
    else:
        step_tool = tool_raw.lower() if isinstance(tool_raw, str) else str(tool_raw).lower()
    
    if step_tool != "workbook":
        return step_config

    workbook_action_name = step_config.get("name")
    if not workbook_action_name:
        logger.warning("Workbook step missing 'name' attribute, cannot expand")
        return step_config

    try:
        # Lazy import to avoid circular dependency
        import yaml

        from noetl.server.api.catalog.service import CatalogService

        # Fetch playbook from catalog
        catalog_entry = await CatalogService.fetch_entry(catalog_id=catalog_id)
        if not catalog_entry or not catalog_entry.content:
            logger.warning(f"No playbook content found for catalog_id {catalog_id}")
            return step_config

        playbook = yaml.safe_load(catalog_entry.content)

        # Find the workbook action in the playbook's workbook section
        workbook_actions = playbook.get("workbook", [])
        workbook_action = None
        for action in workbook_actions:
            if action.get("name") == workbook_action_name:
                workbook_action = dict(action)
                break

        if not workbook_action:
            logger.warning(
                f"Workbook action '{workbook_action_name}' not found in playbook"
            )
            return step_config

        # Preserve step-level overrides
        step_args = step_config.get("args", {})
        step_data = step_config.get("data", {})

        # Merge workbook action into step config
        expanded_config = dict(workbook_action)
        tool_name = expanded_config.get("tool")
        if not tool_name:
            raise ValueError(
                f"Workbook action '{workbook_action_name}' must define a 'tool'"
            )

        # Ensure legacy 'type' field is cleared
        expanded_config.pop("type", None)

        # Restore step-level overrides (they take precedence)
        if step_args:
            if "args" not in expanded_config:
                expanded_config["args"] = {}
            expanded_config["args"].update(step_args)
        if step_data:
            if "data" not in expanded_config:
                expanded_config["data"] = {}
            expanded_config["data"].update(step_data)

        # Preserve other step-level fields that aren't in the workbook action
        for key in ["desc", "next", "step"]:
            if key in step_config and key not in expanded_config:
                expanded_config[key] = step_config[key]

        logger.info(
            f"Expanded workbook action '{workbook_action_name}' to tool '{expanded_config['tool']}'"
        )
        return expanded_config

    except Exception:
        logger.exception(f"Failed to expand workbook action '{workbook_action_name}'")
        return step_config


class QueuePublisher:
    """Compatibility shim after queue removal."""

    @staticmethod
    async def publish_initial_steps(
        execution_id: str,
        catalog_id: str,
        initial_steps: List[str],
        workflow_steps: List[Dict[str, Any]],
        parent_event_id: str,
        context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent_execution_id: Optional[str] = None,
    ) -> List[str]:
        # Queue subsystem is removed; nothing to enqueue here.
        logger.info(
            "QueuePublisher.publish_initial_steps invoked but queue subsystem is removed; returning empty list"
        )
        return []

    @staticmethod
    async def publish_step(
        execution_id: str,
        catalog_id: str,
        step_name: str,
        step_config: Dict[str, Any],
        step_type: str,
        parent_event_id: str,
        context: Optional[Dict[str, Any]] = None,
        priority: int = 50,
        delay_seconds: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        # Generate a synthetic identifier to maintain API compatibility.
        queue_id = await get_snowflake_id()
        logger.info(
            "QueuePublisher.publish_step invoked but queue subsystem is removed; returning synthetic id"
        )
        return str(queue_id)
