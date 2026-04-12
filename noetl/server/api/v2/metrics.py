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
_batch_metrics: dict[str, float] = {'accepted_total': 0, 'enqueue_error_total': 0, 'ack_timeout_total': 0, 'queue_unavailable_total': 0, 'worker_unavailable_total': 0, 'processing_timeout_total': 0, 'processing_error_total': 0, 'enqueue_latency_seconds_sum': 0.0, 'enqueue_latency_seconds_count': 0, 'first_worker_claim_latency_seconds_sum': 0.0, 'first_worker_claim_latency_seconds_count': 0}

def _inc_batch_metric(name: str, amount: float=1.0) -> None:
    _batch_metrics[name] = float(_batch_metrics.get(name, 0.0)) + amount

def _observe_batch_metric(prefix: str, value: float) -> None:
    safe_value = max(0.0, float(value))
    _inc_batch_metric(f'{prefix}_sum', safe_value)
    _inc_batch_metric(f'{prefix}_count', 1.0)

def _batch_queue_depth() -> int:
    if _batch_accept_queue is None:
        return 0
    return _batch_accept_queue.qsize()

def get_batch_metrics_snapshot() -> dict[str, float]:
    """Export in-process batch acceptance metrics for /metrics endpoint."""
    snapshot = dict(_batch_metrics)
    snapshot['queue_depth'] = float(_batch_queue_depth())
    snapshot['worker_count'] = float(sum((1 for task in _batch_accept_workers_tasks if not task.done())))
    return snapshot

__all__ = ['_batch_metrics', '_inc_batch_metric', '_observe_batch_metric', '_batch_queue_depth', 'get_batch_metrics_snapshot']
