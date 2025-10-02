"""
Execution management endpoints for execution data and summaries.
"""

import json
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.core.common import get_async_db_connection, convert_snowflake_ids_for_api, snowflake_id_to_int
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.get("/execution/data/{execution_id}", response_class=JSONResponse)
async def get_execution_data(
    request: Request,
    execution_id: str
):
    try:
        from .service import get_event_service
        
        event_service = get_event_service()
        event = await event_service.get_event(execution_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Execution '{execution_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching execution data: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching execution data: {e}."
        )


@router.get("/events/summary/{execution_id}", response_class=JSONResponse)
async def get_execution_summary(request: Request, execution_id: str):
    """
    Summarize execution events by type and provide quick success/error/skipped counts.
    """
    try:
        counts = {}
        errors = []
        skipped = 0
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT event_type, COUNT(*)
                    FROM noetl.event
                    WHERE execution_id = %s
                    GROUP BY event_type
                    """,
                    (execution_id,)
                )
                rows = await cur.fetchall()
                for et, c in rows:
                    counts[str(et)] = int(c)

            # Count skipped from action_completed payloads
            async with conn.cursor() as cur2:
                await cur2.execute(
                    """
                    SELECT result FROM noetl.event
                    WHERE execution_id = %s AND event_type = 'action_completed'
                    """,
                    (execution_id,)
                )
                rows2 = await cur2.fetchall()
                for (out,) in rows2:
                    try:
                        data = json.loads(out) if isinstance(out, str) else out
                        if isinstance(data, dict) and data.get('skipped') is True:
                            skipped += 1
                    except Exception:
                        pass

            # Last 3 errors
            async with get_async_db_connection() as conn2:
                async with conn2.cursor(row_factory=dict_row) as cur3:
                    await cur3.execute(
                        """
                        SELECT node_name, error, timestamp
                        FROM noetl.event
                        WHERE execution_id = %s AND event_type = 'action_error'
                        ORDER BY timestamp DESC
                        LIMIT 3
                        """,
                        (execution_id,)
                    )
                    errors = await cur3.fetchall() or []
                    # Ensure datetimes are JSON-serializable
                    try:
                        for e in errors:
                            ts = e.get('timestamp') if isinstance(e, dict) else None
                            if ts is not None:
                                try:
                                    e['timestamp'] = ts.isoformat()
                                except Exception:
                                    e['timestamp'] = str(ts)
                    except Exception:
                        pass

        summary = {
            "execution_id": execution_id,
            "counts": counts,
            "skipped": skipped,
            "errors": errors,
        }
        return JSONResponse(content={"status": "ok", "summary": summary})
    except Exception as e:
        logger.exception(f"Error summarizing execution: {e}.")
        return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)


@router.get("/executions", response_class=JSONResponse)
async def get_executions():
    """Get all executions"""
    try:
        from .service import get_event_service
        
        event_service = get_event_service()
        executions = await event_service.get_all_executions()
        # Convert snowflake IDs to strings for API compatibility
        executions = convert_snowflake_ids_for_api(executions)
        return executions
    except Exception as e:
        logger.error(f"Error getting executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/executions/{execution_id}", response_class=JSONResponse)
async def get_execution(execution_id: str):
    try:
        from .service import get_event_service
        
        # Convert execution_id from string to int for database queries
        execution_id_int = snowflake_id_to_int(execution_id)
        
        event_service = get_event_service()
        events = await event_service.get_events_by_execution_id(execution_id_int)

        if not events:
            raise HTTPException(
                status_code=404,
                detail=f"Execution '{execution_id}' not found."
            )

        latest_event = None
        for event in events.get("events", []):
            if not latest_event or (event.get("timestamp", "") > latest_event.get("timestamp", "")):
                latest_event = event

        if not latest_event:
            raise HTTPException(
                status_code=404,
                detail=f"No events found for execution '{execution_id}'."
            )

        metadata = latest_event.get("metadata", {})
        context = latest_event.get("context", {})
        result = latest_event.get("result", {})

        playbook_id = metadata.get('resource_path', context.get('path', ''))
        playbook_name = playbook_id.split('/')[-1] if playbook_id else 'Unknown'

        raw_status = latest_event.get("status", "")
        status = event_service._normalize_status(raw_status)

        timestamps = [event.get("timestamp", "") for event in events.get("events", []) if event.get("timestamp")]
        timestamps.sort()

        start_time = timestamps[0] if timestamps else None
        end_time = timestamps[-1] if timestamps and status in ['completed', 'failed'] else None

        duration = None
        if start_time and end_time:
            try:
                start_dt = datetime.fromisoformat(start_time)
                end_dt = datetime.fromisoformat(end_time)
                duration = (end_dt - start_dt).total_seconds()
            except Exception as e:
                logger.error(f"Error calculating duration: {e}")

        if status in ['completed', 'failed']:
            progress = 100
        elif status == 'running':
            normalized_statuses = [event_service._normalize_status(e.get('status')) for e in events.get('events', [])]
            total = len(normalized_statuses)
            done = sum(1 for s in normalized_statuses if s in {'completed', 'failed'})
            progress = int((done / total) * 100) if total else 0
        else:
            progress = 0

        execution_data = {
            "id": execution_id,
            "playbook_id": playbook_id,
            "playbook_name": playbook_name,
            "status": status,
            "start_time": start_time,
            "end_time": end_time,
            "duration": duration,
            "progress": progress,
            "result": result,
            "error": latest_event.get("error"),
            "events": events.get("events", [])
        }

        # Convert snowflake IDs to strings for API compatibility
        execution_data = convert_snowflake_ids_for_api(execution_data)

        return execution_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))
