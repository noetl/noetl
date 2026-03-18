"""
NoETL API v2 - Pure Event Sourcing Architecture.

Single source of truth: noetl.event table
- event.result stores either inline data OR reference (kind: data|ref|refs)
- No queue tables, no projection tables
- All state derived from events
- NATS for command notifications only
"""

import os
import json
import time
import asyncio
import heapq
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
from noetl.claim_policy import decide_reclaim_for_existing_claim

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)

router = APIRouter(prefix="", tags=["api"])

# Global engine components
_playbook_repo: Optional[PlaybookRepo] = None
_state_store: Optional[StateStore] = None
_engine: Optional[ControlFlowEngine] = None
_nats_publisher: Optional[NATSCommandPublisher] = None
_CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS = float(
    os.getenv("NOETL_CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS", "0.25")
)
_CLAIM_LEASE_SECONDS = max(
    1.0,
    float(os.getenv("NOETL_COMMAND_CLAIM_LEASE_SECONDS", "120")),
)
_CLAIM_ACTIVE_RETRY_AFTER_SECONDS = max(
    1,
    int(os.getenv("NOETL_COMMAND_CLAIM_RETRY_AFTER_SECONDS", "2")),
)
_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS = max(
    0.01,
    float(os.getenv("NOETL_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS", "0.25")),
)
_BATCH_ACCEPT_QUEUE_MAXSIZE = max(
    1,
    int(os.getenv("NOETL_BATCH_ACCEPT_QUEUE_MAXSIZE", "1024")),
)
_BATCH_ACCEPT_WORKERS = max(
    0,
    int(os.getenv("NOETL_BATCH_ACCEPT_WORKERS", "1")),
)
_BATCH_PROCESSING_TIMEOUT_SECONDS = max(
    0.1,
    float(os.getenv("NOETL_BATCH_PROCESSING_TIMEOUT_SECONDS", "15.0")),
)
_BATCH_STATUS_STREAM_POLL_SECONDS = max(
    0.1,
    float(os.getenv("NOETL_BATCH_STATUS_STREAM_POLL_SECONDS", "0.5")),
)

_BATCH_FAILURE_ENQUEUE_TIMEOUT = "ack_timeout"
_BATCH_FAILURE_ENQUEUE_ERROR = "enqueue_error"
_BATCH_FAILURE_QUEUE_UNAVAILABLE = "queue_unavailable"
_BATCH_FAILURE_WORKER_UNAVAILABLE = "worker_unavailable"
_BATCH_FAILURE_PROCESSING_TIMEOUT = "processing_timeout"
_BATCH_FAILURE_PROCESSING_ERROR = "processing_error"


def _normalize_command_server_url(server_url: str) -> str:
    """Normalize notification server URL to host base without trailing '/api'."""
    normalized = (server_url or "").strip().rstrip("/")
    if normalized.endswith("/api"):
        normalized = normalized[:-4]
    return normalized


def _compute_retry_after(min_seconds: float = 1.0, max_seconds: float = 15.0) -> str:
    """
    Return Retry-After value (string seconds) based on actual server pool state.

    If the pool has waiters, the client should wait at least long enough for
    those to drain: roughly 0.5 s * (waiters + 1), capped at max_seconds.
    Returns a plain integer string as required by the HTTP spec.
    """
    try:
        stats = get_server_pool_stats()
        waiting = int(stats.get("requests_waiting", 0) or 0)
        available = int(stats.get("slots_available", 1) or 1)
        # If nothing is waiting and slots are free, a short retry is fine
        if waiting == 0 and available > 0:
            return str(int(min_seconds))
        # Each waiter adds ~0.5 s; extra penalty when no free slots at all
        estimated = min_seconds + 0.5 * (waiting + 1) + (1.0 if available == 0 else 0.0)
        return str(int(min(max(estimated, min_seconds), max_seconds)))
    except Exception:
        return str(int(min_seconds))


@router.get("/pool/status")
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
        return {
            "pool_min": 0, "pool_max": 0, "pool_size": 0,
            "pool_available": 0, "requests_waiting": 0,
            "utilization": 0.0, "slots_available": 0,
            "status": "unavailable",
        }
    return {**stats, "status": "ok"}


_CLAIM_WORKER_HEARTBEAT_STALE_SECONDS = max(
    5.0,
    float(os.getenv("NOETL_COMMAND_WORKER_HEARTBEAT_STALE_SECONDS", "30")),
)
_CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS = max(
    _CLAIM_LEASE_SECONDS,
    float(os.getenv("NOETL_COMMAND_CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS", "1800")),
)
_STATUS_VALUE_MAX_BYTES = max(
    256,
    int(os.getenv("NOETL_STATUS_VALUE_MAX_BYTES", "16384")),
)
_STATUS_PREVIEW_ITEMS = max(
    1,
    int(os.getenv("NOETL_STATUS_PREVIEW_ITEMS", "5")),
)
_ACTIVE_CLAIMS_CACHE_TTL_SECONDS = max(
    1.0,
    float(
        os.getenv(
            "NOETL_ACTIVE_CLAIMS_CACHE_TTL_SECONDS",
            str(_CLAIM_WORKER_HEARTBEAT_STALE_SECONDS),
        )
    ),
)
_ACTIVE_CLAIMS_CACHE_MAX_ENTRIES = max(
    128,
    int(os.getenv("NOETL_ACTIVE_CLAIMS_CACHE_MAX_ENTRIES", "20000")),
)
_ACTIVE_CLAIMS_CACHE_PRUNE_INTERVAL_SECONDS = max(
    0.1,
    float(os.getenv("NOETL_ACTIVE_CLAIMS_CACHE_PRUNE_INTERVAL_SECONDS", "1.0")),
)


@dataclass(slots=True)
class _ActiveClaimCacheEntry:
    event_id: int
    command_id: str
    worker_id: str
    expires_at_monotonic: float
    updated_at_monotonic: float


_active_claim_cache_by_event: dict[int, _ActiveClaimCacheEntry] = {}
_active_claim_cache_by_command: dict[str, _ActiveClaimCacheEntry] = {}
_active_claim_cache_last_prune_monotonic: float = 0.0


def _active_claim_cache_prune(
    now_monotonic: Optional[float] = None,
    *,
    force: bool = False,
) -> None:
    global _active_claim_cache_last_prune_monotonic
    now = now_monotonic if now_monotonic is not None else time.monotonic()
    if not force:
        if len(_active_claim_cache_by_event) <= _ACTIVE_CLAIMS_CACHE_MAX_ENTRIES and (
            now - _active_claim_cache_last_prune_monotonic
        ) < _ACTIVE_CLAIMS_CACHE_PRUNE_INTERVAL_SECONDS:
            return
    _active_claim_cache_last_prune_monotonic = now

    expired_event_ids = [
        event_id
        for event_id, entry in _active_claim_cache_by_event.items()
        if entry.expires_at_monotonic <= now
    ]
    for event_id in expired_event_ids:
        entry = _active_claim_cache_by_event.pop(event_id, None)
        if entry and _active_claim_cache_by_command.get(entry.command_id) is entry:
            _active_claim_cache_by_command.pop(entry.command_id, None)

    if len(_active_claim_cache_by_event) <= _ACTIVE_CLAIMS_CACHE_MAX_ENTRIES:
        return

    # Evict oldest entries by update time to bound memory.
    overflow = len(_active_claim_cache_by_event) - _ACTIVE_CLAIMS_CACHE_MAX_ENTRIES
    oldest_entries = heapq.nsmallest(
        overflow,
        _active_claim_cache_by_event.values(),
        key=lambda item: item.updated_at_monotonic,
    )
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
    # Fast-path stale guard: avoid returning expired entries between prune intervals.
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

    # Cache fast-path must never outlive reclaim eligibility; otherwise a stale
    # entry could return 409 before DB lease/heartbeat checks can reclaim.
    effective_ttl_seconds = max(
        1.0,
        min(_ACTIVE_CLAIMS_CACHE_TTL_SECONDS, _CLAIM_LEASE_SECONDS),
    )
    entry = _ActiveClaimCacheEntry(
        event_id=normalized_event_id,
        command_id=normalized_command_id,
        worker_id=normalized_worker_id,
        expires_at_monotonic=now + effective_ttl_seconds,
        updated_at_monotonic=now,
    )
    _active_claim_cache_by_event[entry.event_id] = entry
    _active_claim_cache_by_command[entry.command_id] = entry
    _active_claim_cache_prune(
        now,
        force=len(_active_claim_cache_by_event) > _ACTIVE_CLAIMS_CACHE_MAX_ENTRIES,
    )


def _active_claim_cache_invalidate(
    *,
    command_id: Optional[str] = None,
    event_id: Optional[int] = None,
) -> None:
    if command_id:
        cached = _active_claim_cache_by_command.pop(str(command_id), None)
        if cached is not None and _active_claim_cache_by_event.get(cached.event_id) is cached:
            _active_claim_cache_by_event.pop(cached.event_id, None)
    if event_id is not None:
        cached = _active_claim_cache_by_event.pop(int(event_id), None)
        if cached is not None and _active_claim_cache_by_command.get(cached.command_id) is cached:
            _active_claim_cache_by_command.pop(cached.command_id, None)


def _extract_event_command_id(req: "EventRequest") -> Optional[str]:
    payload = req.payload or {}
    meta = req.meta or {}

    candidates = [
        payload.get("command_id"),
        meta.get("command_id"),
    ]
    data_payload = payload.get("data")
    if isinstance(data_payload, dict):
        candidates.append(data_payload.get("command_id"))

    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


@dataclass(slots=True)
class _BatchAcceptJob:
    request_id: str
    execution_id: int
    catalog_id: Optional[int]
    worker_id: Optional[str]
    idempotency_key: Optional[str]
    events: list["BatchEventItem"]
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


_batch_accept_queue: Optional[asyncio.Queue[_BatchAcceptJob]] = None
_batch_accept_workers_tasks: list[asyncio.Task] = []
_batch_acceptor_lock: Optional[asyncio.Lock] = None

