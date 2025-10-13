"""
Iterator utility functions.

Provides helpers for collection coercion, filtering, and sorting.
"""

import json
from typing import Any, List, Tuple

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def coerce_items(rendered_items: Any) -> List[Any]:
    """
    Coerce various input types into a list of items.
    
    Handles lists, tuples, JSON strings, Python literal strings,
    and fallback to single-item list.
    
    Args:
        rendered_items: Input to coerce to list
        
    Returns:
        List of items
    """
    if isinstance(rendered_items, list):
        return rendered_items
    
    if isinstance(rendered_items, tuple):
        return list(rendered_items)
    
    if isinstance(rendered_items, str):
        s = rendered_items.strip()
        if not s:
            return []
        
        # Try JSON first
        try:
            obj = json.loads(s)
            if isinstance(obj, list):
                return obj
            # JSON parsing may succeed but produce a scalar/dict
            if isinstance(obj, tuple):
                return list(obj)
            if isinstance(obj, dict):
                return [obj]
        except Exception:
            # Fall back to Python literal evaluation for repr-style strings
            try:
                import ast
                obj = ast.literal_eval(s)
                if isinstance(obj, list):
                    return obj
                if isinstance(obj, tuple):
                    return list(obj)
                if isinstance(obj, dict):
                    return [obj]
            except Exception:
                pass
        
        # Fallback: treat as a single item (do not iterate characters)
        return [rendered_items]
    
    # Fallback single item
    return [rendered_items]


def truthy(val: Any) -> bool:
    """
    Evaluate value for truthiness in template context.
    
    Handles booleans, None, numbers, and string representations
    of boolean values.
    
    Args:
        val: Value to evaluate
        
    Returns:
        Boolean evaluation result
    """
    try:
        if isinstance(val, bool):
            return val
        if val is None:
            return False
        if isinstance(val, (int, float)):
            return val != 0
        
        s = str(val).strip().lower()
        if s in {"true", "yes", "y", "on", "1"}:
            return True
        if s in {"false", "no", "n", "off", "0", "", "none", "null"}:
            return False
        
        # Non-empty strings default to True
        return True
    except Exception:
        return False


def create_batches(
    indexed_items: List[Tuple[int, Any]], 
    chunk_n: int
) -> List[List[Tuple[int, Any]]]:
    """
    Create batches from indexed items.
    
    Args:
        indexed_items: List of (original_index, item) tuples
        chunk_n: Chunk size (0 or None means no chunking)
        
    Returns:
        List of batches, where each batch is a list of (index, item) tuples
    """
    if chunk_n and chunk_n > 0:
        # Create chunks of specified size
        return [
            indexed_items[i:i+chunk_n] 
            for i in range(0, len(indexed_items), chunk_n)
        ]
    else:
        # One logical iteration per item (no chunking)
        return [[pair] for pair in indexed_items]
