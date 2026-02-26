"""
Output select field extractor for ResultRef pattern.

Automatically extracts small fields from large results to avoid
putting huge data in render_context.

Default extraction rules:
- Extract scalar fields (strings, numbers, booleans)
- Extract small arrays (< 10 items)
- Skip large arrays and nested objects
- Always include common metadata fields (status, id, count, error)

Custom extraction via step config:
  result:
    output_select:
      - status
      - data.id
      - data.items[0].name
"""

import json
from typing import Any, Dict, List, Optional, Set
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

# Fields to always extract if present
DEFAULT_EXTRACT_FIELDS = {
    "status", "id", "error", "message", "code",
    "count", "total", "success", "failed",
    "name", "type", "kind", "state",
}

# Max size for small arrays
SMALL_ARRAY_MAX_ITEMS = 10

# Max depth for auto-extraction
MAX_EXTRACT_DEPTH = 2


def extract_output_select(
    data: Any,
    select_paths: Optional[List[str]] = None,
    max_string_len: int = 500,
    max_depth: int = MAX_EXTRACT_DEPTH,
) -> Dict[str, Any]:
    """
    Extract small fields from result data for templating.

    Args:
        data: Full result data
        select_paths: Optional explicit paths to extract (e.g., ["data.id", "status"])
        max_string_len: Max length for string values
        max_depth: Max depth for auto-extraction

    Returns:
        Dict of extracted fields suitable for render_context
    """
    if data is None:
        return {}

    # If explicit paths provided, use them
    if select_paths:
        return _extract_explicit_paths(data, select_paths, max_string_len)

    # Auto-extract based on structure
    return _auto_extract(data, max_string_len, max_depth)


def _extract_explicit_paths(
    data: Any,
    paths: List[str],
    max_string_len: int,
) -> Dict[str, Any]:
    """Extract specific paths from data."""
    result = {}

    for path in paths:
        value = _get_path(data, path)
        if value is not None:
            # Use last segment as key
            key = path.split(".")[-1].split("[")[0]
            result[key] = _truncate_value(value, max_string_len)

    return result


def _get_path(data: Any, path: str) -> Any:
    """Get value at dotted path, supporting array indexing."""
    parts = path.replace("]", "").split(".")
    current = data

    for part in parts:
        if current is None:
            return None

        # Handle array index
        if "[" in part:
            key, idx_str = part.split("[")
            idx = int(idx_str)
            if isinstance(current, dict):
                current = current.get(key)
            if isinstance(current, list) and 0 <= idx < len(current):
                current = current[idx]
            else:
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None

    return current


def _auto_extract(
    data: Any,
    max_string_len: int,
    max_depth: int,
    current_depth: int = 0,
) -> Dict[str, Any]:
    """Automatically extract small fields from data."""
    result = {}

    if not isinstance(data, dict):
        # For non-dict, wrap in _value
        if _is_small_value(data):
            return {"_value": _truncate_value(data, max_string_len)}
        elif isinstance(data, list):
            return {
                "_count": len(data),
                "_sample": data[:3] if len(data) <= SMALL_ARRAY_MAX_ITEMS else None,
            }
        return {}

    for key, value in data.items():
        # Always extract default fields
        if key in DEFAULT_EXTRACT_FIELDS:
            result[key] = _truncate_value(value, max_string_len)
            continue

        # Extract small scalar values
        if _is_small_value(value):
            result[key] = _truncate_value(value, max_string_len)

        # Extract small arrays
        elif isinstance(value, list):
            if len(value) <= SMALL_ARRAY_MAX_ITEMS:
                # Only include if items are small
                if all(_is_small_value(item) for item in value):
                    result[key] = value
                else:
                    result[f"{key}_count"] = len(value)
            else:
                result[f"{key}_count"] = len(value)

        # Recursively extract from nested dicts
        elif isinstance(value, dict) and current_depth < max_depth:
            nested = _auto_extract(value, max_string_len, max_depth, current_depth + 1)
            if nested:
                # Flatten nested with prefix
                for nested_key, nested_value in nested.items():
                    if not nested_key.startswith("_"):
                        result[f"{key}_{nested_key}"] = nested_value

    return result


