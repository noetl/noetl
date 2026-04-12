"""

NoETL API v2 - Pure Event Sourcing Architecture.

Single source of truth: noetl.event table
- event.result stores control-plane state with status + optional reference/context (no inline output payload)
- No queue tables, no projection tables
- All state derived from events
- NATS for command notifications only

"""

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

logger = setup_logger(__name__, include_location=True)

router = APIRouter(prefix='', tags=['api'])

_playbook_repo: Optional[PlaybookRepo] = None

_state_store: Optional[StateStore] = None

_engine: Optional[ControlFlowEngine] = None

_nats_publisher: Optional[NATSCommandPublisher] = None

_CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS = float(os.getenv('NOETL_CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS', '0.25'))

_CLAIM_LEASE_SECONDS = max(1.0, float(os.getenv('NOETL_COMMAND_CLAIM_LEASE_SECONDS', '120')))

_CLAIM_ACTIVE_RETRY_AFTER_SECONDS = max(1, int(os.getenv('NOETL_COMMAND_CLAIM_RETRY_AFTER_SECONDS', '2')))

_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS = max(0.01, float(os.getenv('NOETL_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS', '0.25')))

_BATCH_ACCEPT_QUEUE_MAXSIZE = max(1, int(os.getenv('NOETL_BATCH_ACCEPT_QUEUE_MAXSIZE', '1024')))

_BATCH_ACCEPT_WORKERS = max(0, int(os.getenv('NOETL_BATCH_ACCEPT_WORKERS', '1')))

_BATCH_PROCESSING_TIMEOUT_SECONDS = max(0.0, float(os.getenv('NOETL_BATCH_PROCESSING_TIMEOUT_SECONDS', '0')))

_BATCH_PROCESSING_WARN_SECONDS = max(0.1, float(os.getenv('NOETL_BATCH_PROCESSING_WARN_SECONDS', '15.0')))

_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS = max(60000, int(os.getenv('NOETL_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS', '300000')))

_BATCH_STATUS_STREAM_POLL_SECONDS = max(0.1, float(os.getenv('NOETL_BATCH_STATUS_STREAM_POLL_SECONDS', '0.5')))

_BATCH_MAX_EVENTS_PER_REQUEST = max(1, int(os.getenv('NOETL_BATCH_MAX_EVENTS_PER_REQUEST', '256')))

_BATCH_MAX_PAYLOAD_BYTES = max(1024, int(os.getenv('NOETL_BATCH_MAX_PAYLOAD_BYTES', str(2 * 1024 * 1024))))

_COMMAND_CONTEXT_INLINE_MAX_BYTES = max(4096, int(os.getenv('NOETL_COMMAND_CONTEXT_INLINE_MAX_BYTES', os.getenv('NOETL_INLINE_MAX_BYTES', '65536'))))

_EVENT_RESULT_CONTEXT_MAX_BYTES = max(1024, int(os.getenv('NOETL_EVENT_RESULT_CONTEXT_MAX_BYTES', '16384')))

_EVENT_RESULT_CONTEXT_MAX_ROWS_PER_COMMAND = max(1, int(os.getenv('NOETL_EVENT_RESULT_CONTEXT_MAX_ROWS_PER_COMMAND', '1')))

_COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS = max(5.0, float(os.getenv('NOETL_COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS', '20')))

_COMMAND_PUBLISH_RECOVERY_JITTER_SECONDS = max(0.0, float(os.getenv('NOETL_COMMAND_PUBLISH_RECOVERY_JITTER_SECONDS', '2')))

_COMMAND_PUBLISH_RECOVERY_MAX_CONCURRENCY = max(1, int(os.getenv('NOETL_COMMAND_PUBLISH_RECOVERY_MAX_CONCURRENCY', '16')))

_COMMAND_TERMINAL_EVENT_TYPES = ['command.completed', 'command.failed', 'command.cancelled']

_EXECUTION_TERMINAL_EVENT_TYPES = ['playbook.completed', 'playbook.failed', 'workflow.completed', 'workflow.failed', 'execution.cancelled']

_BATCH_FAILURE_ENQUEUE_TIMEOUT = 'ack_timeout'

_BATCH_FAILURE_ENQUEUE_ERROR = 'enqueue_error'

_BATCH_FAILURE_QUEUE_UNAVAILABLE = 'queue_unavailable'

_BATCH_FAILURE_WORKER_UNAVAILABLE = 'worker_unavailable'

_BATCH_FAILURE_PROCESSING_TIMEOUT = 'processing_timeout'

_BATCH_FAILURE_PROCESSING_ERROR = 'processing_error'

_CLAIM_WORKER_HEARTBEAT_STALE_SECONDS = max(5.0, float(os.getenv('NOETL_COMMAND_WORKER_HEARTBEAT_STALE_SECONDS', '30')))

_CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS = max(_CLAIM_LEASE_SECONDS, float(os.getenv('NOETL_COMMAND_CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS', '1800')))

_STATUS_VALUE_MAX_BYTES = max(256, int(os.getenv('NOETL_STATUS_VALUE_MAX_BYTES', '16384')))

_STATUS_PREVIEW_ITEMS = max(1, int(os.getenv('NOETL_STATUS_PREVIEW_ITEMS', '5')))

_ACTIVE_CLAIMS_CACHE_TTL_SECONDS = max(1.0, float(os.getenv('NOETL_ACTIVE_CLAIMS_CACHE_TTL_SECONDS', str(_CLAIM_WORKER_HEARTBEAT_STALE_SECONDS))))

_ACTIVE_CLAIMS_CACHE_MAX_ENTRIES = max(128, int(os.getenv('NOETL_ACTIVE_CLAIMS_CACHE_MAX_ENTRIES', '5000')))

_ACTIVE_CLAIMS_CACHE_PRUNE_INTERVAL_SECONDS = max(0.1, float(os.getenv('NOETL_ACTIVE_CLAIMS_CACHE_PRUNE_INTERVAL_SECONDS', '1.0')))

_batch_accept_queue: Optional[asyncio.Queue[Any]] = None

_batch_accept_workers_tasks: list[asyncio.Task] = []

_batch_acceptor_lock: Optional[asyncio.Lock] = None

def get_engine():
    """Get or initialize engine."""
    global _playbook_repo, _state_store, _engine
    if _engine is None:
        _playbook_repo = PlaybookRepo()
        _state_store = StateStore(_playbook_repo)
        _engine = ControlFlowEngine(_playbook_repo, _state_store)
    return _engine

async def _invalidate_execution_state_cache(execution_id: str, reason: str, engine: Optional[ControlFlowEngine]=None) -> None:
    """Best-effort cache invalidation to recover from partial command issuance failures."""
    try:
        active_engine = engine or get_engine()
        await active_engine.state_store.invalidate_state(str(execution_id), reason=reason)
    except Exception as cache_error:
        logger.warning('[STATE-CACHE-INVALIDATE] failed execution_id=%s reason=%s error=%s', execution_id, reason, cache_error)

async def get_nats_publisher():
    """Get or initialize NATS publisher."""
    global _nats_publisher
    if _nats_publisher is None:
        from noetl.core.config import settings
        _nats_publisher = NATSCommandPublisher(nats_url=settings.nats_url, subject=settings.nats_subject)
        await _nats_publisher.connect()
        logger.info(f'NATS publisher initialized: {settings.nats_url}')
    return _nats_publisher

__all__ = ['logger', 'router', '_playbook_repo', '_state_store', '_engine', '_nats_publisher', '_CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS', '_CLAIM_LEASE_SECONDS', '_CLAIM_ACTIVE_RETRY_AFTER_SECONDS', '_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS', '_BATCH_ACCEPT_QUEUE_MAXSIZE', '_BATCH_ACCEPT_WORKERS', '_BATCH_PROCESSING_TIMEOUT_SECONDS', '_BATCH_PROCESSING_WARN_SECONDS', '_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS', '_BATCH_STATUS_STREAM_POLL_SECONDS', '_BATCH_MAX_EVENTS_PER_REQUEST', '_BATCH_MAX_PAYLOAD_BYTES', '_COMMAND_CONTEXT_INLINE_MAX_BYTES', '_EVENT_RESULT_CONTEXT_MAX_BYTES', '_EVENT_RESULT_CONTEXT_MAX_ROWS_PER_COMMAND', '_COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS', '_COMMAND_PUBLISH_RECOVERY_JITTER_SECONDS', '_COMMAND_PUBLISH_RECOVERY_MAX_CONCURRENCY', '_COMMAND_TERMINAL_EVENT_TYPES', '_EXECUTION_TERMINAL_EVENT_TYPES', '_BATCH_FAILURE_ENQUEUE_TIMEOUT', '_BATCH_FAILURE_ENQUEUE_ERROR', '_BATCH_FAILURE_QUEUE_UNAVAILABLE', '_BATCH_FAILURE_WORKER_UNAVAILABLE', '_BATCH_FAILURE_PROCESSING_TIMEOUT', '_BATCH_FAILURE_PROCESSING_ERROR', '_CLAIM_WORKER_HEARTBEAT_STALE_SECONDS', '_CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS', '_STATUS_VALUE_MAX_BYTES', '_STATUS_PREVIEW_ITEMS', '_ACTIVE_CLAIMS_CACHE_TTL_SECONDS', '_ACTIVE_CLAIMS_CACHE_MAX_ENTRIES', '_ACTIVE_CLAIMS_CACHE_PRUNE_INTERVAL_SECONDS', '_batch_accept_queue', '_batch_accept_workers_tasks', '_batch_acceptor_lock', 'get_engine', '_invalidate_execution_state_cache', 'get_nats_publisher']
