"""
Template rendering and SQL preprocessing for DuckDB commands.
"""

from typing import Union, List, Any, Dict

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger

from ..types import JinjaEnvironment, ContextDict
from ..errors import SQLExecutionError

logger = setup_logger(__name__, include_location=True)


def render_deep(jenv: JinjaEnvironment, ctx: ContextDict, obj: Any) -> Any:
    """
    Deep Jinja2 rendering of nested data structures.
    
    Args:
        jenv: Jinja2 environment (can be None)
        ctx: Context dictionary for rendering
        obj: Object to render recursively
        
    Returns:
        Rendered object with templates resolved
    """
    if jenv is None: 
        return obj
        
    if isinstance(obj, str):
        return jenv.from_string(obj).render(ctx or {})
    elif isinstance(obj, dict):
        return {k: render_deep(jenv, ctx, v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return type(obj)(render_deep(jenv, ctx, v) for v in obj)
    else:
        return obj


def render_commands(
    commands: Union[str, List[str]], 
    jinja_env: JinjaEnvironment, 
    context: ContextDict
) -> List[str]:
    """
    Render SQL commands using Jinja2 templates.
    
    Args:
        commands: Raw commands string or list
        jinja_env: Jinja2 environment for rendering
        context: Template context
        
    Returns:
        List of rendered SQL command strings
        
    Raises:
        SQLExecutionError: If rendering fails
    """
    try:
        if isinstance(commands, str):
            # Render the entire commands string first
            commands_rendered = render_template(jinja_env, commands, context)
            logger.info(f"Commands rendered (first 400 chars): {commands_rendered[:400]}")
            
            # Clean and split into individual commands
            return clean_sql_text(commands_rendered)
        else:
            # Render each command individually
            return [render_template(jinja_env, cmd, context) for cmd in commands]
            
    except Exception as e:
        raise SQLExecutionError(f"Failed to render SQL commands: {e}")


def clean_sql_text(sql_text: str) -> List[str]:
    """
    Clean SQL text by removing comments and splitting into commands.
    
    Args:
        sql_text: Raw SQL text
        
    Returns:
        List of cleaned SQL commands
    """
    cmd_lines = []
    
    for line in sql_text.split('\n'):
        s = line.strip()
        # Skip common SQL comment line prefixes (DuckDB supports -- and /* ... */)
        if not s:
            continue
        if s.startswith('--') or s.startswith('#'):
            continue
        cmd_lines.append(s)
    
    commands_text = ' '.join(cmd_lines)
    
    # Import sql_split from action module
    from ...action import sql_split
    return sql_split(commands_text)


def escape_sql(s: Any) -> str:
    """
    Escape single quotes in SQL string literals.
    
    Args:
        s: Value to escape
        
    Returns:
        SQL-escaped string
    """
    return str(s or "").replace("'", "''")