def _is_small_value(value: Any) -> bool:
    """Check if value is small enough to include directly."""
    if value is None:
        return True
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return len(value) <= 1000
    return False


def _truncate_value(value: Any, max_len: int) -> Any:
    """Truncate value if too long."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "..."
    return value


def estimate_size(data: Any) -> int:
    """Estimate JSON byte size without full serialization.

    Uses recursive traversal with ``sys.getsizeof`` sampling for large
    payloads to avoid the cost of ``json.dumps`` (which allocates and
    immediately discards a full serialised string just to count bytes).
    Small/simple values still fall through to ``json.dumps`` for accuracy.
    """
    return _estimate_size_fast(data)


def _estimate_size_fast(data: Any, _depth: int = 0) -> int:
    """Fast recursive size estimator (avoids json.dumps for large structures)."""
    if data is None:
        return 4  # null
    if isinstance(data, bool):
        return 5  # true/false
    if isinstance(data, int):
        return max(1, len(str(data)))
    if isinstance(data, float):
        return 20  # conservative
    if isinstance(data, str):
        # JSON string: content + quotes + rough escape overhead
        return len(data) + 2 + data.count('"') + data.count('\\')
    if isinstance(data, (bytes, bytearray)):
        return len(data) + 2

    # For deeply nested structures, cap recursion and use rough heuristic
    if _depth > 6:
        try:
            import sys
            return sys.getsizeof(data)
        except Exception:
            return 256

    if isinstance(data, dict):
        # braces + commas + colon per entry
        size = 2 + max(0, len(data) - 1)  # {} + commas
        for k, v in data.items():
            size += _estimate_size_fast(k, _depth + 1) + 1  # key + colon
            size += _estimate_size_fast(v, _depth + 1)
        return size

    if isinstance(data, (list, tuple)):
        size = 2 + max(0, len(data) - 1)  # [] + commas
        # For large collections, sample a few items and extrapolate
        items = list(data) if not isinstance(data, list) else data
        n = len(items)
        if n <= 20 or _depth > 3:
            for item in items:
                size += _estimate_size_fast(item, _depth + 1)
        else:
            # Sample first, middle, last items
            sample_indices = [0, n // 4, n // 2, 3 * n // 4, n - 1]
            sample_total = sum(_estimate_size_fast(items[i], _depth + 1) for i in sample_indices)
            avg_item_size = sample_total / len(sample_indices)
            size += int(avg_item_size * n)
        return size

    # Fallback for unknown types
    try:
        return len(json.dumps(data, default=str).encode("utf-8"))
    except Exception:
        return 256


def should_externalize(
    data: Any,
    inline_threshold: int = 65536,  # 64KB
) -> bool:
    """Check if data should be stored externally vs inline."""
    size = estimate_size(data)
    return size > inline_threshold


def create_preview(data: Any, max_bytes: int = 1024) -> Dict[str, Any]:
    """Create a truncated preview of data for UI/debugging."""
    if isinstance(data, dict):
        preview = {}
        current_size = 2  # {}
        for key, value in data.items():
            truncated = _truncate_for_preview(value)
            item_size = len(json.dumps({key: truncated}, default=str))
            if current_size + item_size > max_bytes:
                preview["_truncated"] = True
                break
            preview[key] = truncated
            current_size += item_size
        return preview

    elif isinstance(data, list):
        return {
            "_type": "array",
            "_count": len(data),
            "_sample": [_truncate_for_preview(item) for item in data[:3]],
        }

    else:
        return {"_value": str(data)[:200]}


def _truncate_for_preview(value: Any) -> Any:
    """Truncate a single value for preview."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:100] + "..." if len(value) > 100 else value
    if isinstance(value, list):
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    return str(value)[:100]


__all__ = [
    "extract_output_select",
    "estimate_size",
    "should_externalize",
    "create_preview",
    "DEFAULT_EXTRACT_FIELDS",
]
