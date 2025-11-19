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
# from .service import get_event_service

logger = setup_logger(__name__, include_location=True)
router = APIRouter(tags=["executions"])


@router.get("/executions", response_model=list[ExecutionEntryResponse])
async def get_executions():
    """Get all executions"""
    async with get_pool_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("""
                WITH latest_events AS (
                    SELECT 
                        execution_id,
                        MAX(event_id) as latest_event_id
                    FROM event
                    GROUP BY execution_id
                )
                SELECT 
                    e.execution_id,
                    e.catalog_id,
                    e.event_type,
                    e.status,
                    e.created_at,
                    e.meta,
                    e.context,
                    e.result,
                    e.error,
                    e.stack_trace,
                    c.path,
                    c.version
                FROM event e
                JOIN latest_events le ON e.execution_id = le.execution_id AND e.event_id = le.latest_event_id
                JOIN catalog c on c.catalog_id = e.catalog_id
                ORDER BY e.created_at DESC
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
                    start_time=row_dict["created_at"],
                    end_time=None,  # Not in query, needs to be computed from events
                    progress=0,  # Not in query, needs to be computed
                    result=row_dict["result"],
                    error=row_dict["error"]
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
                   node_type,
                   status,
                   duration,
                   created_at,
                   context,
                   result,
                   meta,
                   error,
                   catalog_id
            FROM event
            WHERE execution_id = %(execution_id)s
            ORDER BY created_at
            """, {"execution_id": execution_id})
            rows = await cursor.fetchall()
            if rows:
                events = []
                for row in rows:
                    # Use the dictionary keys directly, no manual mapping needed
                    event_data = dict(row)
                    event_data["execution_id"] = execution_id
                    event_data["timestamp"] = row["created_at"].isoformat() if row["created_at"] else None
                    event_data["metadata"] = row["meta"]
                    # Parse JSON fields if they're strings
                    if isinstance(row["context"], str):
                        event_data["context"] = json.loads(row["context"])
                    if isinstance(row["result"], str):
                        event_data["result"] = json.loads(row["result"])
                    
                    events.append(event_data)

                def filter_events(event: dict):
                    return event.get("node_id") == "playbook" and event.get("status") == "STARTED"
                # print(json.dumps(events, default=str, indent=2))
                execution_item = next(filter(filter_events, events), None)
                if execution_item is None:
                    logger.error(f"No event node_id:playbook status:STARTED item found for execution_id: {execution_id}")
                return {
                    "execution_id": execution_item["execution_id"],
                    "path": execution_item["node_name"],
                    "status": events[-1].get("status"),
                    "start_time": execution_item["timestamp"],
                    "end_time": events[-1].get("timestamp"),
                    "events": events,
                }