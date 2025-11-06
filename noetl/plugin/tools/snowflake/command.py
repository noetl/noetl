"""
Snowflake SQL command processing module.

Handles command decoding, rendering, and splitting for Snowflake SQL execution.
"""

import base64
from typing import List, Dict
from jinja2 import Environment

from noetl.core.logger import setup_logger
from noetl.plugin.runtime import sql_split

logger = setup_logger(__name__, include_location=True)


def decode_base64_commands(task_config: Dict) -> str:
    """
    Decode base64 encoded SQL commands from task configuration.
    
    Supports both singular (command_b64) and plural (commands_b64) field names.
    
    Args:
        task_config: Task configuration dictionary
        
    Returns:
        Decoded SQL commands string
        
    Raises:
        ValueError: If no command field is found or decoding fails
    """
    command_b64 = task_config.get('command_b64') or task_config.get('commands_b64')
    
    if not command_b64:
        raise ValueError("No 'command_b64' or 'commands_b64' field found in task config")
    
    try:
        decoded = base64.b64decode(command_b64).decode('utf-8')
        logger.debug(f"Decoded {len(decoded)} characters of SQL commands")
        return decoded
    except Exception as e:
        logger.error(f"Failed to decode base64 commands: {e}")
        raise ValueError(f"Failed to decode base64 SQL commands: {e}")


def escape_task_with_params(task_with: Dict) -> Dict:
    """
    Escape special characters in task_with parameters for SQL compatibility.
    
    This prevents SQL injection and syntax errors when parameters are used
    in SQL statements.
    
    Args:
        task_with: Task 'with' parameters dictionary
        
    Returns:
        Dictionary with escaped parameter values
    """
    escaped = {}
    for key, value in (task_with or {}).items():
        if isinstance(value, str):
            # Escape single quotes by doubling them (SQL standard)
            escaped[key] = value.replace("'", "''")
        else:
            escaped[key] = value
    return escaped


def render_and_split_commands(
    commands_str: str,
    jinja_env: Environment,
    context: Dict,
    task_with: Dict
) -> List[str]:
    """
    Render Jinja2 templates in SQL commands and split into individual statements.
    
    Args:
        commands_str: Raw SQL commands string (may contain Jinja2 templates)
        jinja_env: Jinja2 environment for rendering
        context: Execution context for template rendering
        task_with: Task 'with' parameters to merge into context
        
    Returns:
        List of individual SQL statements
    """
    # Merge context and task_with for rendering
    render_context = {**context, **(task_with or {})}
    
    # Render Jinja2 templates
    try:
        template = jinja_env.from_string(commands_str)
        rendered = template.render(render_context)
        logger.debug(f"Rendered SQL commands: {len(rendered)} characters")
    except Exception as e:
        logger.error(f"Failed to render SQL template: {e}")
        raise ValueError(f"Failed to render SQL template: {e}")
    
    # Split into individual statements
    statements = sql_split(rendered)
    
    # Filter out empty statements
    statements = [s.strip() for s in statements if s.strip()]
    
    logger.info(f"Split SQL into {len(statements)} statement(s)")
    return statements
