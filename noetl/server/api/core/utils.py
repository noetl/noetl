import json
import math
from typing import Any, Optional
from datetime import datetime, timezone
from noetl.core.db.pool import get_server_pool_stats
from .core import (
    _STATUS_PREVIEW_ITEMS,
    _STATUS_VALUE_MAX_BYTES,
    _STRICT_CONTEXT_FORBIDDEN_KEYS,
)

def _estimate_json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return len(str(value).encode("utf-8"))

def _compute_retry_after(min_seconds: float = 1.0, max_seconds: float = 15.0) -> str:
    """Return Retry-After value based on actual server pool state."""
    try:
        stats = get_server_pool_stats()
        waiting = int(stats.get("requests_waiting", 0) or 0)
        available = int(stats.get("slots_available", 1) or 1)
        if waiting == 0 and available > 0:
            return str(int(min_seconds))
        estimated = min_seconds + 0.5 * (waiting + 1) + (1.0 if available == 0 else 0.0)
        return str(int(min(max(estimated, min_seconds), max_seconds)))
    except Exception:
        return str(int(min_seconds))

def _compact_status_value(value: Any, depth: int = 0) -> Any:
    """Compact large nested values for execution status payloads."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= 3:
        if isinstance(value, dict):
            return f"dict({len(value)} keys)"
        if isinstance(value, (list, tuple)):
            return f"list({len(value)} items)"
        return str(type(value).__name__)
    if isinstance(value, dict):
        items = list(value.items())
        compacted: dict[str, Any] = {}
        for key, item_value in items[:_STATUS_PREVIEW_ITEMS]:
            compacted[key] = _compact_status_value(item_value, depth + 1)
        if len(items) > _STATUS_PREVIEW_ITEMS:
            compacted["_truncated_keys"] = len(items) - _STATUS_PREVIEW_ITEMS
        if _estimate_json_size(compacted) > _STATUS_VALUE_MAX_BYTES:
            return {"_truncated": True, "_type": "dict", "_keys": len(items)}
        return compacted
    if isinstance(value, (list, tuple)):
        seq = list(value)
        compacted_list = [_compact_status_value(v, depth + 1) for v in seq[:_STATUS_PREVIEW_ITEMS]]
        if len(seq) > _STATUS_PREVIEW_ITEMS:
            compacted_list.append(f"... {len(seq) - _STATUS_PREVIEW_ITEMS} more")
        if _estimate_json_size(compacted_list) > _STATUS_VALUE_MAX_BYTES:
            return {"_truncated": True, "_type": "list", "_items": len(seq)}
        return compacted_list
    return str(value)

def _compact_status_variables(variables: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key, value in variables.items():
        size_bytes = _estimate_json_size(value)
        if size_bytes <= _STATUS_VALUE_MAX_BYTES:
            compacted[key] = value
        else:
            compacted[key] = {
                "_truncated": True,
                "_original_size_bytes": size_bytes,
                "_preview": _compact_status_value(value),
            }
    return compacted

def _normalize_utc_timestamp(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _iso_timestamp(value: Optional[datetime]) -> Optional[str]:
    normalized = _normalize_utc_timestamp(value)
    return normalized.isoformat() if normalized else None

def _format_duration_human(total_seconds: Optional[float]) -> Optional[str]:
    if total_seconds is None:
        return None
    seconds = max(0, int(round(float(total_seconds))))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    if secs or not parts: parts.append(f"{secs}s")
    return " ".join(parts)

def _duration_fields(
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    completed: bool,
) -> dict[str, Any]:
    start_dt = _normalize_utc_timestamp(start_time)
    end_dt = _normalize_utc_timestamp(end_time)
    duration_seconds: Optional[float] = None
    if start_dt:
        effective_end = end_dt if completed and end_dt else datetime.now(timezone.utc)
        duration_seconds = max(0.0, (effective_end - start_dt).total_seconds())
    return {
        "start_time": _iso_timestamp(start_dt),
        "end_time": _iso_timestamp(end_dt if completed else None),
        "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
        "duration_human": _format_duration_human(duration_seconds),
    }

def _contains_forbidden_payload_keys(value: Any, forbidden_keys: set[str], *, depth: int = 0) -> bool:
    if depth > 8: return False
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in forbidden_keys: return True
            if _contains_forbidden_payload_keys(child, forbidden_keys, depth=depth + 1): return True
    elif isinstance(value, list):
        for child in value:
            if _contains_forbidden_payload_keys(child, forbidden_keys, depth=depth + 1): return True
    return False

def _contains_legacy_command_keys(value: Any, *, depth: int = 0) -> bool:
    # PERFORMANCE & CORRECTNESS: Do not kill postgres tool results (e.g. 'command_0').
    # The JSON size limit is sufficient to prevent DB bloat.
    return False

def _normalize_result_status(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if raw in {"OK", "SUCCESS"}: return "COMPLETED"
    if raw in {"ERROR", "FAILED"}: return "FAILED"
    if raw: return raw
    return "UNKNOWN"

def _status_from_event_name(event_name: str) -> str:
    lowered = event_name.lower()
    if "error" in lowered or "failed" in lowered: return "FAILED"
    if "done" in lowered or "exit" in lowered or "completed" in lowered: return "COMPLETED"
    return "RUNNING"
