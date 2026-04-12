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
from .utils import *
_DB_UNAVAILABLE_SHORT_CIRCUIT = os.getenv('NOETL_DB_UNAVAILABLE_SHORT_CIRCUIT', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}

_DB_UNAVAILABLE_BACKOFF_BASE_SECONDS = max(0.1, float(os.getenv('NOETL_DB_UNAVAILABLE_BACKOFF_BASE_SECONDS', '1.0')))

_DB_UNAVAILABLE_BACKOFF_MAX_SECONDS = max(_DB_UNAVAILABLE_BACKOFF_BASE_SECONDS, float(os.getenv('NOETL_DB_UNAVAILABLE_BACKOFF_MAX_SECONDS', '30.0')))

_DB_UNAVAILABLE_ERROR_MARKERS = ('server conn crashed', 'server login has been failing', 'server_login_retry', 'the database system is in recovery mode', 'the database system is not yet accepting connections', 'could not connect to server', 'connection refused', 'connection reset by peer', 'terminating connection due to administrator command', 'admin shutdown', 'connection is closed', 'pool closed')

_db_unavailable_failure_streak: int = 0

_db_unavailable_backoff_until_monotonic: float = 0.0

def _compute_retry_after(min_seconds: float=1.0, max_seconds: float=15.0) -> str:
    """
    Return Retry-After value (string seconds) based on actual server pool state.

    If the pool has waiters, the client should wait at least long enough for
    those to drain: roughly 0.5 s * (waiters + 1), capped at max_seconds.
    Returns a plain integer string as required by the HTTP spec.
    """
    try:
        stats = get_server_pool_stats()
        waiting = int(stats.get('requests_waiting', 0) or 0)
        available = int(stats.get('slots_available', 1) or 1)
        if waiting == 0 and available > 0:
            return str(int(min_seconds))
        estimated = min_seconds + 0.5 * (waiting + 1) + (1.0 if available == 0 else 0.0)
        return str(int(min(max(estimated, min_seconds), max_seconds)))
    except Exception:
        return str(int(min_seconds))

def _db_unavailable_retry_after() -> Optional[str]:
    remaining = _db_unavailable_backoff_until_monotonic - time.monotonic()
    if remaining <= 0:
        return None
    return str(max(1, int(math.ceil(remaining))))

def _record_db_operation_success() -> None:
    global _db_unavailable_failure_streak
    global _db_unavailable_backoff_until_monotonic
    if _db_unavailable_failure_streak > 0 or _db_unavailable_backoff_until_monotonic > time.monotonic():
        logger.info('[DB-RECOVERY] Connectivity recovered; clearing outage backoff (previous_streak=%s)', _db_unavailable_failure_streak)
    _db_unavailable_failure_streak = 0
    _db_unavailable_backoff_until_monotonic = 0.0

def _is_db_unavailable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if not message:
        return False
    return any((marker in message for marker in _DB_UNAVAILABLE_ERROR_MARKERS))

def _record_db_unavailable_failure(exc: Exception, *, operation: str) -> Optional[str]:
    global _db_unavailable_failure_streak
    global _db_unavailable_backoff_until_monotonic
    if not _is_db_unavailable_error(exc):
        return None
    _db_unavailable_failure_streak = max(1, _db_unavailable_failure_streak + 1)
    exponent = min(_db_unavailable_failure_streak - 1, 6)
    next_backoff_seconds = min(_DB_UNAVAILABLE_BACKOFF_BASE_SECONDS * 2 ** exponent, _DB_UNAVAILABLE_BACKOFF_MAX_SECONDS)
    now = time.monotonic()
    _db_unavailable_backoff_until_monotonic = max(_db_unavailable_backoff_until_monotonic, now + next_backoff_seconds)
    retry_after = _db_unavailable_retry_after() or str(max(1, int(math.ceil(next_backoff_seconds))))
    logger.warning('[DB-UNAVAILABLE] operation=%s streak=%s retry_after=%ss error=%s', operation, _db_unavailable_failure_streak, retry_after, exc)
    return retry_after

def _raise_if_db_short_circuit_enabled(*, operation: str) -> None:
    if not _DB_UNAVAILABLE_SHORT_CIRCUIT:
        return
    retry_after = _db_unavailable_retry_after()
    if retry_after is None:
        return
    raise HTTPException(status_code=503, detail={'code': 'db_unavailable', 'message': f'Database temporarily unavailable during {operation}; retry shortly'}, headers={'Retry-After': retry_after})

@router.get('/pool/status')
async def get_pool_status():
    """
    Return real-time server DB pool telemetry.

    Workers use this endpoint to proactively throttle claim/event requests
    before hitting 503, rather than discovering saturation reactively.

    Response fields:
      pool_min        - configured minimum connections
      pool_max        - configured maximum connections
      pool_size       - current live connections
      pool_available  - idle (free) connections right now
      requests_waiting- requests queued waiting for a connection
      utilization     - fraction of max in active use (0.0–1.0)
      slots_available - connections available for immediate use
    """
    stats = get_server_pool_stats()
    if not stats:
        return {'pool_min': 0, 'pool_max': 0, 'pool_size': 0, 'pool_available': 0, 'requests_waiting': 0, 'utilization': 0.0, 'slots_available': 0, 'status': 'unavailable'}
    return {**stats, 'status': 'ok'}

