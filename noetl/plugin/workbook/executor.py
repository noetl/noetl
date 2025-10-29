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
    args: Optional[Dict[str, Any]] = None
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Build action configuration from workbook action definition.
    
    Args:
        target_action: Workbook action definition
        task_name: Task name for reference
        args: Additional arguments from step
        
    Returns:
        Tuple of (action_config, action_args)
    """
    # Merge step args into the action's args
    action_args = target_action.get('args', {}).copy()
    if args:
        action_args.update(args)
    
    logger.info(f"WORKBOOK.BUILD_CONFIG: action_args from workbook = {target_action.get('args', {})}")
    logger.info(f"WORKBOOK.BUILD_CONFIG: args from step = {args}")
    logger.info(f"WORKBOOK.BUILD_CONFIG: action_args after merge = {action_args}")
    
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
    
    return action_config, action_args


async def execute_workbook_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]] = None,
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
        args: Additional arguments from step
        log_event_callback: Optional callback for logging events
        
    Returns:
        Task execution result
        
    Raises:
        ValueError: If task_name not provided, path not in context, 
                   playbook not found, or workbook action not found
    """
    # Prefer explicit 'task' reference to workbook action; fall back to 'name' for legacy compatibility
    task_name = task_config.get('task') or task_config.get('name')
    if not task_name:
        raise ValueError("Workbook task must specify a 'task' (or legacy 'name') attribute to lookup")
    
    logger.info(f"WORKBOOK: Looking up task '{task_name}' in workbook")
    
    # Step 1: Extract playbook location from context
    path, version = extract_playbook_location(context)
    
    # Step 2: Fetch playbook from catalog
    playbook = await fetch_playbook_from_catalog(path, version)
    
    # Step 3: Find the workbook action by name
    target_action = find_workbook_action(playbook, task_name)
    
    # Step 4: Build action config
    action_config, action_args = build_action_config(
        target_action, task_name, args
    )
    
    logger.info(
        f"WORKBOOK: Executing action '{task_name}' as type "
        f"'{target_action.get('type')}'"
    )
    logger.debug(f"WORKBOOK: Action config: {action_config}")
    logger.debug(f"WORKBOOK: Action args: {action_args}")
    
    # Step 5: Execute the actual action using the standard task executor
    # Import execute_task here to avoid circular imports
    from .. import execute_task
    
    result = execute_task(
        action_config,
        task_name,
        context,
        jinja_env,
        action_args,
        log_event_callback
    )
    
    logger.info(f"WORKBOOK: Action '{task_name}' completed successfully")
    return result
