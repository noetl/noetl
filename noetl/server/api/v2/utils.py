import os
import json
import time
import asyncio
import heapq
import math
from dataclasses import dataclass
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from typing import Any, Optional, Literal
from datetime import datetime, timezone
from psycopg.types.json import Json
from psycopg.rows import dict_row
from psycopg_pool import PoolTimeout
from noetl.core.dsl.v2.models import Event
from noetl.core.dsl.v2.engine import ControlFlowEngine, PlaybookRepo, StateStore
from noetl.core.db.pool import get_pool_connection, get_server_pool_stats
from noetl.core.messaging import NATSCommandPublisher
from noetl.core.storage import Scope, default_store, estimate_size
from noetl.claim_policy import decide_reclaim_for_existing_claim
from noetl.server.api.event_queries import PENDING_COMMAND_COUNT_SQL
from noetl.server.api.supervision import supervise_command_issued, supervise_persisted_event
from noetl.core.logger import setup_logger

from .core import *
from .models import *
def _extract_command_id_from_payload(payload: Optional[dict[str, Any]], meta: Optional[dict[str, Any]]=None) -> Optional[str]:
    payload_obj = payload if isinstance(payload, dict) else {}
    meta_obj = meta if isinstance(meta, dict) else {}
    candidates: list[Any] = [payload_obj.get('command_id'), meta_obj.get('command_id')]
    payload_context = payload_obj.get('context')
    if isinstance(payload_context, dict):
        candidates.append(payload_context.get('command_id'))
    payload_result = payload_obj.get('result')
    if isinstance(payload_result, dict):
        candidates.append(payload_result.get('command_id'))
        result_context = payload_result.get('context')
        if isinstance(result_context, dict):
            candidates.append(result_context.get('command_id'))
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

def _extract_event_command_id(req: 'EventRequest') -> Optional[str]:
    return _extract_command_id_from_payload(req.payload, req.meta)

_STRICT_RESULT_ALLOWED_KEYS = {'status', 'reference', 'context', 'command_id'}

_STRICT_PAYLOAD_FORBIDDEN_KEYS = {'response', 'inputs', 'data', 'data_reference', '_internal_data', '_inline'}

_STRICT_CONTEXT_FORBIDDEN_KEYS = {'response', 'result', 'payload', 'data', '_ref', '_inline', '_internal_data'}

def _contains_forbidden_payload_keys(value: Any, forbidden_keys: set[str], *, depth: int=0) -> bool:
    if depth > 8:
        return False
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in forbidden_keys:
                return True
            if _contains_forbidden_payload_keys(child, forbidden_keys, depth=depth + 1):
                return True
    elif isinstance(value, list):
        for child in value:
            if _contains_forbidden_payload_keys(child, forbidden_keys, depth=depth + 1):
                return True
    return False

def _contains_legacy_command_keys(value: Any, *, depth: int=0) -> bool:
    if depth > 8:
        return False
    if isinstance(value, dict):
        for key, child in value.items():
            key_str = str(key)
            if key_str.startswith('command_') and key_str != 'command_id':
                return True
            if _contains_legacy_command_keys(child, depth=depth + 1):
                return True
    elif isinstance(value, list):
        for child in value:
            if _contains_legacy_command_keys(child, depth=depth + 1):
                return True
    return False

def _validate_reference_only_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError('event payload must be an object')
    if any((key in payload for key in _STRICT_PAYLOAD_FORBIDDEN_KEYS)):
        bad = sorted((key for key in payload.keys() if key in _STRICT_PAYLOAD_FORBIDDEN_KEYS))
        raise ValueError(f'payload includes forbidden inline output keys: {', '.join(bad)}')
    result_obj = payload.get('result')
    if result_obj is None:
        return
    if not isinstance(result_obj, dict):
        raise ValueError('payload.result must be an object')
    unknown = sorted((str(k) for k in result_obj.keys() if str(k) not in _STRICT_RESULT_ALLOWED_KEYS))
    if unknown:
        raise ValueError(f'payload.result includes unsupported keys: {', '.join(unknown)}')
    reference_obj = result_obj.get('reference')
    if reference_obj is not None and (not isinstance(reference_obj, dict)):
        raise ValueError('payload.result.reference must be an object')
    context_obj = result_obj.get('context')
    if context_obj is not None:
        if not isinstance(context_obj, dict):
            raise ValueError('payload.result.context must be an object')
        if _contains_forbidden_payload_keys(context_obj, _STRICT_CONTEXT_FORBIDDEN_KEYS):
            raise ValueError('payload.result.context includes forbidden inline data keys')
        if _contains_legacy_command_keys(context_obj):
            raise ValueError('payload.result.context includes legacy command_* keys')

