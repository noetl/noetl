"""
Workbook task executor.

Executes workbook tasks by looking up actions in playbook workbook section
and delegating to appropriate action executors.
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.logger import setup_logger
from .catalog import (
    fetch_playbook_from_catalog, 
    find_workbook_action,
    extract_playbook_location
)

logger = setup_logger(__name__, include_location=True)


def build_action_config(
    target_action: Dict[str, Any], 
    task_name: str,
    task_with: Optional[Dict[str, Any]] = None
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Build action configuration from workbook action definition.
    
    Args:
        target_action: Workbook action definition
        task_name: Task name for reference
        task_with: Additional parameters from 'with' clause
        
    Returns:
        Tuple of (action_config, action_with)
    """
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
    for field in [
        'code', 'command', 'commands', 'sql', 
        'url', 'method', 'endpoint', 'headers', 'params', 
        'data', 'payload', 'timeout'
    ]:
        if field in target_action:
            action_config[field] = target_action[field]
    
    return action_config, action_with


async def execute_workbook_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a workbook task by looking up the action in the workbook section.
    
    This executor:
    1. Validates task_config has 'name' attribute
    2. Extracts playbook path/version from context
    3. Fetches playbook from catalog
    4. Finds workbook action by name
    5. Builds action config and delegates to appropriate executor
    
    Args:
        task_config: Task configuration containing 'name' attribute to lookup
        context: Execution context (should contain workload with path/version)
        jinja_env: Jinja2 environment for template rendering
        task_with: Additional parameters from 'with' clause
        log_event_callback: Optional callback for logging events
        
    Returns:
        Task execution result
        
    Raises:
        ValueError: If task_name not provided, path not in context, 
                   playbook not found, or workbook action not found
    """
    task_name = task_config.get('name')
    if not task_name:
        raise ValueError("Workbook task must specify a 'name' attribute to lookup")
    
    logger.info(f"WORKBOOK: Looking up task '{task_name}' in workbook")
    
    # Step 1: Extract playbook location from context
    path, version = extract_playbook_location(context)
    
    # Step 2: Fetch playbook from catalog
    playbook = await fetch_playbook_from_catalog(path, version)
    
    # Step 3: Find the workbook action by name
    target_action = find_workbook_action(playbook, task_name)
    
    # Step 4: Build action config
    action_config, action_with = build_action_config(
        target_action, task_name, task_with
    )
    
    logger.info(
        f"WORKBOOK: Executing action '{task_name}' as type "
        f"'{target_action.get('type')}'"
    )
    logger.debug(f"WORKBOOK: Action config: {action_config}")
    logger.debug(f"WORKBOOK: Action with: {action_with}")
    
    # Step 5: Execute the actual action using the standard task executor
    # Import execute_task here to avoid circular imports
    from .. import execute_task
    
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
