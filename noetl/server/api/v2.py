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
from fastapi import APIRouter, HTTPException
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
_STATUS_VALUE_MAX_BYTES = max(
    256,
    int(os.getenv("NOETL_STATUS_VALUE_MAX_BYTES", "16384")),
)
_STATUS_PREVIEW_ITEMS = max(
    1,
    int(os.getenv("NOETL_STATUS_PREVIEW_ITEMS", "5")),
)


def get_engine():
    """Get or initialize engine."""
    global _playbook_repo, _state_store, _engine
    
    if _engine is None:
        _playbook_repo = PlaybookRepo()
        _state_store = StateStore(_playbook_repo)
        _engine = ControlFlowEngine(_playbook_repo, _state_store)
    
    return _engine


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


# ============================================================================
# Request/Response Models
# ============================================================================

class ExecuteRequest(BaseModel):
    """Request to start playbook execution."""
    path: Optional[str] = Field(None, description="Playbook catalog path")
    catalog_id: Optional[int] = Field(None, description="Catalog ID (alternative to path)")
    version: Optional[int] = Field(None, description="Specific version to execute (used with path)")
    payload: dict[str, Any] = Field(default_factory=dict, alias="workload", description="Input payload/workload")
    parent_execution_id: Optional[int] = Field(None, description="Parent execution ID")

    class Config:
        populate_by_name = True  # Allow both 'payload' and 'workload' field names

    @model_validator(mode='after')
    def validate_path_or_catalog_id(self):
        if not self.path and not self.catalog_id:
            raise ValueError("Either 'path' or 'catalog_id' must be provided")
        return self