def _extract_event_error(payload: dict[str, Any]) -> Optional[str]:
    """Extract compact error text for noetl.event.error column."""
    if not isinstance(payload, dict):
        return None
    direct_error = payload.get('error')
    if isinstance(direct_error, str):
        value = direct_error.strip()
        return value[:2000] if value else None
    if isinstance(direct_error, dict):
        message = direct_error.get('message')
        if isinstance(message, str) and message.strip():
            return message.strip()[:2000]
        compact = json.dumps(direct_error, default=str)
        return compact[:2000] if compact else None
    result_obj = payload.get('result')
    if isinstance(result_obj, dict):
        result_error = result_obj.get('error')
        if isinstance(result_error, str):
            value = result_error.strip()
            return value[:2000] if value else None
        if isinstance(result_error, dict):
            message = result_error.get('message')
            if isinstance(message, str) and message.strip():
                return message.strip()[:2000]
            compact = json.dumps(result_error, default=str)
            return compact[:2000] if compact else None
    return None

def _estimate_json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str, separators=(',', ':')).encode('utf-8'))
    except Exception:
        return len(str(value).encode('utf-8'))

def _compact_status_value(value: Any, depth: int=0) -> Any:
    """Compact large nested values for execution status payloads."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= 3:
        if isinstance(value, dict):
            return f'dict({len(value)} keys)'
        if isinstance(value, (list, tuple)):
            return f'list({len(value)} items)'
        return str(type(value).__name__)
    if isinstance(value, dict):
        items = list(value.items())
        compacted: dict[str, Any] = {}
        for key, item_value in items[:_STATUS_PREVIEW_ITEMS]:
            compacted[key] = _compact_status_value(item_value, depth + 1)
        if len(items) > _STATUS_PREVIEW_ITEMS:
            compacted['_truncated_keys'] = len(items) - _STATUS_PREVIEW_ITEMS
        if _estimate_json_size(compacted) > _STATUS_VALUE_MAX_BYTES:
            return {'_truncated': True, '_type': 'dict', '_keys': len(items)}
        return compacted
    if isinstance(value, (list, tuple)):
        seq = list(value)
        compacted_list = [_compact_status_value(v, depth + 1) for v in seq[:_STATUS_PREVIEW_ITEMS]]
        if len(seq) > _STATUS_PREVIEW_ITEMS:
            compacted_list.append(f'... {len(seq) - _STATUS_PREVIEW_ITEMS} more')
        if _estimate_json_size(compacted_list) > _STATUS_VALUE_MAX_BYTES:
            return {'_truncated': True, '_type': 'list', '_items': len(seq)}
        return compacted_list
    return str(value)

def _compact_status_variables(variables: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key, value in variables.items():
        size_bytes = _estimate_json_size(value)
        if size_bytes <= _STATUS_VALUE_MAX_BYTES:
            compacted[key] = value
        else:
            compacted[key] = {'_truncated': True, '_original_size_bytes': size_bytes, '_preview': _compact_status_value(value)}
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
    if days:
        parts.append(f'{days}d')
    if hours:
        parts.append(f'{hours}h')
    if minutes:
        parts.append(f'{minutes}m')
    if secs or not parts:
        parts.append(f'{secs}s')
    return ' '.join(parts)

def _duration_fields(start_time: Optional[datetime], end_time: Optional[datetime], completed: bool) -> dict[str, Any]:
    start_dt = _normalize_utc_timestamp(start_time)
    end_dt = _normalize_utc_timestamp(end_time)
    duration_seconds: Optional[float] = None
    if start_dt:
        effective_end = end_dt if completed and end_dt else datetime.now(timezone.utc)
        duration_seconds = max(0.0, (effective_end - start_dt).total_seconds())
    return {'start_time': _iso_timestamp(start_dt), 'end_time': _iso_timestamp(end_dt if completed else None), 'duration_seconds': round(duration_seconds, 3) if duration_seconds is not None else None, 'duration_human': _format_duration_human(duration_seconds)}

def _status_from_event_name(event_name: str) -> str:
    lowered = event_name.lower()
    if 'error' in lowered or 'failed' in lowered:
        return 'FAILED'
    if 'done' in lowered or 'exit' in lowered or 'completed' in lowered:
        return 'COMPLETED'
    return 'RUNNING'

def _collect_compact_context(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    compact: dict[str, Any] = {}
    for key in ('command_id', 'loop_event_id', 'request_id', 'event_ids', 'commands_generated', 'error_code', 'message', 'worker_id', 'batch_request_id'):
        if key in payload and payload[key] is not None:
            compact[key] = payload[key]
    return compact or None

def _bounded_context(context_obj: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(context_obj, dict):
        return None
    if _contains_forbidden_payload_keys(context_obj, _STRICT_CONTEXT_FORBIDDEN_KEYS):
        return None
    if _contains_legacy_command_keys(context_obj):
        return None
    if _estimate_json_size(context_obj) > _EVENT_RESULT_CONTEXT_MAX_BYTES:
        return None
    return context_obj

def _normalize_result_status(value: Any) -> str:
    raw = str(value or '').strip().upper()
    if raw in {'OK', 'SUCCESS'}:
        return 'COMPLETED'
    if raw in {'ERROR', 'FAILED'}:
        return 'FAILED'
    if raw:
        return raw
    return 'UNKNOWN'

def _build_reference_only_result(*, payload: dict[str, Any], status: str) -> dict[str, Any]:
    result_obj: dict[str, Any] = {'status': _normalize_result_status(status)}
    payload_result = payload.get('result')
    if isinstance(payload_result, dict):
        payload_status = payload_result.get('status')
        if isinstance(payload_status, str) and payload_status.strip():
            result_obj['status'] = _normalize_result_status(payload_status)
        reference = payload_result.get('reference')
        if isinstance(reference, dict):
            result_obj['reference'] = reference
        context = _bounded_context(payload_result.get('context'))
        if isinstance(context, dict):
            result_obj['context'] = context
    else:
        direct_reference = payload.get('reference')
        if isinstance(direct_reference, dict):
            result_obj['reference'] = direct_reference
        direct_context = _bounded_context(payload.get('context'))
        if isinstance(direct_context, dict):
            result_obj['context'] = direct_context
    compact = _collect_compact_context(payload)
    if compact:
        existing_context = result_obj.get('context')
        if isinstance(existing_context, dict):
            merged = {**compact, **existing_context}
            if _estimate_json_size(merged) <= _EVENT_RESULT_CONTEXT_MAX_BYTES:
                result_obj['context'] = merged
        elif _estimate_json_size(compact) <= _EVENT_RESULT_CONTEXT_MAX_BYTES:
            result_obj['context'] = compact
    return result_obj

__all__ = ['_extract_command_id_from_payload', '_extract_event_command_id', '_STRICT_RESULT_ALLOWED_KEYS', '_STRICT_PAYLOAD_FORBIDDEN_KEYS', '_STRICT_CONTEXT_FORBIDDEN_KEYS', '_contains_forbidden_payload_keys', '_contains_legacy_command_keys', '_validate_reference_only_payload', '_extract_event_error', '_estimate_json_size', '_compact_status_value', '_compact_status_variables', '_normalize_utc_timestamp', '_iso_timestamp', '_format_duration_human', '_duration_fields', '_status_from_event_name', '_collect_compact_context', '_bounded_context', '_normalize_result_status', '_build_reference_only_result']
