"""
Workbook execution plugin for NoETL.

This plugin handles 'workbook' type tasks which look up actions
by name in the workbook section of a playbook and execute them.
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def execute_workbook_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a workbook task by looking up the action in the workbook section.
    
    Args:
        task_config: Task configuration containing 'task' name to lookup
        context: Execution context (should contain workload with path/version)
        jinja_env: Jinja2 environment for template rendering
        task_with: Additional parameters from 'with' clause
        log_event_callback: Optional callback for logging events
        
    Returns:
        Task execution result
    """
    task_name = task_config.get('task')
    if not task_name:
        raise ValueError("Workbook task must specify a 'task' name to lookup")
    
    logger.info(f"WORKBOOK: Looking up task '{task_name}' in workbook")
    
    # Get playbook path and version from context
    # Context can come in various shapes. Prefer 'work' wrapper if present (as emitted by worker events),
    # then fall back to top-level and to nested 'workload' keys.
    work_ctx = context.get('work') or {}
    workload = work_ctx.get('workload') or context.get('workload') or {}
    path = work_ctx.get('path') or context.get('path') or workload.get('path')
    version = work_ctx.get('version') or context.get('version') or workload.get('version') or 'latest'
    
    if not path:
        raise ValueError("Workbook task requires 'path' in context to locate playbook")
    
    logger.info(f"WORKBOOK: Fetching playbook from catalog: {path} v{version}")
    
    # Import catalog service here to avoid circular imports
    from noetl.server.api.catalog import get_catalog_service
    
    # Fetch playbook from catalog
    catalog = get_catalog_service()
    entry = await catalog.fetch_entry(path, version)
    
    if not entry or not entry.get('content'):
        raise ValueError(f"Could not fetch playbook content for {path} v{version}")
    
    # Parse playbook content
    import yaml
    try:
        playbook = yaml.safe_load(entry['content'])
    except Exception as e:
        raise ValueError(f"Failed to parse playbook YAML: {e}")
    
    # Find the workbook action by name
    workbook_actions = playbook.get('workbook', [])
    target_action = None
    
    for action in workbook_actions:
        if action.get('name') == task_name:
            target_action = action
            break
    
    if not target_action:
        available_actions = [a.get('name') for a in workbook_actions]
        raise ValueError(f"Workbook action '{task_name}' not found. Available actions: {available_actions}")
    
    logger.info(f"WORKBOOK: Found action '{task_name}' with type '{target_action.get('type')}'")
    
    # Merge task_with into the action's 'with' parameters
    action_with = target_action.get('with', {}).copy()
    if task_with:
        action_with.update(task_with)
    
    # Create task config for the actual action type
    action_config = {
        'type': target_action.get('type'),
        'name': task_name,
    }
    
    # Copy relevant fields from the action to the config
    for field in ['code', 'command', 'commands', 'sql', 'url', 'method', 'endpoint', 'headers', 'params', 'data', 'payload', 'timeout']:
        if field in target_action:
            action_config[field] = target_action[field]
    
    logger.info(f"WORKBOOK: Executing action '{task_name}' as type '{target_action.get('type')}'")
    logger.debug(f"WORKBOOK: Action config: {action_config}")
    logger.debug(f"WORKBOOK: Action with: {action_with}")
    
    # Import execute_task here to avoid circular imports
    from . import execute_task
    
    # Execute the actual action using the standard task executor
    result = execute_task(
        action_config,
        task_name,
        context,
        jinja_env,
        action_with,
        log_event_callback
    )
    
    logger.info(f"WORKBOOK: Action '{task_name}' completed successfully")
    return result
