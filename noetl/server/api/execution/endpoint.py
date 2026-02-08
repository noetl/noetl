import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Json
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger
from noetl.core.common import convert_snowflake_ids_for_api
from .schema import (
    ExecutionEntryResponse,
    CancelExecutionRequest,
    CancelExecutionResponse,
    FinalizeExecutionRequest,
    FinalizeExecutionResponse,
    CleanupStuckExecutionsRequest,
    CleanupStuckExecutionsResponse
)

# V2 engine fallback
try:
    from noetl.server.api.v2 import get_engine as get_v2_engine
except Exception:  # pragma: no cover
    get_v2_engine = None

logger = setup_logger(__name__, include_location=True)
router = APIRouter(tags=["executions"])


@router.post("/executions/{execution_id}/finalize", response_model=FinalizeExecutionResponse)
async def finalize_execution(execution_id: str, request: FinalizeExecutionRequest = Body(default=None)):
    """
    Forcibly finalize an execution by emitting terminal events if not already completed.
    This is for admin/automation use to close out stuck or abandoned executions.
    """
    if get_v2_engine is None:
        raise HTTPException(status_code=500, detail="V2 engine not available")
    engine = get_v2_engine()
    # Try to load state
    state = await engine.state_store.load_state(execution_id)
    if not state:
        return FinalizeExecutionResponse(
            status="not_found",
            execution_id=execution_id,
            message=f"Execution {execution_id} not found in engine state store"
        )
    if state.completed:
        return FinalizeExecutionResponse(
            status="already_completed",
            execution_id=execution_id,
            message=f"Execution {execution_id} is already completed"
        )
    reason = request.reason if request and request.reason else "Abandoned or timed out"
    await engine.finalize_abandoned_execution(execution_id, reason=reason)
    return FinalizeExecutionResponse(
        status="finalized",
        execution_id=execution_id,
        message=f"Emitted terminal events for execution {execution_id}"
    )


@router.get("/executions", response_model=list[ExecutionEntryResponse])
async def get_executions():
    """Get all executions"""
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute("""
                WITH execution_times AS (
                    SELECT 
                        execution_id,
                        MIN(created_at) as start_time,
                        MAX(created_at) as end_time,
                        MAX(event_id) as latest_event_id
                    FROM event
                    GROUP BY execution_id
                ),
                -- Get the latest terminal event (by event_id DESC) for each execution
                latest_terminal_event AS (
                    SELECT DISTINCT ON (execution_id)
                        execution_id,
                        event_type as terminal_event_type,
                        status as terminal_status,
                        event_id as terminal_event_id
                    FROM event
                    WHERE event_type IN ('playbook.completed', 'playbook.failed', 'execution.cancelled', 'workflow.completed', 'workflow.failed')
                    ORDER BY execution_id, event_id DESC
                )
                SELECT 
                    e.execution_id,
                    e.catalog_id,
                    e.event_type,
                    -- Use terminal status if available, otherwise use latest event status
                    COALESCE(lte.terminal_status, e.status) as status,
                    COALESCE(lte.terminal_event_type, e.event_type) as derived_event_type,
                    et.start_time,
                    et.end_time,
                    e.meta,
                    e.context,
                    e.result,
                    e.error,
                    e.stack_trace,
                    e.parent_execution_id,
                    c.path,
                    c.version
                FROM event e
                JOIN execution_times et ON e.execution_id = et.execution_id AND e.event_id = et.latest_event_id
                JOIN catalog c on c.catalog_id = e.catalog_id
                LEFT JOIN latest_terminal_event lte ON lte.execution_id = e.execution_id
                ORDER BY et.start_time DESC
            """)
            rows = await cursor.fetchall()
            resp = []
            for row_dict in rows:
                resp.append(ExecutionEntryResponse(
                    execution_id=row_dict["execution_id"],
                    catalog_id=row_dict["catalog_id"],
                    path=row_dict["path"],
                    version=row_dict["version"],
                    status=row_dict["status"],
                    start_time=row_dict["start_time"],
                    end_time=row_dict["end_time"],
                    progress=0,  # Not in query, needs to be computed
                    result=row_dict["result"],
                    error=row_dict["error"],
                    parent_execution_id=row_dict.get("parent_execution_id")
                ))
            return resp