_batch_metrics: dict[str, float] = {
    "accepted_total": 0,
    "enqueue_error_total": 0,
    "ack_timeout_total": 0,
    "queue_unavailable_total": 0,
    "worker_unavailable_total": 0,
    "processing_timeout_total": 0,
    "processing_error_total": 0,
    "enqueue_latency_seconds_sum": 0.0,
    "enqueue_latency_seconds_count": 0,
    "first_worker_claim_latency_seconds_sum": 0.0,
    "first_worker_claim_latency_seconds_count": 0,
}


def _get_batch_acceptor_lock() -> asyncio.Lock:
    global _batch_acceptor_lock
    if _batch_acceptor_lock is None:
        _batch_acceptor_lock = asyncio.Lock()
    return _batch_acceptor_lock


def _inc_batch_metric(name: str, amount: float = 1.0) -> None:
    _batch_metrics[name] = float(_batch_metrics.get(name, 0.0)) + amount


def _observe_batch_metric(prefix: str, value: float) -> None:
    safe_value = max(0.0, float(value))
    _inc_batch_metric(f"{prefix}_sum", safe_value)
    _inc_batch_metric(f"{prefix}_count", 1.0)


def _batch_queue_depth() -> int:
    if _batch_accept_queue is None:
        return 0
    return _batch_accept_queue.qsize()


def _has_live_batch_workers() -> bool:
    return any(not task.done() for task in _batch_accept_workers_tasks)


def get_batch_metrics_snapshot() -> dict[str, float]:
    """Export in-process batch acceptance metrics for /metrics endpoint."""
    snapshot = dict(_batch_metrics)
    snapshot["queue_depth"] = float(_batch_queue_depth())
    snapshot["worker_count"] = float(sum(1 for task in _batch_accept_workers_tasks if not task.done()))
    return snapshot


async def ensure_batch_acceptor_started() -> bool:
    """Ensure in-process batch acceptor queue and workers are running."""
    global _batch_accept_queue

    if _BATCH_ACCEPT_WORKERS <= 0:
        return False

    lock = _get_batch_acceptor_lock()
    async with lock:
        if _batch_accept_queue is None:
            _batch_accept_queue = asyncio.Queue(maxsize=_BATCH_ACCEPT_QUEUE_MAXSIZE)

        # Clean up completed workers before scaling up.
        _batch_accept_workers_tasks[:] = [task for task in _batch_accept_workers_tasks if not task.done()]
        while len(_batch_accept_workers_tasks) < _BATCH_ACCEPT_WORKERS:
            worker_idx = len(_batch_accept_workers_tasks) + 1
            task = asyncio.create_task(
                _batch_accept_worker_loop(worker_idx),
                name=f"batch-acceptor-{worker_idx}",
            )
            _batch_accept_workers_tasks.append(task)

        return _has_live_batch_workers()


async def shutdown_batch_acceptor() -> None:
    """Stop in-process batch acceptor workers."""
    lock = _get_batch_acceptor_lock()
    async with lock:
        if not _batch_accept_workers_tasks:
            return
        tasks = list(_batch_accept_workers_tasks)
        _batch_accept_workers_tasks.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def get_engine():
    """Get or initialize engine."""
    global _playbook_repo, _state_store, _engine
    
    if _engine is None:
        _playbook_repo = PlaybookRepo()
        _state_store = StateStore(_playbook_repo)
        _engine = ControlFlowEngine(_playbook_repo, _state_store)
    
    return _engine


async def _invalidate_execution_state_cache(
    execution_id: str,
    reason: str,
    engine: Optional[ControlFlowEngine] = None,
) -> None:
    """Best-effort cache invalidation to recover from partial command issuance failures."""
    try:
        active_engine = engine or get_engine()
        await active_engine.state_store.invalidate_state(str(execution_id), reason=reason)
    except Exception as cache_error:
        logger.warning(
            "[STATE-CACHE-INVALIDATE] failed execution_id=%s reason=%s error=%s",
            execution_id,
            reason,
            cache_error,
        )


async def get_nats_publisher():
    """Get or initialize NATS publisher."""
    global _nats_publisher
    
    if _nats_publisher is None:
        from noetl.core.config import settings
        _nats_publisher = NATSCommandPublisher(
            nats_url=settings.nats_url,
            subject=settings.nats_subject
        )
        await _nats_publisher.connect()
        logger.info(f"NATS publisher initialized: {settings.nats_url}")
    
    return _nats_publisher


async def _next_snowflake_id(cur) -> int:
    """Generate a snowflake ID using the current DB cursor/connection."""
    await cur.execute("SELECT noetl.snowflake_id() AS snowflake_id")
    row = await cur.fetchone()
    if not row:
        raise RuntimeError("Failed to generate snowflake ID from database")
    value = row.get("snowflake_id") if isinstance(row, dict) else row[0]
    return int(value)


def _estimate_json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return len(str(value).encode("utf-8"))


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
            return {
                "_truncated": True,
                "_type": "dict",
                "_keys": len(items),
            }
        return compacted

    if isinstance(value, (list, tuple)):
        seq = list(value)
        compacted_list = [_compact_status_value(v, depth + 1) for v in seq[:_STATUS_PREVIEW_ITEMS]]
        if len(seq) > _STATUS_PREVIEW_ITEMS:
            compacted_list.append(f"... {len(seq) - _STATUS_PREVIEW_ITEMS} more")
        if _estimate_json_size(compacted_list) > _STATUS_VALUE_MAX_BYTES:
            return {
                "_truncated": True,
                "_type": "list",
                "_items": len(seq),
            }
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
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
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


# ============================================================================
# Request/Response Models
# ============================================================================

class ExecuteRequest(BaseModel):
    """Request to start execution for a catalog resource."""
    path: Optional[str] = Field(None, description="Playbook catalog path")
    catalog_id: Optional[int] = Field(None, description="Catalog ID (alternative to path)")
    version: Optional[int] = Field(None, description="Specific version to execute (used with path)")
    payload: dict[str, Any] = Field(default_factory=dict, alias="workload", description="Input payload/workload")
    resource_kind: Literal["playbook", "notebook"] = Field(
        default="playbook",
        alias="resource_type",
        description="Executable resource type. 'playbook' is currently supported; 'notebook' reserved.",
    )
    rerun_from_execution_id: Optional[int] = Field(
        None,
        description="Optional source execution ID to rerun. Uses original path/workload unless overridden.",
    )
    parent_execution_id: Optional[int] = Field(None, description="Parent execution ID")

    class Config:
        populate_by_name = True  # Allow both 'payload' and 'workload' field names

    @model_validator(mode='after')
    def validate_path_or_catalog_id(self):
        if not self.path and not self.catalog_id and not self.rerun_from_execution_id:
            raise ValueError("Either 'path', 'catalog_id', or 'rerun_from_execution_id' must be provided")
        return self


# Alias for backward compatibility with /api/run endpoint
StartExecutionRequest = ExecuteRequest


class ExecuteResponse(BaseModel):
    """Response for starting execution."""
    execution_id: str
    status: str
    commands_generated: int
    resource_kind: Literal["playbook", "notebook"] = "playbook"


class RerunRequest(BaseModel):
    """Request body for execution rerun."""
    path: Optional[str] = Field(None, description="Optional override path for rerun target")
    catalog_id: Optional[int] = Field(None, description="Optional override catalog ID")
    version: Optional[int] = Field(None, description="Optional version override when path is used")
    payload: dict[str, Any] = Field(default_factory=dict, alias="workload", description="Workload override")
    resource_kind: Literal["playbook", "notebook"] = Field(
        default="playbook",
        alias="resource_type",
        description="Executable resource type. 'playbook' is currently supported; 'notebook' reserved.",
    )
    parent_execution_id: Optional[int] = Field(None, description="Optional parent execution ID")

    class Config:
        populate_by_name = True


class EventRequest(BaseModel):
    """Worker event - reports task completion with result."""
    execution_id: str
    step: str
    name: str  # step.enter, call.done, step.exit
    payload: dict[str, Any] = Field(default_factory=dict)
    meta: Optional[dict[str, Any]] = None
    worker_id: Optional[str] = None
    # ResultRef pattern
    result_kind: Literal["data", "ref", "refs"] = "data"
    result_uri: Optional[str] = None  # For kind=ref
    event_ids: Optional[list[int]] = None  # For kind=refs
    # Control flags (stored in meta column)
    actionable: bool = True  # If True, server should take action (evaluate case, route)
    informative: bool = True  # If True, event is for logging/observability


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


class BatchEventResponse(BaseModel):
    """Response for async batch event acceptance."""
    status: str
    request_id: str
    event_ids: list[int] = Field(default_factory=list)
    commands_generated: int = 0
    queue_depth: int = 0
    duplicate: bool = False
    idempotency_key: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================


def _unwrap_result_payload(value: Any) -> Any:
    """
    Extract inline payload from result wrappers.

    Supports:
    - {"kind":"data","data":...}
    - {"result": {...}}
    - nested combinations of the above
    """
    current = value
    for _ in range(4):
        if not isinstance(current, dict):
            break
        if current.get("kind") in {"data", "ref", "refs"} and "data" in current:
            current = current.get("data")
            continue
        if "result" in current and isinstance(current.get("result"), dict):
            current = current.get("result")
            continue
        break
    return current


