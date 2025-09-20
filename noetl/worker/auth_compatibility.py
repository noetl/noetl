"""
Backwards compatibility layer for NoETL authentication.

Handles the transition from 'credentials' field to unified 'auth' attribute,
providing warnings and automatic transformation for deprecated usage.
"""

import copy
from typing import Dict, Any, Optional
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def transform_credentials_to_auth(step_config: Dict[str, Any], task_with: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Transform deprecated 'credentials' field to unified 'auth' field with warnings.
    
    Args:
        step_config: Step configuration dictionary
        task_with: Task 'with' parameters dictionary
        
    Returns:
        Tuple of (updated_step_config, updated_task_with) with credentials transformed to auth
    """
    updated_step = copy.deepcopy(step_config)
    updated_with = copy.deepcopy(task_with)
    
    # Check step-level credentials
    step_creds = updated_step.get('credentials')
    if step_creds is not None:
        logger.warning(
            f"COMPATIBILITY: Step '{step_config.get('task', 'unknown')}' uses deprecated 'credentials' field. "
            "Please migrate to 'auth' field. See https://docs.noetl.io/migration/auth-unified"
        )
        
        # Transform to auth if no auth already exists
        if 'auth' not in updated_step:
            updated_step['auth'] = step_creds
        else:
            logger.warning(
                f"COMPATIBILITY: Step '{step_config.get('task', 'unknown')}' has both 'credentials' and 'auth' fields. "
                "Using 'auth' field and ignoring 'credentials'"
            )
        
        # Remove the deprecated field
        del updated_step['credentials']
    
    # Check task-with-level credentials
    with_creds = updated_with.get('credentials')
    if with_creds is not None:
        logger.warning(
            f"COMPATIBILITY: Step '{step_config.get('task', 'unknown')}' uses deprecated 'credentials' in 'with' parameters. "
            "Please migrate to 'auth' field. See https://docs.noetl.io/migration/auth-unified"
        )
        
        # Transform to auth if no auth already exists
        if 'auth' not in updated_with:
            updated_with['auth'] = with_creds
        else:
            logger.warning(
                f"COMPATIBILITY: Step '{step_config.get('task', 'unknown')}' has both 'credentials' and 'auth' in 'with' parameters. "
                "Using 'auth' field and ignoring 'credentials'"
            )
        
        # Remove the deprecated field
        del updated_with['credentials']
    
    return updated_step, updated_with


def validate_auth_transition(step_config: Dict[str, Any], task_with: Dict[str, Any]) -> None:
    """
    Validate that the auth transition is valid and log appropriate messages.
    
    Args:
        step_config: Step configuration dictionary
        task_with: Task 'with' parameters dictionary
    """
    step_name = step_config.get('task', 'unknown')
    
    # Check for mixed usage patterns that might indicate confusion
    has_step_creds = 'credentials' in step_config
    has_step_auth = 'auth' in step_config
    has_with_creds = 'credentials' in task_with
    has_with_auth = 'auth' in task_with
    
    if (has_step_creds or has_with_creds) and (has_step_auth or has_with_auth):
        logger.warning(
            f"COMPATIBILITY: Step '{step_name}' mixes old 'credentials' and new 'auth' fields. "
            "This is supported for backwards compatibility but please migrate to 'auth' only."
        )
    
    # Check for complex credentials patterns that might need manual migration
    for location, config in [("step", step_config), ("with", task_with)]:
        creds = config.get('credentials')
        if creds and isinstance(creds, dict):
            # Check if this looks like complex credential mapping
            if any(isinstance(v, dict) for v in creds.values()):
                logger.info(
                    f"COMPATIBILITY: Step '{step_name}' has complex credentials mapping in {location}. "
                    "Auto-transformation applied, but please review the new 'auth' structure."
                )


def get_auth_deprecation_summary() -> Dict[str, Any]:
    """
    Get summary information about auth deprecation for debugging/monitoring.
    
    Returns:
        Dictionary with deprecation statistics and recommendations
    """
    return {
        "deprecated_field": "credentials",
        "new_field": "auth",
        "migration_guide": "https://docs.noetl.io/migration/auth-unified",
        "supported_until": "v2.0.0",
        "current_status": "backwards_compatible_with_warnings",
        "action_required": "Replace 'credentials' with 'auth' in all playbooks"
    }