# Alias for backward compatibility with /api/run endpoint
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
    """Response for batch event submission."""
    status: str
    event_ids: list[int]
    commands_generated: int


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest) -> ExecuteResponse:
    """
    Start playbook execution.

    Creates playbook.initialized event, emits command.issued events.
    All state in event table - result column has kind: data|ref|refs.
    """
    try:
        engine = get_engine()

        # Log incoming request for debugging version selection
        logger.debug(f"[EXECUTE] Request: path={req.path}, catalog_id={req.catalog_id}, version={req.version}")

        # Resolve catalog
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                if req.catalog_id:
                    await cur.execute(
                        "SELECT path, catalog_id FROM noetl.catalog WHERE catalog_id = %s",
                        (req.catalog_id,)
                    )
                    row = await cur.fetchone()
                    if not row:
                        raise HTTPException(404, f"Playbook not found: catalog_id={req.catalog_id}")
                    path, catalog_id = row['path'], row['catalog_id']
                else:
                    # If version specified, look up exact path + version
                    # Otherwise, get the latest version
                    if req.version is not None:
                        await cur.execute(
                            "SELECT catalog_id, path, version FROM noetl.catalog WHERE path = %s AND version = %s",
                            (req.path, req.version)
                        )
                        row = await cur.fetchone()
                        if not row:
                            raise HTTPException(404, f"Playbook not found: {req.path} v{req.version}")
                    else:
                        await cur.execute(
                            "SELECT catalog_id, path, version FROM noetl.catalog WHERE path = %s ORDER BY version DESC LIMIT 1",
                            (req.path,)
                        )
                        row = await cur.fetchone()
                        if not row:
                            raise HTTPException(404, f"Playbook not found: {req.path}")
                    catalog_id, path = row['catalog_id'], row['path']
                    logger.debug(f"[EXECUTE] Resolved playbook: {path} v{row.get('version', '?')} -> catalog_id={catalog_id}")
        
        # Start execution
        execution_id, commands = await engine.start_execution(
            path, req.payload, catalog_id, req.parent_execution_id
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
        server_url = os.getenv("NOETL_SERVER_URL", "http://noetl.noetl.svc.cluster.local:8082")
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
        
        return ExecuteResponse(execution_id=execution_id, status="started", commands_generated=len(commands))
    
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
                    SELECT worker_id, meta, created_at FROM noetl.event
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

                        worker_inactive = (
                            worker_runtime_status is not None
                            and worker_runtime_status != "ready"
                        )
                        heartbeat_stale = (
                            worker_heartbeat_age is not None
                            and worker_heartbeat_age >= _CLAIM_WORKER_HEARTBEAT_STALE_SECONDS
                        )

                        if worker_inactive or heartbeat_stale:
                            stale_reclaim = True
                            reclaimed_from_worker = existing_worker
                            reclaimed_reason = (
                                "worker_inactive"
                                if worker_inactive
                                else "worker_heartbeat_stale"
                            )
                            logger.warning(
                                "[CLAIM] Reclaiming command %s from inactive worker=%s "
                                "(status=%s heartbeat_age=%.3fs threshold=%.3fs)",
                                command_id,
                                existing_worker,
                                worker_runtime_status,
                                worker_heartbeat_age or -1.0,
                                _CLAIM_WORKER_HEARTBEAT_STALE_SECONDS,
                            )
                        elif claim_age_seconds < _CLAIM_LEASE_SECONDS:
                            retry_after = max(
                                1,
                                min(
                                    _CLAIM_ACTIVE_RETRY_AFTER_SECONDS,
                                    int(max(1.0, _CLAIM_LEASE_SECONDS - claim_age_seconds)),
                                ),
                            )
                            raise HTTPException(
                                409,
                                detail={
                                    "code": "active_claim",
                                    "message": f"Command already claimed by {existing_worker}",
                                    "worker_id": existing_worker,
                                    "age_seconds": round(claim_age_seconds, 3),
                                    "lease_seconds": _CLAIM_LEASE_SECONDS,
                                    "worker_status": worker_runtime_status,
                                    "worker_heartbeat_age_seconds": (
                                        round(worker_heartbeat_age, 3)
                                        if worker_heartbeat_age is not None
                                        else None
                                    ),
                                },
                                headers={"Retry-After": str(retry_after)},
                            )
                        else:
                            stale_reclaim = True
                            reclaimed_from_worker = existing_worker
                            reclaimed_reason = "lease_expired"
                            logger.warning(
                                "[CLAIM] Reclaiming stale command %s from worker=%s age=%.3fs (lease=%.3fs)",
                                command_id,
                                existing_worker,
                                claim_age_seconds,
                                _CLAIM_LEASE_SECONDS,
                            )
                    # Already claimed by same worker - idempotent, return command details
                    if not stale_reclaim:
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
            logger.debug(f"[ENGINE] Processed {req.name} for step {req.step}, generated {len(commands)} commands")
        else:
            logger.debug(f"[ENGINE] Skipped engine for administrative event {req.name}")
        
        # Emit command.issued for next steps
        nats_pub = await get_nats_publisher()
        server_url = os.getenv("NOETL_SERVER_URL", "http://noetl.noetl.svc.cluster.local:8082")
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
        retry_after = _compute_retry_after()
        logger.warning("[EVENTS] DB pool saturated while persisting %s for step %s retry_after=%ss", req.name, req.step, retry_after)
        raise HTTPException(
            status_code=503,
            detail={"code": "pool_saturated", "message": "Database temporarily overloaded; retry shortly"},
            headers={"Retry-After": retry_after},
        )
    except Exception as e:
        logger.error(f"handle_event failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/events/batch", response_model=BatchEventResponse)
async def handle_batch_events(req: BatchEventRequest) -> BatchEventResponse:
    """
    Persist multiple events for one execution in a single DB transaction.

    Only the LAST actionable event in the batch is routed through the engine
    to generate commands. Non-actionable events (command.started, step.enter,
    command.completed, step.exit without routing) are persisted directly.

    This reduces HTTP round-trips from 5 per loop iteration to 2 (batch + call.done).
    """
    try:
        engine = get_engine()

        skip_engine_events = {
            "command.claimed", "command.started", "command.completed",
            "step.enter",
        }

        event_ids: list[int] = []
        last_actionable_event: Optional[Event] = None
        last_actionable_evt_id: Optional[int] = None

        # Persist all events in a single transaction
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1",
                    (int(req.execution_id),),
                )
                row = await cur.fetchone()
                catalog_id = row["catalog_id"] if row else None

                for item in req.events:
                    evt_id = await _next_snowflake_id(cur)
                    event_ids.append(evt_id)

                    meta_obj: dict[str, Any] = {
                        "actionable": item.actionable,
                        "informative": item.informative,
                    }
                    if req.worker_id:
                        meta_obj["worker_id"] = req.worker_id

                    result_obj = {"kind": "data", "data": item.payload}

                    if "error" in item.name or "failed" in item.name:
                        status = "FAILED"
                    elif "done" in item.name or "exit" in item.name or "completed" in item.name:
                        status = "COMPLETED"
                    else:
                        status = "RUNNING"

                    await cur.execute(
                        """
                        INSERT INTO noetl.event (
                            event_id, execution_id, catalog_id, event_type,
                            node_id, node_name, status, result, meta, worker_id, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            evt_id,
                            int(req.execution_id),
                            catalog_id,
                            item.name,
                            item.step,
                            item.step,
                            status,
                            Json(result_obj),
                            Json(meta_obj),
                            req.worker_id,
                            datetime.now(timezone.utc),
                        ),
                    )

                    # Track last actionable event for engine processing
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

                await conn.commit()

        # Process only the last actionable event through the engine
        commands: list = []
        if last_actionable_event:
            commands = await engine.handle_event(last_actionable_event, already_persisted=True)

        # Emit command.issued for generated commands
        if commands:
            nats_pub = await get_nats_publisher()
            server_url = os.getenv(
                "NOETL_SERVER_URL",
                "http://noetl.noetl.svc.cluster.local:8082",
            )
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    for cmd in commands:
                        await cur.execute(
                            "SELECT catalog_id, parent_execution_id FROM noetl.event WHERE execution_id = %s LIMIT 1",
                            (int(cmd.execution_id),),
                        )
                        row = await cur.fetchone()
                        cat_id = row["catalog_id"] if row else catalog_id
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
                            "triggered_by": last_actionable_event.name if last_actionable_event else "batch",
                            "actionable": True,
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
                                "parent_event_id": last_actionable_evt_id,
                                "parent_execution_id": parent_exec,
                                "created_at": datetime.now(timezone.utc),
                            },
                        )

                        await nats_pub.publish_command(
                            execution_id=int(cmd.execution_id),
                            event_id=new_evt_id,
                            command_id=cmd_id,
                            step=cmd.step,
                            server_url=server_url,
                        )

                    await conn.commit()

        return BatchEventResponse(
            status="ok",
            event_ids=event_ids,
            commands_generated=len(commands),
        )

    except PoolTimeout:
        retry_after = _compute_retry_after()
        logger.warning("[BATCH-EVENTS] DB pool saturated retry_after=%ss", retry_after)
        raise HTTPException(
            status_code=503,
            detail={"code": "pool_saturated", "message": "Database temporarily overloaded; retry shortly"},
            headers={"Retry-After": retry_after},
        )
    except Exception as e:
        logger.error(f"handle_batch_events failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/executions/{execution_id}/status")
async def get_execution_status(execution_id: str, full: bool = False):
    """Get execution status from engine state."""
    try:
        engine = get_engine()
        state = engine.state_store.get_state(execution_id)
        
        if not state:
            raise HTTPException(404, "Execution not found")

        completed = state.completed
        failed = state.failed
        completion_inferred = False

        # Fallback completion inference:
        # Some runs reach terminal step completion in events but may miss
        # playbook/workflow terminal flags in engine state.
        if not completed:
            latest_event = None
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute("""
                        SELECT event_type, node_name, status
                        FROM noetl.event
                        WHERE execution_id = %s
                        ORDER BY event_id DESC
                        LIMIT 1
                    """, (int(execution_id),))
                    latest_event = await cur.fetchone()

            if state.current_step == "end" and "end" in state.completed_steps and not failed:
                completed = True
                completion_inferred = True
            elif latest_event:
                terminal_complete_events = {"playbook.completed", "workflow.completed"}
                terminal_failed_events = {"playbook.failed", "workflow.failed", "execution.cancelled"}

                if latest_event["event_type"] in terminal_complete_events:
                    completed = True
                    completion_inferred = True
                elif latest_event["event_type"] in terminal_failed_events:
                    completed = True
                    failed = latest_event["event_type"] != "execution.cancelled"
                    completion_inferred = True
                elif (
                    latest_event["node_name"] == "end"
                    and latest_event["status"] == "COMPLETED"
                    and latest_event["event_type"] in {"command.completed", "call.done", "step.exit"}
                ):
                    completed = True
                    completion_inferred = True
        
        return {
            "execution_id": execution_id,
            "current_step": state.current_step,
            "completed_steps": list(state.completed_steps),
            "failed": failed,
            "completed": completed,
            "completion_inferred": completion_inferred,
            "variables": state.variables if full else _compact_status_variables(state.variables),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_execution_status failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))
