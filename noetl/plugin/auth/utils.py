"""
Utility functions for authentication processing.
"""

import os
from typing import Dict, Any, Optional
from jinja2 import Environment

from noetl.core.logger import setup_logger
from .constants import REDACTED_FIELDS

logger = setup_logger(__name__, include_location=True)


def deep_render_template(jinja_env: Environment, context: Dict, obj: Any) -> Any:
    """
    Recursively render Jinja templates in nested objects.
    
    Args:
        jinja_env: Jinja2 environment
        context: Template context
        obj: Object to render (can be dict, list, string, or primitive)
        
    Returns:
        Rendered object with templates resolved
    """
    if isinstance(obj, str):
        try:
            template = jinja_env.from_string(obj)
            return template.render(context)
        except Exception as e:
            logger.debug(f"AUTH: Failed to render template '{obj}': {e}")
            return obj
    elif isinstance(obj, dict):
        return {k: deep_render_template(jinja_env, context, v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [deep_render_template(jinja_env, context, item) for item in obj]
    else:
        return obj


def redact_dict(data: Dict) -> Dict:
    """
    Create a redacted copy of a dictionary for safe logging.
    
    Args:
        data: Dictionary to redact
        
    Returns:
        Dictionary with sensitive fields redacted
    """
    result = {}
    for key, value in data.items():
        if key.lower() in REDACTED_FIELDS or "password" in key.lower() or "secret" in key.lower() or "token" in key.lower():
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        else:
            result[key] = value
    return result


def fetch_secret_manager_value(key: str, auth_type: str) -> Optional[str]:
    """
    Fetch a scalar value from an external secret manager.
    
    Args:
        key: Secret key/name
        auth_type: Authentication type to determine field mapping
        
    Returns:
        Secret value or None if not found
    """
    # TODO: Implement actual secret manager integration
    # For now, check environment variables as a fallback
    env_key = f"NOETL_SECRET_{key.upper()}"
    value = os.getenv(env_key)
    if value:
        logger.debug(f"AUTH: Retrieved secret '{key}' from environment")
        return value
    
    logger.debug(f"AUTH: Secret '{key}' not found in environment")
    return None
