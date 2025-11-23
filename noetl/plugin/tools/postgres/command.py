"""
PostgreSQL command parsing and SQL statement splitting.

This module handles:
- Base64 command decoding
- Jinja2 template rendering
- SQL statement parsing with quote awareness
- Multi-statement splitting
"""

import base64
from typing import List, Dict
from jinja2 import Environment
from noetl.core.logger import setup_logger
from noetl.core.dsl.render import render_template

logger = setup_logger(__name__, include_location=True)


def escape_task_with_params(task_with: Dict) -> Dict:
    """
    Escape special characters in task_with parameters for SQL compatibility.
    
    Args:
        task_with: The task 'with' parameters dictionary
        
    Returns:
        Dictionary with escaped string values
    """
    processed_task_with = task_with.copy()
    for key, value in task_with.items():
        if isinstance(value, str):
            processed_value = value.replace('<', '\\<').replace('>', '\\>')
            processed_value = processed_value.replace("'", "''")
            processed_task_with[key] = processed_value
            if value != processed_value:
                logger.debug(f"Escaped special characters in {key} for SQL compatibility")
        else:
            # Keep non-string values as-is (integers, booleans, etc.)
            processed_task_with[key] = value
    return processed_task_with


def decode_base64_commands(task_config: Dict, context: Dict = None, jinja_env: Environment = None) -> str:
    """
    Decode SQL commands from task configuration with priority: script > command_b64 > command.
    
    Args:
        task_config: The task configuration
        context: Execution context (for script resolution)
        jinja_env: Jinja2 environment (for script resolution)
        
    Returns:
        Decoded SQL commands string
        
    Raises:
        ValueError: If no command fields found or decoding fails
    """
    # Priority 1: External script
    if 'script' in task_config:
        from noetl.plugin.shared.script import resolve_script
        logger.debug(f"POSTGRES: Resolving external script")
        if not context or not jinja_env:
            raise ValueError("Context and jinja_env are required for script resolution")
        commands = resolve_script(task_config['script'], context, jinja_env)
        logger.debug(f"POSTGRES: Resolved script from {task_config['script']['source']['type']}, length={len(commands)} chars")
        return commands
    
    # Priority 2: Base64 encoded command
    command_b64 = task_config.get('command_b64', '')
    commands_b64 = task_config.get('commands_b64', '')
    
    commands = ''
    if command_b64:
        try:
            commands = base64.b64decode(command_b64.encode('ascii')).decode('utf-8')
            logger.debug(f"POSTGRES: Decoded base64 command, length={len(commands)} chars")
        except Exception as e:
            logger.error(f"POSTGRES: Failed to decode base64 command: {e}")
            raise ValueError(f"Invalid base64 command encoding: {e}")
    elif commands_b64:
        try:
            commands = base64.b64decode(commands_b64.encode('ascii')).decode('utf-8')
            logger.debug(f"POSTGRES: Decoded base64 commands, length={len(commands)} chars")
        except Exception as e:
            logger.error(f"POSTGRES: Failed to decode base64 commands: {e}")
            raise ValueError(f"Invalid base64 commands encoding: {e}")
    
    # Priority 3: Inline command (fallback for direct usage)
    elif 'command' in task_config:
        commands = task_config['command']
        logger.debug(f"POSTGRES: Using inline command, length={len(commands)} chars")
    
    else:
        raise ValueError("No SQL command provided. Expected 'script', 'command_b64', 'commands_b64', or 'command'")
    
    return commands


def render_and_split_commands(commands: str, jinja_env: Environment, context: Dict, task_with: Dict) -> List[str]:
    """
    Render SQL commands with Jinja2 and split into individual statements.
    
    This function:
    1. Renders the commands string with Jinja2 templates
    2. Removes comment-only lines
    3. Splits commands on semicolons while respecting:
       - Single quotes (')
       - Double quotes (")
       - Dollar-quoted strings ($tag$...$tag$)
    
    Args:
        commands: The SQL commands string (may contain Jinja2 templates)
        jinja_env: The Jinja2 environment for template rendering
        context: The context for rendering templates
        task_with: The rendered 'with' parameters dictionary
        
    Returns:
        List of individual SQL statement strings
    """
    logger.debug(f"POSTGRES: Rendering commands with context keys: {list(context.keys()) if isinstance(context, dict) else type(context)}")
    if isinstance(context, dict) and 'result' in context:
        result_val = context['result']
        logger.debug(f"POSTGRES: Found 'result' in context - type: {type(result_val)}, keys: {list(result_val.keys()) if isinstance(result_val, dict) else 'not dict'}")
    else:
        logger.debug("POSTGRES: No 'result' found in context")
    
    # Render commands with combined context
    commands_rendered = render_template(jinja_env, commands, {**context, **task_with})
    
    # Remove comment-only lines and squash whitespace
    cmd_lines = []
    for line in commands_rendered.split('\n'):
        s = line.strip()
        if s and not s.startswith('--'):
            cmd_lines.append(s)
    commands_text = ' '.join(cmd_lines)

    # Split on semicolons, respecting single/double quotes and dollar-quoted strings
    statements = []
    current = []
    in_single = False
    in_double = False
    dollar_quote = False
    dollar_tag = ""
    i = 0
    n = len(commands_text)
    
    while i < n:
        ch = commands_text[i]
        
        # Handle dollar-quoted strings when not inside standard quotes
        if not in_single and not in_double and ch == '$':
            j = i + 1
            while j < n and (commands_text[j].isalnum() or commands_text[j] in ['_', '$']):
                j += 1
            tag = commands_text[i:j]
            if dollar_quote and tag == dollar_tag:
                dollar_quote = False
                dollar_tag = ""
            elif not dollar_quote and tag.startswith('$') and tag.endswith('$'):
                dollar_quote = True
                dollar_tag = tag
            current.append(commands_text[i:j])
            i = j
            continue
        
        # Toggle single/double quotes (ignore when in dollar-quote)
        if not dollar_quote and ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue
        if not dollar_quote and ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue
        
        # Statement split
        if ch == ';' and not in_single and not in_double and not dollar_quote:
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue
        
        current.append(ch)
        i += 1
    
    # Add final statement if exists
    stmt = ''.join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements
