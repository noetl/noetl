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
_active_claim_cache_by_event: dict[int, _ActiveClaimCacheEntry] = {}

_active_claim_cache_by_command: dict[str, _ActiveClaimCacheEntry] = {}

_active_claim_cache_last_prune_monotonic: float = 0.0

def _active_claim_cache_prune(now_monotonic: Optional[float]=None, *, force: bool=False) -> None:
    global _active_claim_cache_last_prune_monotonic
    now = now_monotonic if now_monotonic is not None else time.monotonic()
    if not force:
        if len(_active_claim_cache_by_event) <= _ACTIVE_CLAIMS_CACHE_MAX_ENTRIES and now - _active_claim_cache_last_prune_monotonic < _ACTIVE_CLAIMS_CACHE_PRUNE_INTERVAL_SECONDS:
            return
    _active_claim_cache_last_prune_monotonic = now
    expired_event_ids = [event_id for event_id, entry in _active_claim_cache_by_event.items() if entry.expires_at_monotonic <= now]
    for event_id in expired_event_ids:
        entry = _active_claim_cache_by_event.pop(event_id, None)
        if entry and _active_claim_cache_by_command.get(entry.command_id) is entry:
            _active_claim_cache_by_command.pop(entry.command_id, None)
    if len(_active_claim_cache_by_event) <= _ACTIVE_CLAIMS_CACHE_MAX_ENTRIES:
        return
    overflow = len(_active_claim_cache_by_event) - _ACTIVE_CLAIMS_CACHE_MAX_ENTRIES
    oldest_entries = heapq.nsmallest(overflow, _active_claim_cache_by_event.values(), key=lambda item: item.updated_at_monotonic)
    for entry in oldest_entries:
        _active_claim_cache_by_event.pop(entry.event_id, None)
        if _active_claim_cache_by_command.get(entry.command_id) is entry:
            _active_claim_cache_by_command.pop(entry.command_id, None)

def _active_claim_cache_get(event_id: int) -> Optional[_ActiveClaimCacheEntry]:
    now = time.monotonic()
    _active_claim_cache_prune(now)
    entry = _active_claim_cache_by_event.get(int(event_id))
    if entry is None:
        return None
    if entry.expires_at_monotonic <= now:
        _active_claim_cache_by_event.pop(entry.event_id, None)
        if _active_claim_cache_by_command.get(entry.command_id) is entry:
            _active_claim_cache_by_command.pop(entry.command_id, None)
        return None
    return entry

def _active_claim_cache_set(event_id: int, command_id: str, worker_id: str) -> None:
    now = time.monotonic()
    normalized_event_id = int(event_id)
    normalized_command_id = str(command_id)
    normalized_worker_id = str(worker_id)
    existing_for_event = _active_claim_cache_by_event.get(normalized_event_id)
    if existing_for_event is not None and existing_for_event.command_id != normalized_command_id:
        if _active_claim_cache_by_command.get(existing_for_event.command_id) is existing_for_event:
            _active_claim_cache_by_command.pop(existing_for_event.command_id, None)
    existing_for_command = _active_claim_cache_by_command.get(normalized_command_id)
    if existing_for_command is not None and existing_for_command.event_id != normalized_event_id:
        if _active_claim_cache_by_event.get(existing_for_command.event_id) is existing_for_command:
            _active_claim_cache_by_event.pop(existing_for_command.event_id, None)
    effective_ttl_seconds = max(1.0, min(_ACTIVE_CLAIMS_CACHE_TTL_SECONDS, _CLAIM_LEASE_SECONDS))
    entry = _ActiveClaimCacheEntry(event_id=normalized_event_id, command_id=normalized_command_id, worker_id=normalized_worker_id, expires_at_monotonic=now + effective_ttl_seconds, updated_at_monotonic=now)
    _active_claim_cache_by_event[entry.event_id] = entry
    _active_claim_cache_by_command[entry.command_id] = entry
    _active_claim_cache_prune(now, force=len(_active_claim_cache_by_event) > _ACTIVE_CLAIMS_CACHE_MAX_ENTRIES)

def _active_claim_cache_invalidate(*, command_id: Optional[str]=None, event_id: Optional[int]=None) -> None:
    if command_id:
        cached = _active_claim_cache_by_command.pop(str(command_id), None)
        if cached is not None and _active_claim_cache_by_event.get(cached.event_id) is cached:
            _active_claim_cache_by_event.pop(cached.event_id, None)
    if event_id is not None:
        cached = _active_claim_cache_by_event.pop(int(event_id), None)
        if cached is not None and _active_claim_cache_by_command.get(cached.command_id) is cached:
            _active_claim_cache_by_command.pop(cached.command_id, None)

__all__ = ['_active_claim_cache_by_event', '_active_claim_cache_by_command', '_active_claim_cache_last_prune_monotonic', '_active_claim_cache_prune', '_active_claim_cache_get', '_active_claim_cache_set', '_active_claim_cache_invalidate']
