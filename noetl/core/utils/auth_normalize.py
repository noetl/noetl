"""
Authentication normalization utilities.

Provides functions to convert various auth object types (dicts, dataclasses, objects)
into standardized dict representation for consistent processing.
"""

from __future__ import annotations
from collections.abc import Mapping
from dataclasses import is_dataclass, asdict
from typing import Any

# Common auth fields across different auth types
COMMON_KEYS = ("type", "kind", "engine", "source", "provider", "key", "scope", "dsn", "service", "alias")


def as_mapping(obj: Any) -> dict[str, Any]:
    """
    Convert any auth item to a dict mapping.
    
    This function handles various input types:
    - dict/Mapping: returned as-is (converted to dict)
    - objects with to_dict() method: calls to_dict()  
    - dataclasses: uses asdict()
    - generic objects: extracts common attributes
    - None: returns empty dict
    
    Args:
        obj: Auth object to normalize (can be dict, dataclass, object, None)
        
    Returns:
        Dict representation of the auth object
        
    Examples:
        >>> as_mapping({'type': 'postgres'})
        {'type': 'postgres'}
        
        >>> as_mapping(ResolvedAuthItem(type='postgres', service='pg'))
        {'alias': ..., 'source': ..., 'type': 'postgres', 'service': 'pg', ...}
        
        >>> as_mapping(None)
        {}
    """
    if obj is None:
        return {}
    
    # Already a mapping (dict, etc.)
    if isinstance(obj, Mapping):
        return dict(obj)
    
    # Has explicit to_dict method
    if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
        result = obj.to_dict()
        return dict(result) if isinstance(result, Mapping) else {}
    
    # Dataclass - use asdict
    if is_dataclass(obj):
        return asdict(obj)
    
    # Generic attribute extraction for objects
    result = {}
    for key in COMMON_KEYS:
        if hasattr(obj, key):
            value = getattr(obj, key)
            if value is not None:  # Only include non-None values
                result[key] = value
    
    # If we got nothing from common keys, try some introspection
    if not result and hasattr(obj, '__dict__'):
        # Last resort - get all attributes that don't start with underscore
        for key, value in obj.__dict__.items():
            if not key.startswith('_') and value is not None:
                result[key] = value
                
    return result