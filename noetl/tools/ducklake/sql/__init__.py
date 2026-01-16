"""SQL command rendering and execution for DuckLake."""

from typing import List, Dict, Any, Optional
from decimal import Decimal
from datetime import datetime, date, time
from noetl.tools.ducklake.types import DuckLakeConfig, JinjaEnvironment, ContextDict, LogEventCallback
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def render_commands(
    config: DuckLakeConfig,
    context: ContextDict,
    jinja_env: JinjaEnvironment
) -> List[str]:
    """
    Render SQL commands using Jinja2 templates.
    
    Args:
        config: DuckLake configuration
        context: Context for template rendering
        jinja_env: Jinja2 environment
        
    Returns:
        List of rendered SQL commands
    """
    rendered = []
    
    for cmd in config.commands:
        if not cmd or not cmd.strip():
            continue
            
        try:
            template = jinja_env.from_string(cmd)
            rendered_cmd = template.render(context)
            rendered.append(rendered_cmd)
            logger.debug(f"Rendered command: {rendered_cmd[:100]}...")
        except Exception as e:
            logger.error(f"Failed to render command: {e}")
            raise
    
    return rendered


def execute_sql_commands(
    conn: Any,
    commands: List[str],
    log_event_callback: LogEventCallback = None
) -> List[Dict[str, Any]]:
    """
    Execute SQL commands and return results.
    
    Args:
        conn: DuckDB connection
        commands: List of SQL commands to execute
        log_event_callback: Optional callback for logging events
        
    Returns:
        List of result dictionaries, one per command
    """
    results = []
    
    for idx, cmd in enumerate(commands):
        try:
            logger.debug(f"Executing command {idx + 1}/{len(commands)}")
            
            if log_event_callback:
                log_event_callback("command.start", f"Executing command {idx + 1}")
            
            # Execute command
            result = conn.execute(cmd)
            
            # Fetch results if it's a SELECT query
            if cmd.strip().upper().startswith("SELECT") or cmd.strip().upper().startswith("FROM"):
                rows = result.fetchall()
                columns = [desc[0] for desc in result.description] if result.description else []
                
                # Serialize rows to handle datetime and Decimal objects
                serialized_rows = []
                for row in rows:
                    row_dict = {}
                    for col_name, value in zip(columns, row):
                        # Convert Decimal to float for JSON serialization
                        if isinstance(value, Decimal):
                            row_dict[col_name] = float(value)
                        # Convert datetime objects to ISO format strings for JSON serialization
                        elif isinstance(value, (datetime, date, time)):
                            row_dict[col_name] = value.isoformat()
                        else:
                            row_dict[col_name] = value
                    serialized_rows.append(row_dict)
                
                results.append({
                    "command_index": idx,
                    "row_count": len(rows),
                    "columns": columns,
                    "rows": serialized_rows
                })
                logger.debug(f"Command {idx + 1} returned {len(rows)} rows")
            else:
                # DML command (INSERT, UPDATE, DELETE, etc.)
                results.append({
                    "command_index": idx,
                    "affected_rows": result.rowcount if hasattr(result, 'rowcount') else 0,
                    "status": "executed"
                })
                logger.debug(f"Command {idx + 1} executed successfully")
            
            if log_event_callback:
                log_event_callback("command.complete", f"Command {idx + 1} completed")
                
        except Exception as e:
            error_msg = f"Command {idx + 1} failed: {str(e)}"
            logger.error(error_msg)
            
            if log_event_callback:
                log_event_callback("command.error", error_msg)
            
            results.append({
                "command_index": idx,
                "status": "error",
                "error": str(e)
            })
            
            # Continue to next command instead of failing completely
            continue
    
    return results


def serialize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Serialize results for JSON response.
    
    Args:
        results: List of command execution results
        
    Returns:
        Dictionary with serialized results
    """
    return {
        "command_count": len(results),
        "commands": results
    }