@router.post("/executions/{execution_id}/cancel", response_model=CancelExecutionResponse)
async def cancel_execution(execution_id: str, request: CancelExecutionRequest = None):
    """
    Cancel a running execution.
    
    Emits execution.cancelled events to stop workers from processing further commands.
    If cascade=True (default), also cancels all child executions (sub-playbooks).
    
    **Request Body (optional)**:
    ```json
    {
        "reason": "User requested cancellation",
        "cascade": true
    }
    ```
    
    **Response**:
    ```json
    {
        "status": "cancelled",
        "execution_id": "123456789",
        "cancelled_executions": ["123456789", "987654321"],
        "message": "Cancelled 2 executions"
    }
    ```
    """
    if request is None:
        request = CancelExecutionRequest()
    
    cancelled_ids = []
    
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Check if execution exists and get its current state
            await cur.execute("""
                SELECT e.execution_id, e.status, e.event_type, e.catalog_id
                FROM noetl.event e
                WHERE e.execution_id = %s
                ORDER BY e.event_id DESC
                LIMIT 1
            """, (int(execution_id),))
            latest_event = await cur.fetchone()
            
            if not latest_event:
                raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
            
            # Check if already completed or failed
            terminal_statuses = {'COMPLETED', 'FAILED', 'CANCELLED'}
            terminal_event_types = {'playbook.completed', 'playbook.failed', 'execution.cancelled'}
            
            if latest_event['status'] in terminal_statuses or latest_event['event_type'] in terminal_event_types:
                return CancelExecutionResponse(
                    status="already_completed",
                    execution_id=execution_id,
                    cancelled_executions=[],
                    message=f"Execution {execution_id} is already {latest_event['status']}"
                )
            
            # Collect all execution IDs to cancel (parent + children if cascade)
            execution_ids_to_cancel = [int(execution_id)]
            
            if request.cascade:
                # Find all child executions recursively
                await cur.execute("""
                    WITH RECURSIVE children AS (
                        SELECT DISTINCT execution_id 
                        FROM noetl.event 
                        WHERE parent_execution_id = %s
                        UNION
                        SELECT DISTINCT e.execution_id 
                        FROM noetl.event e
                        INNER JOIN children c ON e.parent_execution_id = c.execution_id
                    )
                    SELECT execution_id FROM children
                """, (int(execution_id),))
                children = await cur.fetchall()
                execution_ids_to_cancel.extend([row['execution_id'] for row in children])
            
            # Emit execution.cancelled event for each execution
            now = datetime.now(timezone.utc)
            for exec_id in execution_ids_to_cancel:
                event_id = await get_snowflake_id()
                
                # Get catalog_id for this execution
                await cur.execute("""
                    SELECT catalog_id FROM noetl.event 
                    WHERE execution_id = %s AND catalog_id IS NOT NULL
                    LIMIT 1
                """, (exec_id,))
                cat_row = await cur.fetchone()
                catalog_id = cat_row['catalog_id'] if cat_row else latest_event['catalog_id']
                
                meta = {
                    "reason": request.reason,
                    "cancelled_by": "api",
                    "cascade": request.cascade,
                    "parent_cancel_id": execution_id if exec_id != int(execution_id) else None,
                    "actionable": True,
                }
                
                await cur.execute("""
                    INSERT INTO noetl.event (
                        event_id, execution_id, catalog_id, event_type,
                        node_id, node_name, status, meta, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    event_id, exec_id, catalog_id, "execution.cancelled",
                    "cancel", "cancel", "CANCELLED",
                    Json(meta), now
                ))
                
                cancelled_ids.append(str(exec_id))
                logger.info(f"Cancelled execution {exec_id} - reason: {request.reason}")
            
            await conn.commit()
    
    return CancelExecutionResponse(
        status="cancelled",
        execution_id=execution_id,
        cancelled_executions=cancelled_ids,
        message=f"Cancelled {len(cancelled_ids)} execution(s)"
    )


@router.get("/executions/{execution_id}/cancellation-check", response_class=JSONResponse)
async def get_execution_cancellation_status(execution_id: str):
    """
    Get quick execution status including cancellation state.
    
    Lightweight endpoint for workers to check if execution is cancelled.
    
    **Response**:
    ```json
    {
        "execution_id": "123456789",
        "status": "RUNNING",
        "cancelled": false,
        "completed": false,
        "failed": false
    }
    ```
    """
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Get latest event status
            await cur.execute("""
                SELECT event_type, status
                FROM noetl.event
                WHERE execution_id = %s
                ORDER BY event_id DESC
                LIMIT 1
            """, (int(execution_id),))
            latest = await cur.fetchone()
            
            if not latest:
                raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
            
            # Check for cancellation event
            await cur.execute("""
                SELECT 1 FROM noetl.event
                WHERE execution_id = %s AND event_type = 'execution.cancelled'
                LIMIT 1
            """, (int(execution_id),))
            cancelled = await cur.fetchone() is not None
            
            terminal_statuses = {'COMPLETED', 'FAILED', 'CANCELLED'}
            completed_events = {'playbook.completed', 'workflow.completed'}
            failed_events = {'playbook.failed', 'workflow.failed', 'command.failed'}
            
            return {
                "execution_id": execution_id,
                "status": latest['status'],
                "event_type": latest['event_type'],
                "cancelled": cancelled,
                "completed": latest['event_type'] in completed_events or latest['status'] == 'COMPLETED',
                "failed": latest['event_type'] in failed_events or latest['status'] == 'FAILED'
            }


@router.get("/executions/{execution_id}", response_class=JSONResponse)
async def get_execution(
    execution_id: str,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=100, ge=10, le=500, description="Events per page"),
    since_event_id: Optional[int] = Query(default=None, description="Get events after this event_id (for incremental loading)"),
    event_type: Optional[str] = Query(default=None, description="Filter by event type")
):
    """
    Get execution by ID with paginated event history.

    **Query Parameters**:
    - `page`: Page number (default: 1)
    - `page_size`: Events per page (default: 100, max: 500)
    - `since_event_id`: Get only events after this ID (for incremental polling)
    - `event_type`: Filter events by type

    **Response includes pagination metadata**:
    ```json
    {
        "execution_id": "...",
        "events": [...],
        "pagination": {
            "page": 1,
            "page_size": 100,
            "total_events": 5000,
            "total_pages": 50,
            "has_next": true,
            "has_prev": false
        }
    }
    ```
    """
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            # Build WHERE clause for filters
            where_clauses = ["execution_id = %(execution_id)s"]
            params = {"execution_id": execution_id}

            if since_event_id is not None:
                where_clauses.append("event_id > %(since_event_id)s")
                params["since_event_id"] = since_event_id

            if event_type:
                where_clauses.append("event_type = %(event_type)s")
                params["event_type"] = event_type

            where_sql = " AND ".join(where_clauses)

            # Get total count for pagination
            await cursor.execute(f"""
                SELECT COUNT(*) as total
                FROM noetl.event
                WHERE {where_sql}
            """, params)
            count_row = await cursor.fetchone()
            total_events = count_row["total"] if count_row else 0

            # Calculate pagination
            total_pages = (total_events + page_size - 1) // page_size if total_events > 0 else 1
            offset = (page - 1) * page_size

            # Get paginated events (ordered by event_id DESC for most recent first)
            params["page_size"] = page_size
            params["offset"] = offset
            await cursor.execute(f"""
                SELECT event_id,
                       event_type,
                       node_id,
                       node_name,
                       status,
                       created_at,
                       context,
                       result,
                       error,
                       catalog_id,
                       parent_execution_id,
                       parent_event_id,
                       duration
                FROM noetl.event
                WHERE {where_sql}
                ORDER BY event_id DESC
                LIMIT %(page_size)s OFFSET %(offset)s
            """, params)
            rows = await cursor.fetchall()

            # Also get execution metadata (first event info) in a separate efficient query
            await cursor.execute("""
                SELECT event_id, event_type, catalog_id, parent_execution_id, created_at, status
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                ORDER BY event_id ASC
                LIMIT 1
            """, {"execution_id": execution_id})
            first_event = await cursor.fetchone()

            # Get terminal status efficiently
            await cursor.execute("""
                SELECT event_type, status, created_at
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('execution.cancelled', 'playbook.failed', 'workflow.failed',
                                     'playbook.completed', 'workflow.completed')
                ORDER BY event_id DESC
                LIMIT 1
            """, {"execution_id": execution_id})
            terminal_event = await cursor.fetchone()

            # Get latest event for end_time and default status
            await cursor.execute("""
                SELECT created_at, status
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                ORDER BY event_id DESC
                LIMIT 1
            """, {"execution_id": execution_id})
            latest_event = await cursor.fetchone()

    if first_event is None:
        # No events found - check v2 engine fallback
        if get_v2_engine:
            try:
                engine = get_v2_engine()
                state = engine.state_store.get_state(execution_id)
                if state:
                    path = None
                    if state.playbook and getattr(state.playbook, "metadata", None):
                        path = state.playbook.metadata.get("path") or state.playbook.metadata.get("name")
                    status = "FAILED" if state.failed else "COMPLETED" if state.completed else "RUNNING"
                    return {
                        "execution_id": execution_id,
                        "path": path or "unknown",
                        "status": status,
                        "start_time": None,
                        "end_time": None,
                        "parent_execution_id": state.parent_execution_id,
                        "events": [],
                        "pagination": {
                            "page": 1,
                            "page_size": page_size,
                            "total_events": 0,
                            "total_pages": 1,
                            "has_next": False,
                            "has_prev": False
                        }
                    }
            except Exception as e:
                logger.warning(f"V2 engine fallback failed for execution {execution_id}: {e}")
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

    # Process events
    events = []
    for row in rows:
        event_data = dict(row)
        event_data["execution_id"] = execution_id
        event_data["timestamp"] = row["created_at"].isoformat() if row["created_at"] else None
        if isinstance(row["context"], str):
            try:
                event_data["context"] = json.loads(row["context"])
            except json.JSONDecodeError:
                pass
        if isinstance(row["result"], str):
            try:
                event_data["result"] = json.loads(row["result"])
            except json.JSONDecodeError:
                pass
        events.append(event_data)

    # Get playbook path and version from catalog
    playbook_path = "unknown"
    playbook_version = None
    catalog_id = first_event.get("catalog_id")
    if catalog_id:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT path, version FROM noetl.catalog WHERE catalog_id = %s
                """, (catalog_id,))
                catalog_row = await cursor.fetchone()
        if catalog_row:
            playbook_path = catalog_row["path"]
            playbook_version = catalog_row["version"]

    # Determine final status
    terminal_event_types = {
        'execution.cancelled': 'CANCELLED',
        'playbook.failed': 'FAILED',
        'workflow.failed': 'FAILED',
        'playbook.completed': 'COMPLETED',
        'workflow.completed': 'COMPLETED',
    }

    if terminal_event:
        final_status = terminal_event_types.get(terminal_event["event_type"], terminal_event["status"])
    elif latest_event:
        final_status = latest_event["status"]
    else:
        final_status = "UNKNOWN"

    return {
        "execution_id": execution_id,
        "path": playbook_path,
        "catalog_id": str(catalog_id) if catalog_id else None,
        "version": playbook_version,
        "status": final_status,
        "start_time": first_event["created_at"].isoformat() if first_event.get("created_at") else None,
        "end_time": latest_event["created_at"].isoformat() if latest_event and latest_event.get("created_at") else None,
        "parent_execution_id": first_event.get("parent_execution_id"),
        "events": events,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_events": total_events,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        }
    }


