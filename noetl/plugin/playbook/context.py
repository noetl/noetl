"""
Playbook execution context management.

Handles building nested execution context and parent tracking for sub-playbooks.
"""

from typing import Dict, Any, Optional

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def build_nested_context(
    context: Dict[str, Any],
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build execution context for nested playbook.
    
    Merges task_with parameters into context for the sub-playbook execution.
    
    Args:
        context: Parent execution context
        task_with: Additional parameters from 'with' clause
        
    Returns:
        Merged context for nested playbook
    """
    nested_context = context.copy()
    if task_with:
        nested_context.update(task_with)
    return nested_context


def extract_parent_identifiers(
    context: Dict[str, Any],
    task_name: str
) -> tuple[Optional[Any], Optional[Any], str]:
    """
    Extract parent execution identifiers for nested playbook tracking.
    
    When called from iterator, context['parent'] contains the original 
    execution context. This function resolves parent_execution_id and 
    parent_event_id from various possible context structures.
    
    Args:
        context: Execution context
        task_name: Task name to use as parent_step
        
    Returns:
        Tuple of (parent_execution_id, parent_event_id, parent_step)
    """
    parent_context = context.get('parent', context)
    
    # Extract metadata structures
    parent_meta = {}
    try:
        if isinstance(parent_context, dict):
            parent_meta = parent_context.get('_meta') or {}
    except Exception:
        parent_meta = {}
    
    context_meta = {}
    try:
        if isinstance(context, dict):
            context_meta = context.get('_meta') or {}
    except Exception:
        context_meta = {}
    
    # Resolve parent_execution_id from various sources
    parent_execution_id = (
        (parent_context.get('execution_id')
         if isinstance(parent_context, dict) else None)
        or parent_meta.get('parent_execution_id')
        or context_meta.get('parent_execution_id')
    )
    
    # Resolve parent_event_id from various sources
    parent_event_id = (
        (parent_context.get('event_id') 
         if isinstance(parent_context, dict) else None)
        or parent_meta.get('parent_event_id')
        or context_meta.get('parent_event_id')
    )
    
    logger.debug(
        f"PLAYBOOK: Resolved parent identifiers - "
        f"execution_id={parent_execution_id}, event_id={parent_event_id}"
    )
    
    parent_step = task_name
    
    return parent_execution_id, parent_event_id, parent_step


def validate_loop_configuration(task_config: Dict[str, Any]) -> None:
    """
    Validate that task does not use deprecated loop configuration.
    
    Legacy loop support has been removed. Tasks must use the new iterator
    wrapper pattern instead.
    
    Args:
        task_config: Task configuration
        
    Raises:
        ValueError: If task uses deprecated 'loop' block
    """
    if isinstance(task_config.get('loop'), dict):
        raise ValueError(
            "playbook task no longer supports 'loop' blocks. "
            "Wrap the playbook in a 'type: iterator' task with 'collection' "
            "and 'element', and move this playbook under iterator.task"
        )