async def _resolve_rerun_seed(execution_id: int) -> tuple[str, Optional[int], dict[str, Any]]:
    """
    Resolve canonical rerun inputs from the source execution initialization event.

    Returns (path, catalog_id, workload).
    """
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT catalog_id, node_name, result
                FROM noetl.event
                WHERE execution_id = %s
                  AND event_type IN ('playbook.initialized', 'playbook_initialized')
                ORDER BY event_id ASC
                LIMIT 1
                """,
                (execution_id,),
            )
            row = await cur.fetchone()

    if not row:
        raise HTTPException(404, f"Source execution not found for rerun: {execution_id}")

    result_payload = _unwrap_result_payload(row.get("result"))
    if isinstance(result_payload, dict):
        rerun_path = (
            result_payload.get("playbook_path")
            or result_payload.get("path")
            or row.get("node_name")
        )
        workload = result_payload.get("workload", {})
    else:
        rerun_path = row.get("node_name")
        workload = {}

    if not isinstance(rerun_path, str) or not rerun_path:
        raise HTTPException(409, f"Execution {execution_id} is missing playbook path for rerun")
    if not isinstance(workload, dict):
        workload = {}

    return rerun_path, row.get("catalog_id"), workload

@router.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest) -> ExecuteResponse:
    """
    Start playbook execution.

    Creates playbook.initialized event, emits command.issued events.
    All state in event table - result column has kind: data|ref|refs.
    """
    try:
        engine = get_engine()

        if req.resource_kind != "playbook":
            raise HTTPException(
                501,
                f"Resource kind '{req.resource_kind}' is not yet supported for execution",
            )

        request_path = req.path
        request_catalog_id = req.catalog_id
        request_payload = dict(req.payload or {})

        if req.rerun_from_execution_id is not None:
            rerun_path, rerun_catalog_id, rerun_payload = await _resolve_rerun_seed(
                req.rerun_from_execution_id
            )
            request_path = request_path or rerun_path
            if request_catalog_id is None:
                request_catalog_id = rerun_catalog_id
            # Caller payload overrides source workload for deterministic replay tweaks.
            merged_payload = dict(rerun_payload or {})
            merged_payload.update(request_payload)
            request_payload = merged_payload

        # Log incoming request for debugging version selection
        logger.debug(
            "[EXECUTE] Request: path=%s catalog_id=%s version=%s rerun_from=%s resource_kind=%s",
            request_path,
            request_catalog_id,
            req.version,
            req.rerun_from_execution_id,
            req.resource_kind,
        )

        # Resolve catalog
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                if request_catalog_id:
                    await cur.execute(
                        "SELECT path, catalog_id FROM noetl.catalog WHERE catalog_id = %s",
                        (request_catalog_id,)
                    )
                    row = await cur.fetchone()
                    if not row:
                        raise HTTPException(404, f"Playbook not found: catalog_id={request_catalog_id}")
                    path, catalog_id = row['path'], row['catalog_id']
                else:
                    # If version specified, look up exact path + version
                    # Otherwise, get the latest version
                    if req.version is not None:
                        await cur.execute(
                            "SELECT catalog_id, path, version FROM noetl.catalog WHERE path = %s AND version = %s",
                            (request_path, req.version)
                        )
                        row = await cur.fetchone()
                        if not row:
                            raise HTTPException(404, f"Playbook not found: {request_path} v{req.version}")
                    else:
                        await cur.execute(
                            "SELECT catalog_id, path, version FROM noetl.catalog WHERE path = %s ORDER BY version DESC LIMIT 1",
                            (request_path,)
                        )
                        row = await cur.fetchone()
                        if not row:
                            raise HTTPException(404, f"Playbook not found: {request_path}")
                    catalog_id, path = row['catalog_id'], row['path']
                    logger.debug(f"[EXECUTE] Resolved playbook: {path} v{row.get('version', '?')} -> catalog_id={catalog_id}")
        
        # Start execution
        execution_id, commands = await engine.start_execution(
            path, request_payload, catalog_id, req.parent_execution_id
        )
        
        # Get root event
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT event_id FROM noetl.event WHERE execution_id = %s AND event_type = 'playbook.initialized' LIMIT 1",
                    (int(execution_id),)
                )
                row = await cur.fetchone()
                root_event_id = row['event_id'] if row else None
        
        # Emit command.issued events
        nats_pub = await get_nats_publisher()
        server_url = _normalize_command_server_url(
            os.getenv("NOETL_SERVER_URL", "http://noetl.noetl.svc.cluster.local:8082")
        )
        command_events = []
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                for cmd in commands:
                    cmd_suffix = await _next_snowflake_id(cur)
                    cmd_id = f"{execution_id}:{cmd.step}:{cmd_suffix}"
                    evt_id = await _next_snowflake_id(cur)
                    
                    # Build context for command execution (passes execution parameters, not results)
                    context = {
                        "tool_config": cmd.tool.config,
                        "args": cmd.args or {},
                        "render_context": cmd.render_context,
                        "next_targets": cmd.next_targets,  # Canonical v2: routing via next[].when
                        "pipeline": cmd.pipeline,  # Canonical v2: task pipeline
                        "spec": cmd.spec.model_dump() if cmd.spec else None,  # Step behavior (next_mode)
                    }
                    meta = {
                        "command_id": cmd_id,
                        "step": cmd.step,
                        "tool_kind": cmd.tool.kind,
                        "max_attempts": cmd.max_attempts or 3,
                        "attempt": 1,
                        "execution_id": str(execution_id),
                        "catalog_id": str(catalog_id),
                    }
                    if cmd.metadata:
                        meta.update({k: v for k, v in cmd.metadata.items() if v is not None})

                    # Store actionable flag in meta column (not separate column)
                    meta["actionable"] = True

                    await cur.execute("""
                        INSERT INTO noetl.event (
                            event_id, execution_id, catalog_id, event_type,
                            node_id, node_name, node_type, status,
                            context, meta, parent_event_id, parent_execution_id,
                            created_at
                        ) VALUES (
                            %(event_id)s, %(execution_id)s, %(catalog_id)s, %(event_type)s,
                            %(node_id)s, %(node_name)s, %(node_type)s, %(status)s,
                            %(context)s, %(meta)s, %(parent_event_id)s, %(parent_execution_id)s,
                            %(created_at)s
                        )
                    """, {
                        "event_id": evt_id,
                        "execution_id": int(execution_id),
                        "catalog_id": catalog_id,
                        "event_type": "command.issued",
                        "node_id": cmd.step,
                        "node_name": cmd.step,
                        "node_type": cmd.tool.kind,
                        "status": "PENDING",
                        "context": Json(context),
                        "meta": Json(meta),
                        "parent_event_id": root_event_id,
                        "parent_execution_id": req.parent_execution_id,
                        "created_at": datetime.now(timezone.utc)
                    })
                    command_events.append((evt_id, cmd_id, cmd))
            
            await conn.commit()
        
        # NATS notifications
        for evt_id, cmd_id, cmd in command_events:
            await nats_pub.publish_command(
                execution_id=int(execution_id),
                event_id=evt_id,
                command_id=cmd_id,
                step=cmd.step,
                server_url=server_url
            )
        
        return ExecuteResponse(
            execution_id=execution_id,
            status="started",
            commands_generated=len(commands),
            resource_kind=req.resource_kind,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"execute failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# Function alias for backward compatibility with /api/run endpoint
async def start_execution(req: ExecuteRequest) -> ExecuteResponse:
    """
    Start playbook execution - function wrapper for endpoint.
    Used by /api/run/playbook endpoint for backward compatibility.
    """
    return await execute(req)


@router.post("/executions/{execution_id}/rerun", response_model=ExecuteResponse)
async def rerun_execution(execution_id: int, req: Optional[RerunRequest] = None) -> ExecuteResponse:
    """
    Rerun an existing execution using canonical execute semantics.

    - Reuses source execution playbook path + workload by default.
    - Allows workload override via request body.
    - Supports explicit resource_kind (currently only playbook).
    """
    if req is None:
        execute_req = ExecuteRequest(rerun_from_execution_id=execution_id)
    else:
        execute_req = ExecuteRequest(
            path=req.path,
            catalog_id=req.catalog_id,
            version=req.version,
            payload=req.payload,
            resource_kind=req.resource_kind,
            parent_execution_id=req.parent_execution_id,
            rerun_from_execution_id=execution_id,
        )
    return await execute(execute_req)


@router.get("/commands/{event_id}")
async def get_command(event_id: int):
    """
    Get command details from command.issued event.
    Workers call this to fetch command config after NATS notification.

    DEPRECATED: Use POST /commands/{event_id}/claim instead for atomic claim+fetch.
    """
    try:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("""
                    SELECT execution_id, node_name as step, node_type as tool_kind, context, meta
                    FROM noetl.event
                    WHERE event_id = %s AND event_type = 'command.issued'
                """, (event_id,))
                row = await cur.fetchone()

                if not row:
                    raise HTTPException(404, f"command.issued event not found: {event_id}")

                # Context already contains command execution parameters
                context = row['context'] or {}

                return {
                    "execution_id": row['execution_id'],
                    "node_id": row['step'],
                    "node_name": row['step'],
                    "action": row['tool_kind'],
                    "context": context,  # Worker expects this
                    "meta": row['meta']
                }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_command failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


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
    action: str  # tool_kind
    context: dict[str, Any]
    meta: dict[str, Any]


@router.post("/commands/{event_id}/claim", response_model=ClaimResponse)
async def claim_command(event_id: int, req: ClaimRequest):
    """
    Atomically claim a command and return its details.

    Combines claim + fetch into single operation:
    1. Acquires advisory lock on command_id
    2. Checks if already claimed
    3. If not claimed, inserts command.claimed event
    4. Returns command details from command.issued event

    Returns 409 Conflict if already claimed by another worker.
    Returns 404 if command.issued event not found.
    """
    try:
        cached_claim = _active_claim_cache_get(event_id)
        if cached_claim and cached_claim.worker_id != req.worker_id:
            raise HTTPException(
                409,
                detail={
                    "code": "active_claim",
                    "message": f"Command already claimed by {cached_claim.worker_id}",
                    "worker_id": cached_claim.worker_id,
                    "claim_policy": "cache_fast_path",
                },
                headers={"Retry-After": str(max(1, _CLAIM_ACTIVE_RETRY_AFTER_SECONDS))},
            )

        # Fail fast under DB saturation so workers can retry without long hangs.
        async with get_pool_connection(timeout=_CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS) as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # First, fetch command.issued event to get command details
                await cur.execute("""
                    SELECT execution_id, catalog_id, node_name as step, node_type as tool_kind,
                           context, meta
                    FROM noetl.event
                    WHERE event_id = %s AND event_type = 'command.issued'
                """, (event_id,))
                cmd_row = await cur.fetchone()

                if not cmd_row:
                    raise HTTPException(404, f"command.issued event not found: {event_id}")

                execution_id = cmd_row['execution_id']
                catalog_id = cmd_row['catalog_id']
                step = cmd_row['step']
                tool_kind = cmd_row['tool_kind']
                context = cmd_row['context'] or {}
                meta = cmd_row['meta'] or {}
                command_id = meta.get('command_id', f"{execution_id}:{step}:{event_id}")

                # If command is already terminal, no further claim attempts are needed.
                await cur.execute("""
                    SELECT event_type
                    FROM noetl.event
                    WHERE execution_id = %s
                      AND event_type IN ('command.completed', 'command.failed')
                      AND (meta->>'command_id' = %s OR (result->'data'->>'command_id' = %s))
                    ORDER BY event_id DESC
                    LIMIT 1
                """, (execution_id, command_id, command_id))
                terminal_row = await cur.fetchone()
                if terminal_row:
                    _active_claim_cache_invalidate(command_id=command_id, event_id=event_id)
                    raise HTTPException(
                        409,
                        detail={
                            "code": "already_terminal",
                            "message": "Command already reached a terminal state",
                            "event_type": terminal_row.get("event_type"),
                        },
                    )

                # Check if execution is cancelled FIRST (before claiming)
                await cur.execute("""
                    SELECT 1 FROM noetl.event
                    WHERE execution_id = %s AND event_type = 'execution.cancelled'
                    LIMIT 1
                """, (execution_id,))
                if await cur.fetchone():
                    _active_claim_cache_invalidate(command_id=command_id, event_id=event_id)
                    raise HTTPException(
                        409,
                        detail={
                            "code": "execution_cancelled",
                            "message": "Execution has been cancelled",
                        },
                    )

                # Acquire advisory lock on command_id hash
                await cur.execute("""
                    SELECT pg_try_advisory_xact_lock(hashtext(%s)::bigint) as lock_acquired
                """, (command_id,))
                lock_result = await cur.fetchone()

                if not lock_result or not lock_result.get('lock_acquired'):
                    raise HTTPException(
                        409,
                        detail={
                            "code": "active_claim",
                            "message": "Command is being claimed by another worker",
                        },
                        headers={
                            "Retry-After": str(max(1, _CLAIM_ACTIVE_RETRY_AFTER_SECONDS))
                        },
                    )

                # Check if already claimed
                await cur.execute("""
                    SELECT event_id, worker_id, meta, created_at FROM noetl.event
                    WHERE execution_id = %s
                      AND event_type = 'command.claimed'
                      AND (meta->>'command_id' = %s OR (result->'data'->>'command_id' = %s))
                    ORDER BY event_id DESC
                    LIMIT 1
                """, (execution_id, command_id, command_id))
                existing = await cur.fetchone()

                stale_reclaim = False
                reclaimed_from_worker = None
                reclaimed_reason = None
                if existing:
                    existing_event_id = existing.get("event_id")
                    existing_worker = existing.get('worker_id') or (existing.get('meta') or {}).get('worker_id')
                    created_at = existing.get("created_at")
                    claim_age_seconds = 0.0
                    if isinstance(created_at, datetime):
                        # noetl.event.created_at is TIMESTAMP (naive). Normalize to UTC
                        # before age calculation so lease checks do not fail with tz mismatch.
                        created_at_dt = created_at
                        if created_at_dt.tzinfo is None:
                            created_at_dt = created_at_dt.replace(tzinfo=timezone.utc)
                        claim_age_seconds = max(
                            0.0,
                            (datetime.now(created_at_dt.tzinfo) - created_at_dt).total_seconds(),
                        )

                    if existing_worker and existing_worker != req.worker_id:
                        worker_runtime_status = None
                        worker_heartbeat_age = None
                        try:
                            await cur.execute(
                                """
                                SELECT status, heartbeat
                                FROM noetl.runtime
                                WHERE kind = 'worker_pool' AND name = %s
                                ORDER BY updated_at DESC
                                LIMIT 1
                                """,
                                (existing_worker,),
                            )
                            runtime_row = await cur.fetchone()
                            if runtime_row:
                                worker_runtime_status = (runtime_row.get("status") or "").lower()
                                heartbeat_ts = runtime_row.get("heartbeat")
                                if isinstance(heartbeat_ts, datetime):
                                    heartbeat_dt = heartbeat_ts
                                    if heartbeat_dt.tzinfo is None:
                                        heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
                                    worker_heartbeat_age = max(
                                        0.0,
                                        (datetime.now(heartbeat_dt.tzinfo) - heartbeat_dt).total_seconds(),
                                    )
                        except Exception:
                            # Runtime table lookup is best-effort; fallback to lease-age semantics.
                            logger.debug(
                                "[CLAIM] Runtime status lookup failed for worker=%s",
                                existing_worker,
                                exc_info=True,
                            )

                        decision = decide_reclaim_for_existing_claim(
                            existing_worker=existing_worker,
                            requesting_worker=req.worker_id,
                            claim_age_seconds=claim_age_seconds,
                            lease_seconds=_CLAIM_LEASE_SECONDS,
                            worker_runtime_status=worker_runtime_status,
                            worker_heartbeat_age_seconds=worker_heartbeat_age,
                            heartbeat_stale_seconds=_CLAIM_WORKER_HEARTBEAT_STALE_SECONDS,
                            healthy_worker_hard_timeout_seconds=_CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS,
                        )

                        if decision.reclaim:
                            stale_reclaim = True
                            reclaimed_from_worker = existing_worker
                            reclaimed_reason = decision.reason or "lease_expired"
                            logger.warning(
                                "[CLAIM] Reclaiming command %s from worker=%s age=%.3fs reason=%s "
                                "(lease=%.3fs heartbeat_age=%.3fs status=%s)",
                                command_id,
                                existing_worker,
                                claim_age_seconds,
                                reclaimed_reason,
                                _CLAIM_LEASE_SECONDS,
                                worker_heartbeat_age or -1.0,
                                worker_runtime_status,
                            )
                        else:
                            retry_after = _CLAIM_ACTIVE_RETRY_AFTER_SECONDS
                            if decision.retry_reason == "lease_active":
                                retry_after = max(
                                    1,
                                    min(
                                        _CLAIM_ACTIVE_RETRY_AFTER_SECONDS,
                                        int(max(1.0, _CLAIM_LEASE_SECONDS - claim_age_seconds)),
                                    ),
                                )
                            _active_claim_cache_set(event_id, command_id, existing_worker)
                            raise HTTPException(
                                409,
                                detail={
                                    "code": "active_claim",
                                    "message": f"Command already claimed by {existing_worker}",
                                    "worker_id": existing_worker,
                                    "claim_event_id": existing_event_id,
                                    "age_seconds": round(claim_age_seconds, 3),
                                    "lease_seconds": _CLAIM_LEASE_SECONDS,
                                    "hard_timeout_seconds": _CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS,
                                    "claim_policy": decision.retry_reason,
                                    "worker_status": worker_runtime_status,
                                    "worker_heartbeat_age_seconds": (
                                        round(worker_heartbeat_age, 3)
                                        if worker_heartbeat_age is not None
                                        else None
                                    ),
                                },
                                headers={"Retry-After": str(retry_after)},
                            )
                    if existing_worker and existing_worker == req.worker_id:
                        await cur.execute(
                            """
                            SELECT event_type FROM noetl.event
                            WHERE execution_id = %s
                              AND event_type IN ('command.started', 'command.completed', 'command.failed')
                              AND (meta->>'command_id' = %s OR (result->'data'->>'command_id' = %s))
                            ORDER BY event_id DESC
                            LIMIT 1
                            """,
                            (execution_id, command_id, command_id),
                        )
                        same_worker_latest = await cur.fetchone()
                        latest_event_type = (same_worker_latest or {}).get("event_type")
                        if latest_event_type == "command.started":
                            _active_claim_cache_set(event_id, command_id, existing_worker)
                            raise HTTPException(
                                409,
                                detail={
                                    "code": "active_claim",
                                    "message": f"Command already running on {existing_worker}",
                                    "worker_id": existing_worker,
                                    "claim_event_id": existing_event_id,
                                    "age_seconds": round(claim_age_seconds, 3),
                                    "lease_seconds": _CLAIM_LEASE_SECONDS,
                                    "hard_timeout_seconds": _CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS,
                                    "claim_policy": "same_worker_running",
                                    "worker_status": "running",
                                },
                                headers={"Retry-After": str(_CLAIM_ACTIVE_RETRY_AFTER_SECONDS)},
                            )
                    # Already claimed by same worker - idempotent, return command details
                    if not stale_reclaim:
                        _active_claim_cache_set(event_id, command_id, req.worker_id)
                        return ClaimResponse(
                            status="ok",
                            event_id=event_id,
                            execution_id=execution_id,
                            node_id=step,
                            node_name=step,
                            action=tool_kind,
                            context=context,
                            meta=meta
                        )

                # Not claimed yet - insert claim event
                claim_evt_id = await _next_snowflake_id(cur)
                claim_meta = {
                    "command_id": command_id,
                    "worker_id": req.worker_id,
                    "actionable": False,
                    "informative": True,
                }
                if stale_reclaim:
                    claim_meta["reclaimed"] = True
                    claim_meta["reclaimed_from_worker"] = reclaimed_from_worker
                    if reclaimed_reason:
                        claim_meta["reclaimed_reason"] = reclaimed_reason
                result_obj = {"kind": "data", "data": {"command_id": command_id}}

                await cur.execute("""
                    INSERT INTO noetl.event (
                        event_id, execution_id, catalog_id, event_type,
                        node_id, node_name, status, result, meta, worker_id, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    claim_evt_id, execution_id, catalog_id, "command.claimed",
                    step, step, "RUNNING",
                    Json(result_obj), Json(claim_meta), req.worker_id, datetime.now(timezone.utc)
                ))
                await conn.commit()
                _active_claim_cache_set(event_id, command_id, req.worker_id)

                logger.info(f"[CLAIM] Command {command_id} claimed by {req.worker_id} (event_id={claim_evt_id})")

                return ClaimResponse(
                    status="ok",
                    event_id=event_id,
                    execution_id=execution_id,
                    node_id=step,
                    node_name=step,
                    action=tool_kind,
                    context=context,
                    meta=meta
                )

    except HTTPException:
        raise
    except PoolTimeout:
        retry_after = _compute_retry_after()
        logger.warning(
            "[CLAIM] DB pool saturated for event_id=%s (acquire_timeout=%.3fs) retry_after=%ss",
            event_id,
            _CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS,
            retry_after,
        )
        raise HTTPException(
            status_code=503,
            detail={"code": "pool_saturated", "message": "Database temporarily overloaded; retry shortly"},
            headers={"Retry-After": retry_after},
        )
    except Exception as e:
        logger.error(f"claim_command failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/events", response_model=EventResponse)
