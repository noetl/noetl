"""
Template rendering for save operations.

Handles rendering data mappings and parameters with Jinja2 templates.
"""

import json
from typing import Dict, Any
from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def render_data_mapping(
    jinja_env: Environment,
    mapping: Any,
    context: Dict[str, Any]
) -> Any:
    """
    Render data mapping with Jinja2 templates.
    
    Args:
        jinja_env: Jinja2 environment
        mapping: Data mapping (may contain templates)
        context: Execution context for rendering
        
    Returns:
        Rendered mapping
    """
    try:
        # Lazy import to avoid circulars
        from noetl.core.dsl.render import render_template
        return render_template(
            jinja_env, mapping, context, 
            rules=None, strict_keys=False
        )
    except Exception as render_err:
        # Log the rendering failure for debugging
        logger.warning(
            f"SAVE: Template rendering failed for mapping {mapping}, "
            f"falling back to unrendered: {render_err}"
        )
        logger.debug(
            f"SAVE: Available context keys: "
            f"{list(context.keys()) if isinstance(context, dict) else type(context)}"
        )
        # Fallback: return as-is if rendering fails
        return mapping


def normalize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize complex param values to JSON strings.
    
    Ensures dict/list values are serialized to JSON for safe embedding
    into SQL statements when using {{ params.* }} in strings.
    
    Args:
        params: Parameters dictionary
        
    Returns:
        Normalized parameters dictionary
    """
    if not isinstance(params, dict):
        return params
    
    try:
        from noetl.core.common import DateTimeEncoder
        
        for k, v in list(params.items()):
            if isinstance(v, (dict, list)):
                try:
                    params[k] = json.dumps(v, cls=DateTimeEncoder)
                except Exception:
                    params[k] = str(v)
    except Exception:
        pass
    
    return params