@router.post("/executions/cleanup", response_model=CleanupStuckExecutionsResponse)
async def cleanup_stuck_executions(request: CleanupStuckExecutionsRequest = Body(...)):
    """
    Clean up stuck executions that have no terminal event.
    
    Marks executions as CANCELLED if they:
    - Have a 'playbook.initialized' event
    - Are older than specified minutes (default: 5)
    - Have no terminal event (playbook.completed, playbook.failed, execution.cancelled)
    
    This is useful for cleaning up executions interrupted by server restarts.
    """
    logger.info(
        f"Cleanup stuck executions request: older_than_minutes={request.older_than_minutes}, "
        f"dry_run={request.dry_run}"
    )
    
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            # Find stuck executions
            await cursor.execute("""
                SELECT DISTINCT 
                    e1.execution_id,
                    e1.catalog_id
                FROM event e1
                WHERE e1.event_type = 'playbook.initialized'
                  AND e1.created_at < NOW() - INTERVAL '%s minutes'
                  AND NOT EXISTS (
                    SELECT 1 FROM event e2 
                    WHERE e2.execution_id = e1.execution_id 
                      AND e2.event_type IN ('playbook.completed', 'playbook.failed', 'execution.cancelled')
                  )
                ORDER BY e1.execution_id
            """, (request.older_than_minutes,))
            
            stuck_executions = await cursor.fetchall()
            execution_ids = [str(ex['execution_id']) for ex in stuck_executions]
            
            if request.dry_run:
                logger.info(f"[DRY RUN] Would cancel {len(execution_ids)} stuck executions")
                return CleanupStuckExecutionsResponse(
                    cancelled_count=len(execution_ids),
                    execution_ids=execution_ids,
                    message=f"[DRY RUN] Would cancel {len(execution_ids)} stuck executions older than {request.older_than_minutes} minutes"
                )
            
            if not stuck_executions:
                return CleanupStuckExecutionsResponse(
                    cancelled_count=0,
                    execution_ids=[],
                    message=f"No stuck executions found older than {request.older_than_minutes} minutes"
                )
            
            # Insert cancellation events
            for execution in stuck_executions:
                execution_id = execution['execution_id']
                catalog_id = execution['catalog_id']
                
                # Get next event_id for this execution
                await cursor.execute("""
                    SELECT COALESCE(MAX(event_id), 0) + 1 as next_event_id
                    FROM event
                    WHERE execution_id = %s
                """, (execution_id,))
                
                result = await cursor.fetchone()
                next_event_id = result['next_event_id']
                
                # Insert cancellation event
                await cursor.execute("""
                    INSERT INTO event (
                        execution_id, catalog_id, event_id, event_type, status, context, created_at
                    ) VALUES (
                        %s, %s, %s, 'execution.cancelled', 'CANCELLED', %s, NOW()
                    )
                """, (
                    execution_id,
                    catalog_id,
                    next_event_id,
                    Json({
                        "reason": f"Cleaned up stuck execution (older than {request.older_than_minutes} minutes)",
                        "auto_cancelled": True,
                        "cleanup_api": True
                    })
                ))
            
            await conn.commit()
            
            logger.info(f"Cancelled {len(execution_ids)} stuck executions")
            
            return CleanupStuckExecutionsResponse(
                cancelled_count=len(execution_ids),
                execution_ids=execution_ids,
                message=f"Successfully cancelled {len(execution_ids)} stuck executions older than {request.older_than_minutes} minutes"
            )

