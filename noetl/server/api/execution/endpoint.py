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
                        MAX(created_at) as latest_timestamp
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
                JOIN latest_events le ON e.execution_id = le.execution_id AND e.created_at = le.latest_timestamp
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

                        return {"events": events}

                    return None