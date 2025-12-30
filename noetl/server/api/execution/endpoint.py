"""
Execution query endpoints - all GET endpoints for execution data.

These endpoints query and aggregate event data to provide execution views.
Business logic is in event/service/event_service.py.
"""

import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger
from noetl.core.common import convert_snowflake_ids_for_api
from .schema import ExecutionEntryResponse
# V2 engine fallback
try:
    from noetl.server.api.v2 import get_engine as get_v2_engine
except Exception:  # pragma: no cover
    get_v2_engine = None
# from .service import get_event_service

logger = setup_logger(__name__, include_location=True)
router = APIRouter(tags=["executions"])


@router.get("/executions", response_model=list[ExecutionEntryResponse])
async def get_executions():
    """Get all executions"""
    async with get_pool_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("""
                WITH execution_times AS (
                    SELECT 
                        execution_id,
                        MIN(created_at) as start_time,
                        MAX(created_at) as end_time,
                        MAX(event_id) as latest_event_id
                    FROM event
                    GROUP BY execution_id
                )
                SELECT 
                    e.execution_id,
                    e.catalog_id,
                    e.event_type,
                    e.status,
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


@router.get("/executions/{execution_id}", response_class=JSONResponse)
async def get_execution(execution_id: str):
    """Get execution by ID with full event history"""
    async with get_pool_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("""
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
            WHERE execution_id = %(execution_id)s
            ORDER BY event_id
            """, {"execution_id": execution_id})
            rows = await cursor.fetchall()
    if rows:
        events = []
        for row in rows:
            event_data = dict(row)
            event_data["execution_id"] = execution_id
            event_data["timestamp"] = row["created_at"].isoformat() if row["created_at"] else None
            if isinstance(row["context"], str):
                event_data["context"] = json.loads(row["context"])
            if isinstance(row["result"], str):
                try:
                    event_data["result"] = json.loads(row["result"])
                except json.JSONDecodeError:
                    event_data["result"] = row["result"]
            events.append(event_data)
        execution_item = next((e for e in events if e.get("event_type") == "workflow.initialized"), None)
        if execution_item is None:
            execution_item = events[0] if events else None
        if execution_item is None:
            logger.error(f"No events found for execution_id: {execution_id}")
            raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
        playbook_path = "unknown"
        if execution_item.get("catalog_id"):
            async with get_pool_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        SELECT path FROM noetl.catalog WHERE catalog_id = %s
                    """, (execution_item["catalog_id"],))
                    catalog_row = await cursor.fetchone()
            if catalog_row:
                playbook_path = catalog_row["path"]
        return {
            "execution_id": execution_id,
            "path": playbook_path,
            "status": events[-1].get("status"),
            "start_time": execution_item["timestamp"],
            "end_time": events[-1].get("timestamp") if events else None,
            "parent_execution_id": execution_item.get("parent_execution_id"),
            "events": events,
        }
    # Fallback: pull from in-memory v2 engine state (for newer engine runs)
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
                    "events": []
                }
        except Exception as e:  # pragma: no cover
            logger.warning(f"V2 engine fallback failed for execution {execution_id}: {e}")
    raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")