async def handle_event(req: EventRequest) -> EventResponse:
    """
    Handle worker event.
    
    Worker reports completion with result (inline or ref).
    Engine evaluates case/when/then and generates next commands.
    
    CRITICAL: Only process through engine for events that drive workflow:
    - step.exit: Step completed, evaluate case rules and generate next commands
    - call.done: Action completed, may trigger case rules
    - call.error: Action failed, may trigger error handling
    - command.failed: Command-level failure, must emit terminal failure lifecycle if unhandled
    - loop.item/loop.done: Loop iteration events
    
    Skip engine for administrative events:
    - command.claimed: Just persist, don't process
    - command.started: Just persist, don't process
    - command.completed: Already processed by worker
    - step.enter: Just marks step started
    """
    engine: Optional[ControlFlowEngine] = None
    commands_generated = False
    try:
        engine = get_engine()
        
        # Events that should NOT trigger engine processing
        # These are administrative events that just need to be persisted
        skip_engine_events = {
            "command.claimed", "command.started", "command.completed",
            "step.enter"
        }
        
        # For command.claimed, use fully atomic claiming with advisory lock + insert in same transaction
        if req.name == "command.claimed":
            command_id = req.payload.get("command_id") or (req.meta or {}).get("command_id")
            if command_id:
                async with get_pool_connection() as conn:
                    async with conn.cursor(row_factory=dict_row) as cur:
                        evt_id = await _next_snowflake_id(cur)
                        # Use advisory lock on command_id hash to prevent race conditions
                        # pg_try_advisory_xact_lock returns true if lock acquired, false if already locked
                        await cur.execute("""
                            SELECT pg_try_advisory_xact_lock(hashtext(%s)::bigint) as lock_acquired
                        """, (command_id,))
                        lock_result = await cur.fetchone()

                        if not lock_result or not lock_result.get('lock_acquired'):
                            # Another transaction has the lock - command is being claimed
                            logger.warning(f"[CLAIM-REJECT] Command {command_id} lock held by another worker, rejecting claim from {req.worker_id}")
                            raise HTTPException(409, f"Command already being claimed by another worker")

                        # Lock acquired - now check if already claimed
                        await cur.execute("""
                            SELECT worker_id, meta FROM noetl.event
                            WHERE execution_id = %s
                              AND event_type = 'command.claimed'
                              AND (meta->>'command_id' = %s OR (result->'data'->>'command_id' = %s))
                            LIMIT 1
                        """, (int(req.execution_id), command_id, command_id))
                        existing = await cur.fetchone()

                        if existing:
                            existing_worker = existing.get('worker_id') or (existing.get('meta') or {}).get('worker_id')
                            if existing_worker and existing_worker != req.worker_id:
                                # Command already claimed by another worker - reject
                                logger.warning(f"[CLAIM-REJECT] Command {command_id} already claimed by {existing_worker}, rejecting claim from {req.worker_id}")
                                raise HTTPException(409, f"Command already claimed by {existing_worker}")
                            else:
                                # Already claimed by SAME worker - idempotent success
                                logger.info(f"[CLAIM-IDEMPOTENT] Command {command_id} already claimed by SAME worker {req.worker_id}, returning success")
                                return EventResponse(status="ok", event_id=0, commands_generated=0)

                        # Not claimed yet - insert the claim event within the same transaction (while lock is held)
                        await cur.execute(
                            "SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1",
                            (int(req.execution_id),)
                        )
                        row = await cur.fetchone()
                        catalog_id = row['catalog_id'] if row else None

                        meta_obj = dict(req.meta or {})
                        meta_obj["actionable"] = req.actionable
                        meta_obj["informative"] = req.informative
                        meta_obj["command_id"] = command_id
                        if req.worker_id:
                            meta_obj["worker_id"] = req.worker_id

                        result_obj = {"kind": "data", "data": req.payload}

                        await cur.execute("""
                            INSERT INTO noetl.event (
                                event_id, execution_id, catalog_id, event_type,
                                node_id, node_name, status, result, meta, worker_id, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            evt_id, int(req.execution_id), catalog_id, req.name,
                            req.step, req.step, "RUNNING",
                            Json(result_obj), Json(meta_obj), req.worker_id, datetime.now(timezone.utc)
                        ))
                        await conn.commit()

                        logger.info(f"[CLAIM-SUCCESS] Command {command_id} claimed by worker {req.worker_id}")
                        return EventResponse(status="ok", event_id=evt_id, commands_generated=0)

        # Build result based on kind
        if req.result_kind == "ref" and req.result_uri:
            result_obj = {
                "kind": "ref",
                "store_tier": "gcs" if req.result_uri.startswith("gs://") else 
                              "s3" if req.result_uri.startswith("s3://") else "artifact",
                "logical_uri": req.result_uri,
            }
        elif req.result_kind == "refs" and req.event_ids:
            result_obj = {
                "kind": "refs",
                "event_ids": req.event_ids,
                "total_parts": len(req.event_ids),
            }
        else:
            result_obj = {
                "kind": "data",
                "data": req.payload,
            }
        
        # Persist worker event
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                evt_id = await _next_snowflake_id(cur)
                await cur.execute(
                    "SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1",
                    (int(req.execution_id),)
                )
                row = await cur.fetchone()
                catalog_id = row['catalog_id'] if row else None
                
                # Store control flags in meta column (not separate columns)
                meta_obj = dict(req.meta or {})
                meta_obj["actionable"] = req.actionable
                meta_obj["informative"] = req.informative
                if req.worker_id:
                    meta_obj["worker_id"] = req.worker_id
                
                # Determine status based on event name
                # "error"/"failed" -> FAILED, "done"/"exit"/"completed" -> COMPLETED, else -> RUNNING
                if "error" in req.name or "failed" in req.name:
                    status = "FAILED"
                elif "done" in req.name or "exit" in req.name or "completed" in req.name:
                    status = "COMPLETED"
                else:
                    status = "RUNNING"

                await cur.execute("""
                    INSERT INTO noetl.event (
                        event_id, execution_id, catalog_id, event_type,
                        node_id, node_name, status, result, meta, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    evt_id, int(req.execution_id), catalog_id, req.name,
                    req.step, req.step, status,
                    Json(result_obj), Json(meta_obj), datetime.now(timezone.utc)
                ))
                await conn.commit()

        if req.name in {"command.completed", "command.failed"}:
            command_id = _extract_event_command_id(req)
            if command_id:
                _active_claim_cache_invalidate(command_id=command_id)
        
        # Process through engine
        event = Event(
            execution_id=req.execution_id,
            step=req.step,
            name=req.name,
            payload=req.payload,
            meta=req.meta or {},
            timestamp=datetime.now(timezone.utc),
            worker_id=req.worker_id,
            attempt=(req.meta or {}).get("attempt", 1)
        )
        
        # CRITICAL: Only process through engine for workflow-driving events
        # Skip engine for administrative events to prevent duplicate command generation
        commands = []
        if req.name not in skip_engine_events:
            # Pass already_persisted=True because we already persisted the event above
            commands = await engine.handle_event(event, already_persisted=True)
            commands_generated = bool(commands)
            logger.debug(f"[ENGINE] Processed {req.name} for step {req.step}, generated {len(commands)} commands")
        else:
            logger.debug(f"[ENGINE] Skipped engine for administrative event {req.name}")
        
        # Emit command.issued for next steps
        nats_pub = await get_nats_publisher()
        server_url = _normalize_command_server_url(
            os.getenv("NOETL_SERVER_URL", "http://noetl.noetl.svc.cluster.local:8082")
        )
        command_events = []
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                for cmd in commands:
                    await cur.execute(
                        "SELECT catalog_id, parent_execution_id FROM noetl.event WHERE execution_id = %s LIMIT 1",
                        (int(cmd.execution_id),)
                    )
                    row = await cur.fetchone()
                    cat_id = row['catalog_id'] if row else catalog_id
                    parent_exec = row['parent_execution_id'] if row else None
                    
                    cmd_suffix = await _next_snowflake_id(cur)
                    cmd_id = f"{cmd.execution_id}:{cmd.step}:{cmd_suffix}"
                    new_evt_id = await _next_snowflake_id(cur)
                    
                    # Build context for retry command (command execution parameters)
                    context = {
                        "tool_config": cmd.tool.config,
                        "args": cmd.args or {},
                        "render_context": cmd.render_context,
                        "next_targets": cmd.next_targets,  # Canonical v2: routing via next[].when
                        "pipeline": cmd.pipeline,  # Canonical v2: task pipeline
                        "spec": cmd.spec.model_dump() if cmd.spec else None,  # Step behavior (next_mode)
                    }
                    meta = {
                        "command_id": cmd_id,
                        "step": cmd.step,
                        "tool_kind": cmd.tool.kind,
                        "triggered_by": req.name,
                        "trigger_step": req.step,
                        "actionable": True,  # Store in meta, not separate column
                    }
                    if cmd.metadata:
                        meta.update({k: v for k, v in cmd.metadata.items() if v is not None})
                    
                    await cur.execute("""
                        INSERT INTO noetl.event (
                            event_id, execution_id, catalog_id, event_type,
                            node_id, node_name, node_type, status,
                            context, meta, parent_event_id, parent_execution_id,
                            created_at
                        ) VALUES (
                            %(event_id)s, %(execution_id)s, %(catalog_id)s, %(event_type)s,
                            %(node_id)s, %(node_name)s, %(node_type)s, %(status)s,
                            %(context)s, %(meta)s, %(parent_event_id)s, %(parent_execution_id)s,
                            %(created_at)s
                        )
                    """, {
                        "event_id": new_evt_id,
                        "execution_id": int(cmd.execution_id),
                        "catalog_id": cat_id,
                        "event_type": "command.issued",
                        "node_id": cmd.step,
                        "node_name": cmd.step,
                        "node_type": cmd.tool.kind,
                        "status": "PENDING",
                        "context": Json(context),
                        "meta": Json(meta),
                        "parent_event_id": evt_id,
                        "parent_execution_id": parent_exec,
                        "created_at": datetime.now(timezone.utc)
                    })
                    command_events.append((new_evt_id, cmd_id, cmd))
                
                await conn.commit()
        
        for new_evt_id, cmd_id, cmd in command_events:
            await nats_pub.publish_command(
                execution_id=int(cmd.execution_id),
                event_id=new_evt_id,
                command_id=cmd_id,
                step=cmd.step,
                server_url=server_url
            )
        
        # Trigger orchestrator for workflow progression
        if req.name == "command.completed" and req.step.lower() != "end":
            try:
                from .run.orchestrator import evaluate_execution
                await evaluate_execution(
                    execution_id=str(req.execution_id),
                    trigger_event_type="command.completed",
                    trigger_event_id=str(evt_id)
                )
            except ImportError:
                logger.debug("Orchestrator module not available, skipping for command.completed")
            except Exception as e:
                logger.warning(f"Orchestrator error: {e}")

        # Evict completed executions from cache to free memory
        # Terminal events indicate execution is done and can be cleaned up
        terminal_events = {
            "playbook.completed", "playbook.failed",
            "workflow.completed", "workflow.failed",
            "execution.cancelled"
        }
        if req.name in terminal_events:
            try:
                await engine.state_store.evict_completed(req.execution_id)
                logger.debug(f"Evicted execution {req.execution_id} from cache after {req.name}")
            except Exception as e:
                logger.warning(f"Failed to evict execution {req.execution_id} from cache: {e}")

        return EventResponse(status="ok", event_id=evt_id, commands_generated=len(commands))
    
    except PoolTimeout:
        if engine is not None and commands_generated:
            await _invalidate_execution_state_cache(
                req.execution_id,
                reason="command_issue_pool_timeout",
                engine=engine,
            )
        retry_after = _compute_retry_after()
        logger.warning("[EVENTS] DB pool saturated while persisting %s for step %s retry_after=%ss", req.name, req.step, retry_after)
        raise HTTPException(
            status_code=503,
            detail={"code": "pool_saturated", "message": "Database temporarily overloaded; retry shortly"},
            headers={"Retry-After": retry_after},
        )
    except Exception as e:
        if engine is not None and commands_generated:
            await _invalidate_execution_state_cache(
                req.execution_id,
                reason=f"command_issue_failed:{type(e).__name__}",
                engine=engine,
            )
        logger.error(f"handle_event failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


def _status_from_event_name(event_name: str) -> str:
    lowered = event_name.lower()
    if "error" in lowered or "failed" in lowered:
        return "FAILED"
    if "done" in lowered or "exit" in lowered or "completed" in lowered:
        return "COMPLETED"
    return "RUNNING"


async def _persist_batch_status_event(
    execution_id: int,
    catalog_id: Optional[int],
    request_id: str,
    worker_id: Optional[str],
    idempotency_key: Optional[str],
    event_type: str,
    status: str,
    payload: dict[str, Any],
    error: Optional[str] = None,
) -> None:
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            evt_id = await _next_snowflake_id(cur)
            meta_obj: dict[str, Any] = {
                "batch_request_id": request_id,
                "actionable": False,
                "informative": True,
            }
            if worker_id:
                meta_obj["worker_id"] = worker_id
            if idempotency_key:
                meta_obj["idempotency_key"] = idempotency_key

            await cur.execute(
                """
                INSERT INTO noetl.event (
                    event_id, execution_id, catalog_id, event_type,
                    node_id, node_name, status, result, meta, worker_id, error, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    evt_id,
                    execution_id,
                    catalog_id,
                    event_type,
                    "events.batch",
                    "events.batch",
                    status,
                    Json({"kind": "data", "data": payload}),
                    Json(meta_obj),
                    worker_id,
                    error,
                    datetime.now(timezone.utc),
                ),
            )
            await conn.commit()


def _build_batch_error(code: str, message: str, request_id: Optional[str] = None) -> dict[str, Any]:
    detail: dict[str, Any] = {"code": code, "message": message}
    if request_id:
        detail["request_id"] = request_id
    return detail


async def _persist_batch_failed_event(job: _BatchAcceptJob, code: str, message: str) -> None:
    try:
        await _persist_batch_status_event(
            execution_id=job.execution_id,
            catalog_id=job.catalog_id,
            request_id=job.request_id,
            worker_id=job.worker_id,
            idempotency_key=job.idempotency_key,
            event_type="batch.failed",
            status="FAILED",
            payload={"request_id": job.request_id, "error_code": code, "message": message},
            error=message,
        )
    except Exception as persist_error:
        logger.error(
            "[BATCH-EVENTS] Failed to persist batch.failed request_id=%s code=%s: %s",
            job.request_id,
            code,
            persist_error,
            exc_info=True,
        )


async def _persist_batch_acceptance(
    req: BatchEventRequest,
    idempotency_key: Optional[str],
) -> _BatchAcceptanceResult:
    skip_engine_events = {
        "command.claimed",
        "command.started",
        "command.completed",
        "step.enter",
    }
    execution_id = int(req.execution_id)

    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1",
                (execution_id,),
            )
            row = await cur.fetchone()
            catalog_id = row["catalog_id"] if row else None

            if idempotency_key:
                await cur.execute(
                    """
                    SELECT meta, result
                    FROM noetl.event
                    WHERE execution_id = %s
                      AND event_type = 'batch.accepted'
                      AND meta->>'idempotency_key' = %s
                    ORDER BY event_id DESC
                    LIMIT 1
                    """,
                    (execution_id, idempotency_key),
                )
                existing = await cur.fetchone()
                if existing:
                    existing_meta = existing.get("meta") or {}
                    existing_result = existing.get("result") or {}
                    existing_data = existing_result.get("data") if isinstance(existing_result, dict) else {}
                    request_id = str(existing_meta.get("batch_request_id") or existing_data.get("request_id"))
                    existing_event_ids = existing_data.get("event_ids") or []
                    if request_id:
                        noop_job = _BatchAcceptJob(
                            request_id=request_id,
                            execution_id=execution_id,
                            catalog_id=catalog_id,
                            worker_id=req.worker_id,
                            idempotency_key=idempotency_key,
                            events=[],
                            last_actionable_event=None,
                            last_actionable_evt_id=None,
                            accepted_event_id=0,
                            accepted_at_monotonic=time.perf_counter(),
                        )
                        return _BatchAcceptanceResult(
                            job=noop_job,
                            event_ids=[int(evt_id) for evt_id in existing_event_ids if isinstance(evt_id, int)],
                            duplicate=True,
                        )

            request_id = str(await _next_snowflake_id(cur))
            accepted_event_id = await _next_snowflake_id(cur)

            event_ids: list[int] = []
            last_actionable_event: Optional[Event] = None
            last_actionable_evt_id: Optional[int] = None
            for item in req.events:
                evt_id = await _next_snowflake_id(cur)
                event_ids.append(evt_id)
                meta_obj: dict[str, Any] = {
                    "actionable": item.actionable,
                    "informative": item.informative,
                    "batch_request_id": request_id,
                }
                if req.worker_id:
                    meta_obj["worker_id"] = req.worker_id
                if idempotency_key:
                    meta_obj["idempotency_key"] = idempotency_key

                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        event_id, execution_id, catalog_id, event_type,
                        node_id, node_name, status, result, meta, worker_id, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        evt_id,
                        execution_id,
                        catalog_id,
                        item.name,
                        item.step,
                        item.step,
                        _status_from_event_name(item.name),
                        Json({"kind": "data", "data": item.payload}),
                        Json(meta_obj),
                        req.worker_id,
                        datetime.now(timezone.utc),
                    ),
                )

                if item.actionable and item.name not in skip_engine_events:
                    last_actionable_event = Event(
                        execution_id=req.execution_id,
                        step=item.step,
                        name=item.name,
                        payload=item.payload,
                        meta=meta_obj,
                        timestamp=datetime.now(timezone.utc),
                        worker_id=req.worker_id,
                    )
                    last_actionable_evt_id = evt_id

            accepted_meta: dict[str, Any] = {
                "batch_request_id": request_id,
                "actionable": False,
                "informative": True,
                "event_count": len(req.events),
            }
            if req.worker_id:
                accepted_meta["worker_id"] = req.worker_id
            if idempotency_key:
                accepted_meta["idempotency_key"] = idempotency_key
            if last_actionable_evt_id is not None:
                accepted_meta["last_actionable_event_id"] = str(last_actionable_evt_id)

            await cur.execute(
                """
                INSERT INTO noetl.event (
                    event_id, execution_id, catalog_id, event_type,
                    node_id, node_name, status, result, meta, worker_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    accepted_event_id,
                    execution_id,
                    catalog_id,
                    "batch.accepted",
                    "events.batch",
                    "events.batch",
                    "PENDING",
                    Json(
                        {
                            "kind": "data",
                            "data": {
                                "request_id": request_id,
                                "event_ids": event_ids,
                                "commands_generated": 0,
                            },
                        }
                    ),
                    Json(accepted_meta),
                    req.worker_id,
                    datetime.now(timezone.utc),
                ),
            )
            await conn.commit()

    job = _BatchAcceptJob(
        request_id=request_id,
        execution_id=execution_id,
        catalog_id=catalog_id,
        worker_id=req.worker_id,
        idempotency_key=idempotency_key,
        events=req.events,
        last_actionable_event=last_actionable_event,
        last_actionable_evt_id=last_actionable_evt_id,
        accepted_event_id=accepted_event_id,
        accepted_at_monotonic=time.perf_counter(),
    )
    return _BatchAcceptanceResult(job=job, event_ids=event_ids, duplicate=False)


async def _issue_commands_for_batch(job: _BatchAcceptJob, commands: list) -> None:
    if not commands:
        return

    nats_pub = await get_nats_publisher()
    server_url = _normalize_command_server_url(
        os.getenv("NOETL_SERVER_URL", "http://noetl.noetl.svc.cluster.local:8082")
    )
    publish_items: list[tuple[int, str, str, int]] = []

    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            for cmd in commands:
                await cur.execute(
                    "SELECT catalog_id, parent_execution_id FROM noetl.event WHERE execution_id = %s LIMIT 1",
                    (int(cmd.execution_id),),
                )
                row = await cur.fetchone()
                cat_id = row["catalog_id"] if row else job.catalog_id
                parent_exec = row["parent_execution_id"] if row else None

                cmd_suffix = await _next_snowflake_id(cur)
                cmd_id = f"{cmd.execution_id}:{cmd.step}:{cmd_suffix}"
                new_evt_id = await _next_snowflake_id(cur)
                context = {
                    "tool_config": cmd.tool.config,
                    "args": cmd.args or {},
                    "render_context": cmd.render_context,
                    "next_targets": cmd.next_targets,
                    "pipeline": cmd.pipeline,
                    "spec": cmd.spec.model_dump() if cmd.spec else None,
                }
                meta = {
                    "command_id": cmd_id,
                    "step": cmd.step,
                    "tool_kind": cmd.tool.kind,
                    "triggered_by": job.last_actionable_event.name if job.last_actionable_event else "batch",
                    "actionable": True,
                    "batch_request_id": job.request_id,
                }
                if cmd.metadata:
                    meta.update({k: v for k, v in cmd.metadata.items() if v is not None})

                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        event_id, execution_id, catalog_id, event_type,
                        node_id, node_name, node_type, status,
                        context, meta, parent_event_id, parent_execution_id,
                        created_at
                    ) VALUES (
                        %(event_id)s, %(execution_id)s, %(catalog_id)s, %(event_type)s,
                        %(node_id)s, %(node_name)s, %(node_type)s, %(status)s,
                        %(context)s, %(meta)s, %(parent_event_id)s, %(parent_execution_id)s,
                        %(created_at)s
                    )
                    """,
                    {
                        "event_id": new_evt_id,
                        "execution_id": int(cmd.execution_id),
                        "catalog_id": cat_id,
                        "event_type": "command.issued",
                        "node_id": cmd.step,
                        "node_name": cmd.step,
                        "node_type": cmd.tool.kind,
                        "status": "PENDING",
                        "context": Json(context),
                        "meta": Json(meta),
                        "parent_event_id": job.last_actionable_evt_id,
                        "parent_execution_id": parent_exec,
                        "created_at": datetime.now(timezone.utc),
                    },
                )
                publish_items.append((int(cmd.execution_id), cmd.step, cmd_id, new_evt_id))
            await conn.commit()

    for execution_id, step, cmd_id, evt_id in publish_items:
        await nats_pub.publish_command(
            execution_id=execution_id,
            event_id=evt_id,
            command_id=cmd_id,
            step=step,
            server_url=server_url,
        )


async def _process_accepted_batch(job: _BatchAcceptJob) -> int:
    commands: list = []
    engine: Optional[ControlFlowEngine] = None
    if job.last_actionable_event:
        engine = get_engine()
        commands = await engine.handle_event(job.last_actionable_event, already_persisted=True)
    try:
        await _issue_commands_for_batch(job, commands)
    except Exception as e:
        if engine is not None and commands:
            await _invalidate_execution_state_cache(
                str(job.execution_id),
                reason=f"batch_command_issue_failed:{type(e).__name__}",
                engine=engine,
            )
        raise
    return len(commands)


async def _batch_accept_worker_loop(worker_idx: int) -> None:
    logger.info("[BATCH-EVENTS] Batch acceptor worker-%s started", worker_idx)
    while True:
        try:
            if _batch_accept_queue is None:
                await asyncio.sleep(0.05)
                continue
            job = await _batch_accept_queue.get()
        except asyncio.CancelledError:
            logger.info("[BATCH-EVENTS] Batch acceptor worker-%s stopped", worker_idx)
            raise

        queue_wait_seconds = max(0.0, time.perf_counter() - job.accepted_at_monotonic)
        _observe_batch_metric("first_worker_claim_latency_seconds", queue_wait_seconds)
        try:
            await _persist_batch_status_event(
                execution_id=job.execution_id,
                catalog_id=job.catalog_id,
                request_id=job.request_id,
                worker_id=job.worker_id,
                idempotency_key=job.idempotency_key,
                event_type="batch.processing",
                status="RUNNING",
                payload={
                    "request_id": job.request_id,
                    "queue_wait_ms": round(queue_wait_seconds * 1000, 3),
                    "event_count": len(job.events),
                },
            )

            process_start = time.perf_counter()
            try:
                commands_generated = await asyncio.wait_for(
                    _process_accepted_batch(job),
                    timeout=_BATCH_PROCESSING_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                _inc_batch_metric("processing_timeout_total")
                await _persist_batch_failed_event(
                    job,
                    _BATCH_FAILURE_PROCESSING_TIMEOUT,
                    f"Batch processing exceeded {_BATCH_PROCESSING_TIMEOUT_SECONDS}s timeout",
                )
                continue

            await _persist_batch_status_event(
                execution_id=job.execution_id,
                catalog_id=job.catalog_id,
                request_id=job.request_id,
                worker_id=job.worker_id,
                idempotency_key=job.idempotency_key,
                event_type="batch.completed",
                status="COMPLETED",
                payload={
                    "request_id": job.request_id,
                    "commands_generated": commands_generated,
                    "processing_ms": round((time.perf_counter() - process_start) * 1000, 3),
                },
            )
        except Exception as e:
            _inc_batch_metric("processing_error_total")
            await _persist_batch_failed_event(job, _BATCH_FAILURE_PROCESSING_ERROR, str(e))
        finally:
            if _batch_accept_queue is not None:
                _batch_accept_queue.task_done()


@router.post("/events/batch", response_model=BatchEventResponse, status_code=202)
async def handle_batch_events(req: BatchEventRequest, request: Request) -> BatchEventResponse:
    """
    Persist batched events and acknowledge with request_id before engine/NATS work.

    Contract:
    1. persist worker events + batch.accepted marker
    2. enqueue async processing
    3. return HTTP 202 with request_id
    """
    idempotency_key = request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key")

    try:
        workers_ready = await ensure_batch_acceptor_started()
        if _batch_accept_queue is None:
            _inc_batch_metric("queue_unavailable_total")
            raise HTTPException(
                status_code=503,
                detail=_build_batch_error(
                    _BATCH_FAILURE_QUEUE_UNAVAILABLE,
                    "Batch acceptance queue is unavailable",
                ),
            )
        if not workers_ready:
            _inc_batch_metric("worker_unavailable_total")
            raise HTTPException(
                status_code=503,
                detail=_build_batch_error(
                    _BATCH_FAILURE_WORKER_UNAVAILABLE,
                    "No batch acceptance workers available",
                ),
            )

        acceptance = await _persist_batch_acceptance(req, idempotency_key)
        if acceptance.duplicate:
            return BatchEventResponse(
                status="accepted",
                request_id=acceptance.job.request_id,
                event_ids=acceptance.event_ids,
                commands_generated=0,
                queue_depth=_batch_queue_depth(),
                duplicate=True,
                idempotency_key=idempotency_key,
            )

        enqueue_start = time.perf_counter()
        try:
            await asyncio.wait_for(
                _batch_accept_queue.put(acceptance.job),
                timeout=_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            _inc_batch_metric("ack_timeout_total")
            await _persist_batch_failed_event(
                acceptance.job,
                _BATCH_FAILURE_ENQUEUE_TIMEOUT,
                f"Timed out while waiting to enqueue batch request (>{_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS}s)",
            )
            raise HTTPException(
                status_code=503,
                detail=_build_batch_error(
                    _BATCH_FAILURE_ENQUEUE_TIMEOUT,
                    "Timed out while waiting for batch enqueue acknowledgment",
                    acceptance.job.request_id,
                ),
                headers={"Retry-After": "1"},
            )
        except Exception as e:
            _inc_batch_metric("enqueue_error_total")
            await _persist_batch_failed_event(
                acceptance.job,
                _BATCH_FAILURE_ENQUEUE_ERROR,
                str(e),
            )
            raise HTTPException(
                status_code=503,
                detail=_build_batch_error(
                    _BATCH_FAILURE_ENQUEUE_ERROR,
                    f"Failed to enqueue batch request: {e}",
                    acceptance.job.request_id,
                ),
            )

        _observe_batch_metric("enqueue_latency_seconds", time.perf_counter() - enqueue_start)
        _inc_batch_metric("accepted_total")
        return BatchEventResponse(
            status="accepted",
            request_id=acceptance.job.request_id,
            event_ids=acceptance.event_ids,
            commands_generated=0,
            queue_depth=_batch_queue_depth(),
            duplicate=False,
            idempotency_key=idempotency_key,
        )
    except PoolTimeout:
        retry_after = _compute_retry_after()
        logger.warning("[BATCH-EVENTS] DB pool saturated during acceptance retry_after=%ss", retry_after)
        raise HTTPException(
            status_code=503,
            detail=_build_batch_error("pool_saturated", "Database temporarily overloaded; retry shortly"),
            headers={"Retry-After": retry_after},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("handle_batch_events failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=_build_batch_error(_BATCH_FAILURE_ENQUEUE_ERROR, f"Batch acceptance failed: {e}"),
        )


async def _get_batch_request_state(request_id: str) -> dict[str, Any]:
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT execution_id, event_type, status, result, error, created_at, meta
                FROM noetl.event
                WHERE meta->>'batch_request_id' = %s
                  AND event_type IN ('batch.accepted', 'batch.processing', 'batch.completed', 'batch.failed')
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (request_id,),
            )
            row = await cur.fetchone()

    if not row:
        raise HTTPException(404, f"Batch request not found: {request_id}")

    event_type = row["event_type"]
    if event_type == "batch.completed":
        state = "completed"
    elif event_type == "batch.failed":
        state = "failed"
    elif event_type == "batch.processing":
        state = "processing"
    else:
        state = "accepted"

    result_obj = row.get("result") or {}
    result_data = result_obj.get("data") if isinstance(result_obj, dict) else {}
    error_code = result_data.get("error_code")
    message = result_data.get("message") or row.get("error")
    meta = row.get("meta") or {}

    return {
        "request_id": request_id,
        "execution_id": str(row["execution_id"]),
        "state": state,
        "status": row["status"],
        "error_code": error_code,
        "message": message,
        "commands_generated": result_data.get("commands_generated"),
        "idempotency_key": meta.get("idempotency_key"),
        "updated_at": _iso_timestamp(row.get("created_at")),
    }


@router.get("/events/batch/{request_id}/status")
async def get_batch_event_status(request_id: str):
    """Fetch async processing status for a previously accepted batch request."""
    try:
        return await _get_batch_request_state(request_id)
    except PoolTimeout:
        retry_after = _compute_retry_after()
        raise HTTPException(
            status_code=503,
            detail={"code": "pool_saturated", "message": "Database temporarily overloaded; retry shortly"},
            headers={"Retry-After": retry_after},
        )


@router.get("/events/batch/{request_id}/stream")
async def stream_batch_event_status(request_id: str, timeout_seconds: float = 30.0):
    """SSE stream for batch status updates (accepted/processing/completed/failed)."""
    timeout_seconds = max(1.0, float(timeout_seconds))

    async def _stream():
        started_at = time.perf_counter()
        while True:
            try:
                payload = await _get_batch_request_state(request_id)
            except HTTPException as e:
                payload = {
                    "request_id": request_id,
                    "state": "not_found" if e.status_code == 404 else "error",
                    "status": "FAILED",
                    "error_code": "not_found" if e.status_code == 404 else "lookup_error",
                    "message": str(e.detail),
                }
                yield f"event: status\ndata: {json.dumps(payload)}\n\n"
                break

            yield f"event: status\ndata: {json.dumps(payload, default=str)}\n\n"
            if payload.get("state") in {"completed", "failed"}:
                break
            if time.perf_counter() - started_at >= timeout_seconds:
                timeout_payload = {
                    "request_id": request_id,
                    "state": "timeout",
                    "status": "RUNNING",
                    "message": "SSE stream timeout reached; continue polling /status",
                }
                yield f"event: status\ndata: {json.dumps(timeout_payload)}\n\n"
                break
            await asyncio.sleep(_BATCH_STATUS_STREAM_POLL_SECONDS)

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/executions/{execution_id}/status")
async def get_execution_status(execution_id: str, full: bool = False):
    """Get execution status from engine state."""
    try:
        engine = get_engine()
        state = engine.state_store.get_state(execution_id)
        
        if not state:
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    try:
                        exec_id_int = int(execution_id)
                    except ValueError:
                        raise HTTPException(404, "Execution not found")

                    await cur.execute("""
                        SELECT event_type, node_name, status, created_at
                        FROM noetl.event
                        WHERE execution_id = %s
                        ORDER BY event_id DESC
                        LIMIT 1
                    """, (exec_id_int,))
                    latest_event = await cur.fetchone()

                    if not latest_event:
                        raise HTTPException(404, "Execution not found")

                    await cur.execute("""
                        SELECT created_at
                        FROM noetl.event
                        WHERE execution_id = %s
                        ORDER BY event_id ASC
                        LIMIT 1
                    """, (exec_id_int,))
                    first_event = await cur.fetchone()

                    await cur.execute("""
                        SELECT event_type
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND event_type IN (
                            'playbook.completed',
                            'workflow.completed',
                            'playbook.failed',
                            'workflow.failed',
                            'execution.cancelled'
                          )
                        ORDER BY event_id DESC
                        LIMIT 1
                    """, (exec_id_int,))
                    terminal_event = await cur.fetchone()

                    await cur.execute("""
                        SELECT node_name
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND event_type = 'step.exit'
                          AND status = 'COMPLETED'
                        ORDER BY event_id ASC
                    """, (exec_id_int,))
                    step_rows = await cur.fetchall()

                    await cur.execute(
                        """
                        SELECT COUNT(*) AS pending_count
                        FROM (
                            SELECT node_name
                            FROM noetl.event
                            WHERE execution_id = %(execution_id)s
                              AND event_type = 'command.issued'
                            EXCEPT
                            SELECT node_name
                            FROM noetl.event
                            WHERE execution_id = %(execution_id)s
                              AND event_type IN (
                                  'call.done',
                                  'command.completed',
                                  'command.failed'
                              )
                        ) AS pending
                        """,
                        {"execution_id": exec_id_int},
                    )
                    pending_row = await cur.fetchone()

            terminal_complete_events = {"playbook.completed", "workflow.completed"}
            terminal_failed_events = {"playbook.failed", "workflow.failed", "execution.cancelled"}
            pending_count = int((pending_row or {}).get("pending_count", 0))

            completed = False
            failed = False
            completion_inferred = True

            terminal_type = terminal_event["event_type"] if terminal_event else None
            if terminal_type in terminal_complete_events:
                completed = True
                failed = False
            elif terminal_type in terminal_failed_events:
                completed = True
                failed = terminal_type != "execution.cancelled"
            elif (
                latest_event["node_name"] == "end"
                and latest_event["status"] == "COMPLETED"
                and latest_event["event_type"] in {"command.completed", "call.done", "step.exit"}
            ):
                completed = True
                failed = False
            elif (
                latest_event["event_type"] == "batch.completed"
                and latest_event["status"] == "COMPLETED"
                and pending_count == 0
            ):
                completed = True
                failed = False

            completed_steps: list[str] = []
            seen_steps: set[str] = set()
            for row in step_rows or []:
                step_name = row.get("node_name")
                if not step_name or step_name in seen_steps:
                    continue
                seen_steps.add(step_name)
                completed_steps.append(step_name)

            fallback_variables: dict[str, Any] = {}
            duration = _duration_fields(
                first_event.get("created_at") if first_event else None,
                latest_event.get("created_at") if latest_event else None,
                completed,
            )
            return {
                "execution_id": execution_id,
                "current_step": latest_event.get("node_name"),
                "completed_steps": completed_steps,
                "failed": failed,
                "completed": completed,
                "completion_inferred": completion_inferred,
                "variables": fallback_variables if full else _compact_status_variables(fallback_variables),
                "source": "event_log_fallback",
                **duration,
            }

        completed = state.completed
        failed = state.failed
        completion_inferred = False

        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("""
                    SELECT created_at
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id ASC
                    LIMIT 1
                """, (int(execution_id),))
                first_event = await cur.fetchone()

                await cur.execute("""
                    SELECT event_type, node_name, status, created_at
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id DESC
                    LIMIT 1
                """, (int(execution_id),))
                latest_event = await cur.fetchone()

                await cur.execute("""
                    SELECT event_type, node_name, status, created_at
                    FROM noetl.event
                    WHERE execution_id = %s
                      AND event_type IN (
                        'playbook.completed',
                        'workflow.completed',
                        'playbook.failed',
                        'workflow.failed',
                        'execution.cancelled'
                      )
                    ORDER BY event_id DESC
                    LIMIT 1
                """, (int(execution_id),))
                terminal_event = await cur.fetchone()

                await cur.execute(
                    """
                    SELECT COUNT(*) AS pending_count
                    FROM (
                        SELECT node_name
                        FROM noetl.event
                        WHERE execution_id = %(execution_id)s
                          AND event_type = 'command.issued'
                        EXCEPT
                        SELECT node_name
                        FROM noetl.event
                        WHERE execution_id = %(execution_id)s
                          AND event_type IN (
                              'call.done',
                              'command.completed',
                              'command.failed'
                          )
                    ) AS pending
                    """,
                    {"execution_id": int(execution_id)},
                )
                pending_row = await cur.fetchone()

        # Fallback completion inference:
        # Some runs reach terminal step completion in events but may miss
        # playbook/workflow terminal flags in engine state.
        if not completed:
            if state.current_step == "end" and "end" in state.completed_steps and not failed:
                completed = True
                completion_inferred = True
            else:
                terminal_complete_events = {"playbook.completed", "workflow.completed"}
                terminal_failed_events = {"playbook.failed", "workflow.failed", "execution.cancelled"}
                terminal_type = terminal_event["event_type"] if terminal_event else None
                pending_count = int((pending_row or {}).get("pending_count", 0))

                if terminal_type in terminal_complete_events:
                    completed = True
                    completion_inferred = True
                elif terminal_type in terminal_failed_events:
                    completed = True
                    failed = terminal_type != "execution.cancelled"
                    completion_inferred = True
                elif latest_event and (
                    latest_event["node_name"] == "end"
                    and latest_event["status"] == "COMPLETED"
                    and latest_event["event_type"] in {"command.completed", "call.done", "step.exit"}
                ):
                    completed = True
                    completion_inferred = True
                elif latest_event and (
                    latest_event["event_type"] == "batch.completed"
                    and latest_event["status"] == "COMPLETED"
                    and pending_count == 0
                ):
                    completed = True
                    completion_inferred = True

        duration_anchor = terminal_event or latest_event

        duration = _duration_fields(
            first_event.get("created_at") if first_event else None,
            duration_anchor.get("created_at") if duration_anchor else None,
            completed,
        )

        return {
            "execution_id": execution_id,
            "current_step": state.current_step,
            "completed_steps": list(state.completed_steps),
            "failed": failed,
            "completed": completed,
            "completion_inferred": completion_inferred,
            "variables": state.variables if full else _compact_status_variables(state.variables),
            **duration,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_execution_status failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))
