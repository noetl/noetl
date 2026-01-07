"""DuckLake configuration creation and validation."""

from typing import Dict, Any, List
from noetl.tools.ducklake.types import DuckLakeConfig, JinjaEnvironment, ContextDict
from noetl.tools.ducklake.errors import DuckLakePluginError
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def create_ducklake_config(
    task_config: Dict[str, Any],
    context: ContextDict,
    jinja_env: JinjaEnvironment,
    task_with: Dict[str, Any] = None
) -> DuckLakeConfig:
    """
    Create and validate DuckLake configuration from task config.
    
    Args:
        task_config: Task configuration dictionary
        context: Context for template rendering
        jinja_env: Jinja2 environment
        task_with: Task with block containing auth credentials
        
    Returns:
        DuckLakeConfig object
        
    Raises:
        DuckLakePluginError: If configuration is invalid
    """
    try:
        # Get catalog connection string from auth or explicit config
        catalog_connection = _resolve_catalog_connection(task_config, task_with, jinja_env, context)
        if not catalog_connection:
            raise DuckLakePluginError(
                "catalog_connection is required. Provide either:\n"
                "  - auth: credential reference (resolved to Postgres connection string)\n"
                "  - catalog_connection: explicit Postgres connection string"
            )
        
        catalog_name = task_config.get("catalog_name")
        if not catalog_name:
            raise DuckLakePluginError("catalog_name is required")
        
        data_path = task_config.get("data_path")
        if not data_path:
            raise DuckLakePluginError("data_path is required (e.g., '/opt/noetl/data/ducklake')")
        
        # Get commands
        commands = _extract_commands(task_config)
        if not commands:
            raise DuckLakePluginError("At least one command is required (use 'command' or 'commands')")
        
        # Optional settings
        create_catalog = task_config.get("create_catalog", True)
        use_catalog = task_config.get("use_catalog", True)
        memory_limit = task_config.get("memory_limit")
        threads = task_config.get("threads")
        
        return DuckLakeConfig(
            catalog_connection=catalog_connection,
            catalog_name=catalog_name,
            data_path=data_path,
            commands=commands,
            create_catalog=create_catalog,
            use_catalog=use_catalog,
            memory_limit=memory_limit,
            threads=threads
        )
        
    except Exception as e:
        raise DuckLakePluginError(f"Failed to create DuckLake configuration: {e}")


def _resolve_catalog_connection(task_config: Dict[str, Any], task_with: Dict[str, Any], jinja_env: JinjaEnvironment, context: ContextDict) -> str:
    """
    Resolve catalog connection string from auth credentials or explicit config.
    
    Priority:
    1. Explicit catalog_connection in task_config
    2. Auth credential resolved to Postgres connection string
    
    Args:
        task_config: Task configuration
        task_with: Task with block containing auth reference
        jinja_env: Jinja2 environment for rendering
        context: Context for rendering
        
    Returns:
        PostgreSQL connection string for DuckLake catalog
    """
    # Check for explicit catalog_connection
    if "catalog_connection" in task_config:
        return task_config["catalog_connection"]
    
    # Try to resolve from auth credentials using the unified auth system
    if task_with and "auth" in task_with:
        try:
            from noetl.worker.auth_resolver import resolve_auth
            
            auth_config = task_with.get("auth")
            if auth_config:
                logger.debug(f"DUCKLAKE: Resolving auth credential: {auth_config}")
                mode, resolved_items = resolve_auth(auth_config, jinja_env, context)
                
                # Get first resolved item (DuckLake uses single auth)
                if resolved_items:
                    resolved_auth = list(resolved_items.values())[0]
                    logger.debug(f"DUCKLAKE: Resolved auth service='{resolved_auth.service}', keys={list(resolved_auth.payload.keys()) if resolved_auth.payload else []}")
                    
                    if resolved_auth.service == 'postgres':
                        auth_data = resolved_auth.payload
                        
                        # Build connection string from resolved auth
                        host = auth_data.get("host") or auth_data.get("db_host", "localhost")
                        port = auth_data.get("port") or auth_data.get("db_port", 5432)
                        database = auth_data.get("database") or auth_data.get("db_name", "ducklake_catalog")
                        user = auth_data.get("user") or auth_data.get("db_user", "noetl")
                        password = auth_data.get("password") or auth_data.get("db_password", "")
                        
                        if password:
                            conn_str = f"postgresql://{user}:{password}@{host}:{port}/{database}"
                        else:
                            conn_str = f"postgresql://{user}@{host}:{port}/{database}"
                        
                        logger.info(f"DUCKLAKE: Built connection string for {database} at {host}:{port}")
                        return conn_str
                    else:
                        logger.warning(f"DUCKLAKE: Expected 'postgres' service, got '{resolved_auth.service}'")
        except Exception as e:
            logger.error(f"DUCKLAKE: Failed to resolve auth: {e}", exc_info=True)
    
    return None


def _extract_commands(task_config: Dict[str, Any]) -> List[str]:
    """Extract SQL commands from task configuration."""
    commands = []
    
    # Single command
    if "command" in task_config:
        cmd = task_config["command"]
        if isinstance(cmd, str):
            commands.append(cmd)
        else:
            raise DuckLakePluginError(f"command must be a string, got {type(cmd)}")
    
    # Multiple commands
    if "commands" in task_config:
        cmds = task_config["commands"]
        if isinstance(cmds, list):
            commands.extend([str(c) for c in cmds])
        else:
            raise DuckLakePluginError(f"commands must be a list, got {type(cmds)}")
    
    return commands
