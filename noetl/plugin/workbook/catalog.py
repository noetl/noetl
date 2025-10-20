"""
Catalog operations for workbook plugin.

Handles fetching playbooks from catalog and finding workbook actions by name.
"""

from typing import Dict, Any, List, Optional
import yaml

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def fetch_playbook_from_catalog(path: str, version: str = 'latest') -> Dict[str, Any]:
    """
    Fetch playbook from catalog service.
    
    Args:
        path: Playbook path in catalog
        version: Playbook version (default: 'latest')
        
    Returns:
        Parsed playbook dictionary
        
    Raises:
        ValueError: If playbook not found or cannot be parsed
    """
    logger.info(f"WORKBOOK: Fetching playbook from catalog: {path} v{version}")
    
    # Import catalog service here to avoid circular imports
    from noetl.server.api.catalog import get_catalog_service
    
    # Fetch playbook from catalog
    catalog = get_catalog_service()
    entry = await catalog.fetch_entry(path, version)
    
    if not entry or not entry.get('content'):
        raise ValueError(f"Could not fetch playbook content for {path} v{version}")
    
    # Parse playbook content
    try:
        playbook = yaml.safe_load(entry['content'])
    except Exception as e:
        raise ValueError(f"Failed to parse playbook YAML: {e}")
    
    return playbook


def find_workbook_action(playbook: Dict[str, Any], task_name: str) -> Dict[str, Any]:
    """
    Find a workbook action by name in playbook.
    
    Args:
        playbook: Parsed playbook dictionary
        task_name: Name of workbook action to find
        
    Returns:
        Workbook action configuration
        
    Raises:
        ValueError: If action not found
    """
    logger.info(f"WORKBOOK: Looking for action '{task_name}' in workbook")
    
    workbook_actions = playbook.get('workbook', [])
    target_action = None
    
    for action in workbook_actions:
        if action.get('name') == task_name:
            target_action = action
            break
    
    if not target_action:
        available_actions = [a.get('name') for a in workbook_actions]
        raise ValueError(
            f"Workbook action '{task_name}' not found. "
            f"Available actions: {available_actions}"
        )
    
    logger.info(f"WORKBOOK: Found action '{task_name}' with type '{target_action.get('type')}'")
    return target_action


def extract_playbook_location(context: Dict[str, Any]) -> tuple[Optional[str], str]:
    """
    Extract playbook path and version from execution context.
    
    First tries to fetch from workload table using execution_id if available,
    then falls back to context data structures.
    
    Args:
        context: Execution context
        
    Returns:
        Tuple of (path, version)
        
    Raises:
        ValueError: If path not found in context
    """
    # Try to get execution_id and fetch from workload table first
    execution_id = context.get('execution_id')
    if execution_id:
        try:
            import asyncio
            from noetl.core.common import get_async_db_connection
            
            async def _fetch_workload_path(exec_id):
                try:
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                "SELECT data FROM noetl.workload WHERE execution_id = %s",
                                (str(exec_id),)
                            )
                            row = await cur.fetchone()
                            if row and row[0]:
                                import json
                                data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                                return data.get('path'), data.get('version')
                except Exception as e:
                    logger.debug(f"WORKBOOK: Failed to fetch workload from DB: {e}")
                return None, None
            
            # Try to run the async function
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, but execute_task is sync
                # Create a new event loop in a thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _fetch_workload_path(execution_id))
                    db_path, db_version = future.result(timeout=2)
                    if db_path:
                        logger.info(f"WORKBOOK: Fetched path={db_path}, version={db_version} from workload table for execution={execution_id}")
                        return db_path, db_version or 'latest'
            except RuntimeError:
                # No running loop
                db_path, db_version = asyncio.run(_fetch_workload_path(execution_id))
                if db_path:
                    logger.info(f"WORKBOOK: Fetched path={db_path}, version={db_version} from workload table for execution={execution_id}")
                    return db_path, db_version or 'latest'
        except Exception as e:
            logger.debug(f"WORKBOOK: Could not fetch from workload table: {e}")
    
    # Fall back to context-based extraction
    # Context can come in various shapes. Prefer 'work' wrapper if present 
    # (as emitted by worker events), then fall back to top-level and nested 
    # 'workload' keys.
    work_ctx = context.get('work') or {}
    workload = work_ctx.get('workload') or context.get('workload') or {}
    
    path = (work_ctx.get('path') or 
            context.get('path') or 
            workload.get('path'))
    
    version = (work_ctx.get('version') or 
               context.get('version') or 
               workload.get('version') or 
               'latest')
    
    if not path:
        raise ValueError("Workbook task requires 'path' in context to locate playbook")
    
    logger.info(f"WORKBOOK: Extracted path={path}, version={version} from context")
    return path, version