_EVENT_TYPE_TERMINAL_PREDICATE = 'event_type IN (' + ', '.join((f"'{e}'" for e in _COMMAND_TERMINAL_EVENT_TYPES)) + ')'

_EVENT_TYPE_ACTIVE_CLAIM_PREDICATE = "event_type IN ('command.claimed', 'command.heartbeat')"

_EVENT_TYPE_CLAIMED_PREDICATE = "event_type = 'command.claimed'"

_EVENT_TYPE_SAME_WORKER_LATEST_PREDICATE = "event_type IN ('command.started', 'command.heartbeat', 'command.completed', 'command.failed')"

_COMMAND_EVENT_DEDUPE_TYPES = {'call.done', 'call.error', 'step.exit', 'command.started', 'command.completed', 'command.failed'}

def _build_command_id_latest_lookup_sql(*, inner_select_columns: str, outer_select_columns: str, event_type_predicate: str, alias: str) -> str:
    """
    Build latest-event lookup SQL with index-friendly command_id predicates.

    Reference-only contract stores command_id in meta; avoid result JSON scans.
    """
    return f"\n        SELECT {outer_select_columns}\n        FROM noetl.event {alias}\n        WHERE execution_id = %s\n          AND {event_type_predicate}\n          AND meta ? 'command_id'\n          AND meta->>'command_id' = %s\n        ORDER BY event_id DESC\n        LIMIT 1\n    "

def _command_id_lookup_params(execution_id: int, command_id: str) -> tuple[Any, ...]:
    return (execution_id, command_id)

_CLAIM_TERMINAL_LOOKUP_SQL = _build_command_id_latest_lookup_sql(inner_select_columns='event_type, event_id', outer_select_columns='event_type', event_type_predicate=_EVENT_TYPE_TERMINAL_PREDICATE, alias='terminal_match')

_CLAIM_EXISTING_LOOKUP_SQL = _build_command_id_latest_lookup_sql(inner_select_columns='event_id, worker_id, meta, created_at', outer_select_columns='event_id, worker_id, meta, created_at', event_type_predicate=_EVENT_TYPE_ACTIVE_CLAIM_PREDICATE, alias='claimed_match')

_CLAIM_SAME_WORKER_LATEST_LOOKUP_SQL = _build_command_id_latest_lookup_sql(inner_select_columns='event_type, event_id', outer_select_columns='event_type', event_type_predicate=_EVENT_TYPE_SAME_WORKER_LATEST_PREDICATE, alias='same_worker_latest_match')

_HANDLE_EVENT_CLAIMED_LOOKUP_SQL = _build_command_id_latest_lookup_sql(inner_select_columns='worker_id, meta, event_id', outer_select_columns='worker_id, meta', event_type_predicate=_EVENT_TYPE_CLAIMED_PREDICATE, alias='claimed_event')

_PENDING_COMMAND_COUNT_SQL = PENDING_COMMAND_COUNT_SQL

async def _next_snowflake_id(cur) -> int:
    """Generate a snowflake ID using the current DB cursor/connection."""
    await cur.execute('SELECT noetl.snowflake_id() AS snowflake_id')
    row = await cur.fetchone()
    if not row:
        raise RuntimeError('Failed to generate snowflake ID from database')
    value = row.get('snowflake_id') if isinstance(row, dict) else row[0]
    return int(value)

__all__ = ['_DB_UNAVAILABLE_SHORT_CIRCUIT', '_DB_UNAVAILABLE_BACKOFF_BASE_SECONDS', '_DB_UNAVAILABLE_BACKOFF_MAX_SECONDS', '_DB_UNAVAILABLE_ERROR_MARKERS', '_db_unavailable_failure_streak', '_db_unavailable_backoff_until_monotonic', '_compute_retry_after', '_db_unavailable_retry_after', '_record_db_operation_success', '_is_db_unavailable_error', '_record_db_unavailable_failure', '_raise_if_db_short_circuit_enabled', 'get_pool_status', '_EVENT_TYPE_TERMINAL_PREDICATE', '_EVENT_TYPE_ACTIVE_CLAIM_PREDICATE', '_EVENT_TYPE_CLAIMED_PREDICATE', '_EVENT_TYPE_SAME_WORKER_LATEST_PREDICATE', '_COMMAND_EVENT_DEDUPE_TYPES', '_build_command_id_latest_lookup_sql', '_command_id_lookup_params', '_CLAIM_TERMINAL_LOOKUP_SQL', '_CLAIM_EXISTING_LOOKUP_SQL', '_CLAIM_SAME_WORKER_LATEST_LOOKUP_SQL', '_HANDLE_EVENT_CLAIMED_LOOKUP_SQL', '_PENDING_COMMAND_COUNT_SQL', '_next_snowflake_id']
