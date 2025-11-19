"""
Playbook content loader.

Handles loading playbook content from path references or inline content.
"""

import os
from typing import Dict, Any, Optional
import yaml
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def get_playbook_path(task_config: Dict[str, Any]) -> Optional[str]:
    """
    Extract playbook path from task configuration.
    
    Checks multiple possible parameter names for backward compatibility.
    
    Args:
        task_config: Task configuration dictionary
        
    Returns:
        Playbook path or None if not found
    """
    return (task_config.get('resource_path') or
            task_config.get('playbook_path') or
            task_config.get('path'))


def load_playbook_from_filesystem(playbook_path: str) -> str:
    """
    Load playbook content from filesystem.
    
    Tries multiple possible file locations in priority order.
    
    Args:
        playbook_path: Path to playbook file
        
    Returns:
        Playbook YAML content as string
        
    Raises:
        FileNotFoundError: If playbook file not found in any location
    """
    logger.info(f"PLAYBOOK: Loading playbook from path: {playbook_path}")
    
    # Check common playbook file locations
    possible_paths = [
        f"./examples/{playbook_path.replace('examples/', '')}.yaml",
        f"./{playbook_path}.yaml",
        f"{playbook_path}.yaml",
        playbook_path
    ]
    
    for file_path in possible_paths:
        if os.path.exists(file_path):
            logger.debug(f"PLAYBOOK: Found playbook file at: {file_path}")
            with open(file_path, 'r') as f:
                playbook_data = yaml.safe_load(f)
                return yaml.dump(playbook_data)
    
    # File not found in any location
    raise FileNotFoundError(
        f"Playbook file not found at any of: {possible_paths}"
    )


def create_placeholder_playbook(playbook_path: str) -> str:
    """
    Create a minimal placeholder playbook reference.
    
    This allows the broker to handle playbook resolution when the file
    is not found locally.
    
    Args:
        playbook_path: Path reference for the playbook
        
    Returns:
        Minimal playbook YAML content
    """
    logger.debug(
        f"PLAYBOOK: Playbook file not found locally, using path reference"
    )
    
    return f"""
apiVersion: noetl.io/v1
kind: Playbook
name: {playbook_path.split('/')[-1]}
path: {playbook_path}
workload: {{}}
workflow:
  - step: start
    desc: "Placeholder for path-referenced playbook"
    next:
      - step: end
  - step: end
    desc: "End"
"""


def load_playbook_content(
    task_config: Dict[str, Any],
    task_id: str
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Load playbook content from task configuration.
    
    Handles both inline content and path-based references.
    
    Args:
        task_config: Task configuration dictionary
        task_id: Task ID for error reporting
        
    Returns:
        Tuple of (playbook_path, playbook_content, error_message)
        Returns (path, content, None) on success, (None, None, error) on failure
    """
    playbook_path = get_playbook_path(task_config)
    playbook_content = (task_config.get('content') or
                       task_config.get('playbook_content'))
    
    logger.debug(f"PLAYBOOK: Extracted playbook_path: {playbook_path}")
    logger.debug(f"PLAYBOOK: Extracted playbook_content: {playbook_content is not None}")
    
    # If neither path nor content provided, check for task reference
    if not playbook_path and not playbook_content:
        task_path = task_config.get('path')
        if task_path:
            playbook_path = task_path
            logger.debug(f"PLAYBOOK: Using path parameter: {playbook_path}")
        else:
            # Check if this should be a workbook task instead
            task_ref = task_config.get('task')
            if task_ref:
                error_msg = (
                    f"Playbook task requires 'resource_path' or 'path' parameter "
                    f"to reference another playbook. If you want to execute a task "
                    f"from the workbook, use type 'workbook' instead of 'playbook'. "
                    f"Available parameters: {list(task_config.keys())}"
                )
            else:
                error_msg = (
                    f"Playbook task requires 'resource_path', 'path', or 'content' "
                    f"parameter. Available parameters: {list(task_config.keys())}"
                )
            logger.error(f"PLAYBOOK: {error_msg}")
            return None, None, error_msg
    
    # If we have a path but no content, try to load the content
    if playbook_path and not playbook_content:
        try:
            playbook_content = load_playbook_from_filesystem(playbook_path)
        except FileNotFoundError:
            # Create placeholder for broker resolution
            playbook_content = create_placeholder_playbook(playbook_path)
        except Exception as e:
            error_msg = f"Failed to load playbook from path {playbook_path}: {str(e)}"
            logger.error(f"PLAYBOOK: {error_msg}")
            return None, None, error_msg
    
    return playbook_path, playbook_content, None


def render_playbook_content(
    playbook_content: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    task_id: str
) -> tuple[Optional[str], Optional[str]]:
    """
    Render playbook content with Jinja2 templating.
    
    Args:
        playbook_content: Raw playbook YAML content
        context: Execution context for rendering
        jinja_env: Jinja2 environment
        task_id: Task ID for error reporting
        
    Returns:
        Tuple of (rendered_content, error_message)
        Returns (content, None) on success, (None, error) on failure
    """
    if not playbook_content:
        return "", None
    
    try:
        rendered_content = render_template(jinja_env, playbook_content, context)
        logger.debug("PLAYBOOK: Rendered playbook content")
        return rendered_content, None
    except Exception as e:
        error_msg = f"Failed to render playbook content: {str(e)}"
        logger.error(f"PLAYBOOK: {error_msg}")
        return None, error_msg
