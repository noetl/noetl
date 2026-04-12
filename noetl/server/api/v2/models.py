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
@dataclass(slots=True)
class _ActiveClaimCacheEntry:
    event_id: int
    command_id: str
    worker_id: str
    expires_at_monotonic: float
    updated_at_monotonic: float

@dataclass(slots=True)
class _BatchAcceptJob:
    request_id: str
    execution_id: int
    catalog_id: Optional[int]
    worker_id: Optional[str]
    idempotency_key: Optional[str]
    events: list['BatchEventItem']
    last_actionable_event: Optional[Event]
    last_actionable_evt_id: Optional[int]
    accepted_event_id: int
    accepted_at_monotonic: float

@dataclass(slots=True)
class _BatchAcceptanceResult:
    job: _BatchAcceptJob
    event_ids: list[int]
    duplicate: bool

class _BatchEnqueueError(RuntimeError):

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

class ExecuteRequest(BaseModel):
    """Request to start playbook execution."""
    path: Optional[str] = Field(None, description='Playbook catalog path')
    catalog_id: Optional[int] = Field(None, description='Catalog ID (alternative to path)')
    version: Optional[int] = Field(None, description='Specific version to execute (used with path)')
    payload: dict[str, Any] = Field(default_factory=dict, alias='workload', description='Input payload/workload')
    parent_execution_id: Optional[int] = Field(None, description='Parent execution ID')

    class Config:
        populate_by_name = True

    @model_validator(mode='after')
    def validate_path_or_catalog_id(self):
        if not self.path and (not self.catalog_id):
            raise ValueError("Either 'path' or 'catalog_id' must be provided")
        return self

StartExecutionRequest = ExecuteRequest

class ExecuteResponse(BaseModel):
    """Response for starting execution."""
    execution_id: str
    status: str
    commands_generated: int

class EventRequest(BaseModel):
    """Worker event - reports task completion with result."""
    execution_id: str
    step: str
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    meta: Optional[dict[str, Any]] = None
    worker_id: Optional[str] = None
    actionable: bool = True
    informative: bool = True

class EventResponse(BaseModel):
    """Response for event."""
    status: str
    event_id: int
    commands_generated: int

class BatchEventItem(BaseModel):
    """A single event within a batch."""
    step: str
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    actionable: bool = False
    informative: bool = True

class BatchEventRequest(BaseModel):
    """Batch of events for one execution - persisted in a single DB transaction."""
    execution_id: str
    events: list[BatchEventItem]
    worker_id: Optional[str] = None

    @model_validator(mode='after')
    def validate_batch_limits(self):
        event_count = len(self.events or [])
        if event_count > _BATCH_MAX_EVENTS_PER_REQUEST:
            raise ValueError(f'Batch contains {event_count} events; limit is {_BATCH_MAX_EVENTS_PER_REQUEST}')
        if event_count > 0:
            estimated_bytes = _estimate_json_size([evt.payload for evt in self.events])
            if estimated_bytes > _BATCH_MAX_PAYLOAD_BYTES:
                raise ValueError(f'Batch payload exceeds configured limit ({_BATCH_MAX_PAYLOAD_BYTES} bytes)')
        return self

class BatchEventResponse(BaseModel):
    """Response for async batch event acceptance."""
    status: str
    request_id: str
    event_ids: list[int] = Field(default_factory=list)
    commands_generated: int = 0
    queue_depth: int = 0
    duplicate: bool = False
    idempotency_key: Optional[str] = None

class ClaimRequest(BaseModel):
    """Request to claim a command."""
    worker_id: str

class ClaimResponse(BaseModel):
    """Response for successful claim with command details."""
    status: str
    event_id: int
    execution_id: int
    node_id: str
    node_name: str
    action: str
    context: dict[str, Any]
    meta: dict[str, Any]

__all__ = ['_ActiveClaimCacheEntry', '_BatchAcceptJob', '_BatchAcceptanceResult', '_BatchEnqueueError', 'ExecuteRequest', 'StartExecutionRequest', 'ExecuteResponse', 'EventRequest', 'EventResponse', 'BatchEventItem', 'BatchEventRequest', 'BatchEventResponse', 'ClaimRequest', 'ClaimResponse']
