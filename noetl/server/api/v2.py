"""
NoETL API v2 - Pure Event Sourcing Architecture.

Single source of truth: noetl.event table
- event.result stores either inline data OR reference (kind: data|ref|refs)
- No queue tables, no projection tables
- All state derived from events
- NATS for command notifications only
"""

import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from typing import Any, Optional, Literal
from datetime import datetime, timezone
from psycopg.types.json import Json
from psycopg.rows import dict_row

from noetl.core.dsl.v2.models import Event
from noetl.core.dsl.v2.engine import ControlFlowEngine, PlaybookRepo, StateStore
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.messaging import NATSCommandPublisher

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)

router = APIRouter(prefix="", tags=["api"])

# Global engine components
_playbook_repo: Optional[PlaybookRepo] = None
_state_store: Optional[StateStore] = None
_engine: Optional[ControlFlowEngine] = None
_nats_publisher: Optional[NATSCommandPublisher] = None


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
                    cmd_id = f"{execution_id}:{cmd.step}:{await get_snowflake_id()}"
                    evt_id = await get_snowflake_id()
                    
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
        async with get_pool_connection() as conn:
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

                # Check if execution is cancelled FIRST (before claiming)
                await cur.execute("""
                    SELECT 1 FROM noetl.event
                    WHERE execution_id = %s AND event_type = 'execution.cancelled'
                    LIMIT 1
                """, (execution_id,))
                if await cur.fetchone():
                    raise HTTPException(409, "Execution has been cancelled")

                # Acquire advisory lock on command_id hash
                await cur.execute("""
                    SELECT pg_try_advisory_xact_lock(hashtext(%s)::bigint) as lock_acquired
                """, (command_id,))
                lock_result = await cur.fetchone()

                if not lock_result or not lock_result.get('lock_acquired'):
                    raise HTTPException(409, "Command is being claimed by another worker")

                # Check if already claimed
                await cur.execute("""
                    SELECT worker_id, meta FROM noetl.event
                    WHERE execution_id = %s
                      AND event_type = 'command.claimed'
                      AND (meta->>'command_id' = %s OR (result->'data'->>'command_id' = %s))
                    LIMIT 1
                """, (execution_id, command_id, command_id))
                existing = await cur.fetchone()

                if existing:
                    existing_worker = existing.get('worker_id') or (existing.get('meta') or {}).get('worker_id')
                    if existing_worker and existing_worker != req.worker_id:
                        raise HTTPException(409, f"Command already claimed by {existing_worker}")
                    # Already claimed by same worker - idempotent, return command details
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
                claim_evt_id = await get_snowflake_id()
                claim_meta = {
                    "command_id": command_id,
                    "worker_id": req.worker_id,
                    "actionable": False,
                    "informative": True,
                }
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
    - loop.item/loop.done: Loop iteration events
    
    Skip engine for administrative events:
    - command.claimed: Just persist, don't process
    - command.started: Just persist, don't process
    - command.completed: Already processed by worker
    - command.failed: Already handled
    - step.enter: Just marks step started
    """
    try:
        engine = get_engine()
        
        # Events that should NOT trigger engine processing
        # These are administrative events that just need to be persisted
        skip_engine_events = {
            "command.claimed", "command.started", "command.completed", 
            "command.failed", "step.enter"
        }
        
        # For command.claimed, use fully atomic claiming with advisory lock + insert in same transaction
        if req.name == "command.claimed":
            command_id = req.payload.get("command_id") or (req.meta or {}).get("command_id")
            if command_id:
                evt_id = await get_snowflake_id()
                async with get_pool_connection() as conn:
                    async with conn.cursor(row_factory=dict_row) as cur:
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
        evt_id = await get_snowflake_id()
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
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
                    
                    cmd_id = f"{cmd.execution_id}:{cmd.step}:{await get_snowflake_id()}"
                    new_evt_id = await get_snowflake_id()
                    
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
    
    except Exception as e:
        logger.error(f"handle_event failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/executions/{execution_id}/status")
async def get_execution_status(execution_id: str):
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
            "variables": state.variables,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_execution_status failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))
