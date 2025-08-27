from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
import json
import os
from noetl.common import (
    deep_merge,
    get_pgdb_connection,
    get_async_db_connection,
    get_snowflake_id_str,
    get_snowflake_id,
)
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.common import deep_merge, get_pgdb_connection
from noetl.api.catalog import get_catalog_service
from noetl.logger import setup_logger
import asyncio

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.get("/execution/data/{execution_id}", response_class=JSONResponse)
async def get_execution_data(
    request: Request,
    execution_id: str
):
    try:
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

@router.post("/events", response_class=JSONResponse)
async def create_event(
    request: Request,
    background_tasks: BackgroundTasks
):
    try:
        body = await request.json()
        event_service = get_event_service()
        result = await event_service.emit(body)
        try:
            execution_id = result.get("execution_id") or body.get("execution_id")
            if execution_id:
                # schedule async evaluator without blocking the request
                try:
                    asyncio.create_task(evaluate_broker_for_execution(execution_id))
                except Exception:
                    # fallback to background task for environments without running loop
                    background_tasks.add_task(lambda eid=execution_id: _evaluate_broker_for_execution(eid))
        except Exception:
            pass
        return result
    except Exception as e:
        logger.exception(f"Error creating event: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating event: {e}."
        )

@router.get("/events/by-execution/{execution_id}", response_class=JSONResponse)
async def get_events_by_execution(
    request: Request,
    execution_id: str
):
    """
    Get all events for a specific execution.
    """
    try:
        event_service = get_event_service()
        events = await event_service.get_events_by_execution_id(execution_id)
        if not events:
            raise HTTPException(
                status_code=404,
                detail=f"No events found for execution '{execution_id}'."
            )
        return events

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching events by execution: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching events by execution: {e}"
        )

@router.get("/events/by-id/{event_id}", response_class=JSONResponse)
async def get_event_by_id(
    request: Request,
    event_id: str
):
    """
    Get a single event by its ID.
    """
    try:
        event_service = get_event_service()
        event = await event_service.get_event_by_id(event_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Event with ID '{event_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching event by ID: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching event by ID: {e}"
        )

@router.get("/events/{event_id}", response_class=JSONResponse)
async def get_event(
    request: Request,
    event_id: str
):
    """
    Legacy endpoint for getting events by execution_id or event_id.
    Use /events/by-execution/{execution_id} or /events/by-id/{event_id} instead.
    """
    try:
        event_service = get_event_service()
        event = await event_service.get_event(event_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Event '{event_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching event: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching event: {e}"
        )

@router.get("/events/query", response_class=JSONResponse)
async def get_event_by_query(
    request: Request,
    event_id: str = None
):
    if not event_id:
        raise HTTPException(
            status_code=400,
            detail="event_id query parameter is required."
        )

    try:
        event_service = get_event_service()
        event = await event_service.get_event(event_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Event '{event_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching event: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching event: {e}."
        )


@router.get("/executions", response_class=JSONResponse)
async def get_executions():
    """Get all executions"""
    try:
        event_service = get_event_service()
        executions = await event_service.get_all_executions()
        return executions
    except Exception as e:
        logger.error(f"Error getting executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/executions/{execution_id}", response_class=JSONResponse)
async def get_execution(execution_id: str):
    try:
        event_service = get_event_service()
        events = await event_service.get_events_by_execution_id(execution_id)

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
        input_context = latest_event.get("input_context", {})
        output_result = latest_event.get("output_result", {})

        playbook_id = metadata.get('resource_path', input_context.get('path', ''))
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
            "result": output_result,
            "error": latest_event.get("error"),
            "events": events.get("events", [])
        }

        return execution_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class EventService:
    def __init__(self, pgdb_conn_string: str | None = None):
        pass

    def _normalize_status(self, raw: str | None) -> str:
        if not raw:
            return 'pending'
        s = str(raw).strip().lower()
        if s in {'completed', 'complete', 'success', 'succeeded', 'done'}:
            return 'completed'
        if s in {'error', 'failed', 'failure'}:
            return 'failed'
        if s in {'running', 'run', 'in_progress', 'in-progress', 'progress', 'started', 'start'}:
            return 'running'
        if s in {'created', 'queued', 'pending', 'init', 'initialized', 'new'}:
            return 'pending'
        # fallback
        return 'pending'

    async def get_all_executions(self) -> List[Dict[str, Any]]:
        """
        Get all executions from the event_log table.

        Returns:
            A list of execution data dictionaries
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        WITH latest_events AS (
                            SELECT 
                                execution_id,
                                MAX(timestamp) as latest_timestamp
                            FROM event_log
                            GROUP BY execution_id
                        )
                        SELECT 
                            e.execution_id,
                            e.event_type,
                            e.status,
                            e.timestamp,
                            e.metadata,
                            e.input_context,
                            e.output_result,
                            e.error
                        FROM event_log e
                        JOIN latest_events le ON e.execution_id = le.execution_id AND e.timestamp = le.latest_timestamp
                        ORDER BY e.timestamp DESC
                    """)

                    rows = await cursor.fetchall()
                    executions = []

                    for row in rows:
                        execution_id = row[0]
                        metadata = json.loads(row[4]) if row[4] else {}
                        input_context = json.loads(row[5]) if row[5] else {}
                        output_result = json.loads(row[6]) if row[6] else {}
                        playbook_id = metadata.get('resource_path', input_context.get('path', ''))
                        playbook_name = playbook_id.split('/')[-1] if playbook_id else 'Unknown'
                        raw_status = row[2]
                        status = self._normalize_status(raw_status)

                        start_time = row[3].isoformat() if row[3] else None
                        end_time = None
                        duration = None

                        await cursor.execute("""
                            SELECT MIN(timestamp) FROM event_log WHERE execution_id = %s
                        """, (execution_id,))
                        min_time_row = await cursor.fetchone()
                        if min_time_row and min_time_row[0]:
                            start_time = min_time_row[0].isoformat()

                        if status in ['completed', 'failed']:
                            await cursor.execute("""
                                SELECT MAX(timestamp) FROM event_log WHERE execution_id = %s
                            """, (execution_id,))
                            max_time_row = await cursor.fetchone()
                            if max_time_row and max_time_row[0]:
                                end_time = max_time_row[0].isoformat()

                                if start_time:
                                    start_dt = datetime.fromisoformat(start_time)
                                    end_dt = datetime.fromisoformat(end_time)
                                    duration = (end_dt - start_dt).total_seconds()

                        progress = 100 if status in ['completed', 'failed'] else 0
                        if status == 'running':
                            # Count total events & those considered finished (completed/failed)
                            await cursor.execute("""
                                SELECT status FROM event_log WHERE execution_id = %s
                            """, (execution_id,))
                            event_statuses = [self._normalize_status(r[0]) for r in await cursor.fetchall()]
                            total_steps = len(event_statuses)
                            completed_steps = sum(1 for s in event_statuses if s in {'completed', 'failed'})
                            if total_steps > 0:
                                progress = int((completed_steps / total_steps) * 100)

                        execution_data = {
                            "id": execution_id,
                            "playbook_id": playbook_id,
                            "playbook_name": playbook_name,
                            "status": status,
                            "start_time": start_time,
                            "end_time": end_time,
                            "duration": duration,
                            "progress": progress,
                            "result": output_result,
                            "error": row[7]
                        }

                        executions.append(execution_data)

                    return executions

        except Exception as e:
            logger.exception(f"Error getting all executions: {e}")
            return []

    async def emit(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            event_id = event_data.get("event_id", f"evt_{os.urandom(16).hex()}")
            event_data["event_id"] = event_id
            event_type = event_data.get("event_type", "UNKNOWN")
            status = event_data.get("status", "CREATED")
            parent_event_id = event_data.get("parent_id") or event_data.get("parent_event_id")
            execution_id = event_data.get("execution_id", event_id)
            node_id = event_data.get("node_id", event_id)
            node_name = event_data.get("node_name", event_type)
            node_type = event_data.get("node_type", "event")
            duration = event_data.get("duration", 0.0)
            metadata = event_data.get("meta", {})
            error = event_data.get("error")
            traceback_text = event_data.get("traceback")
            input_context_dict = event_data.get("context", {})
            output_result_dict = event_data.get("result", {})
            input_context = json.dumps(input_context_dict)
            output_result = json.dumps(output_result_dict)
            metadata_str = json.dumps(metadata)

            async with get_async_db_connection() as conn:
                  async with conn.cursor() as cursor:
                      await cursor.execute("""
                          SELECT COUNT(*) FROM event_log
                          WHERE execution_id = %s AND event_id = %s
                      """, (execution_id, event_id))

                      row = await cursor.fetchone()
                      exists = row[0] > 0 if row else False

                      if exists:
                          await cursor.execute("""
                              UPDATE event_log SET
                                  event_type = %s,
                                  status = %s,
                                  duration = %s,
                                  input_context = %s,
                                  output_result = %s,
                                  metadata = %s,
                                  error = %s,
                                  timestamp = CURRENT_TIMESTAMP
                              WHERE execution_id = %s AND event_id = %s
                          """, (
                              event_type,
                              status,
                              duration,
                              input_context,
                              output_result,
                              metadata_str,
                              error,
                              execution_id,
                              event_id
                          ))
                      else:
                          await cursor.execute("""
                              INSERT INTO event_log (
                                  execution_id, event_id, parent_event_id, timestamp, event_type,
                                  node_id, node_name, node_type, status, duration,
                                  input_context, output_result, metadata, error
                              ) VALUES (
                                  %s, %s, %s, CURRENT_TIMESTAMP, %s,
                                  %s, %s, %s, %s, %s,
                                  %s, %s, %s, %s
                              )
                          """, (
                              execution_id,
                              event_id,
                              parent_event_id,
                              event_type,
                              node_id,
                              node_name,
                              node_type,
                              status,
                              duration,
                              input_context,
                              output_result,
                              metadata_str,
                              error
                          ))

                      # Also persist error into error_log when applicable
                      try:
                          status_l = (str(status) if status is not None else '').lower()
                          evt_l = (str(event_type) if event_type is not None else '').lower()
                          is_error = ("error" in status_l) or ("failed" in status_l) or ("error" in evt_l) or (error is not None)
                          if is_error:
                              from noetl.schema import DatabaseSchema
                              ds = DatabaseSchema(auto_setup=False)
                              # Use best-effort fields for error_log
                              err_type = event_type or 'action_error'
                              err_msg = str(error) if error is not None else 'Unknown error'
                              ds.log_error(
                                  error_type=err_type,
                                  error_message=err_msg,
                                  execution_id=execution_id,
                                  step_id=node_id,
                                  step_name=node_name,
                                  template_string=None,
                                  context_data=input_context_dict,
                                  stack_trace=traceback_text,
                                  input_data=input_context_dict,
                                  output_data=output_result_dict,
                                  severity='error'
                              )
                      except Exception:
                          # Do not fail event persistence if error_log write fails
                          pass

                      await conn.commit()

            logger.info(f"Event emitted: {event_id} - {event_type} - {status}")
            return event_data

        except Exception as e:
            logger.exception(f"Error emitting event: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error emitting event: {e}"
            )

    async def get_events_by_execution_id(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """
        Get all events for a specific execution.

        Args:
            execution_id: The ID of the execution

        Returns:
            A dictionary containing events or None if not found
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        SELECT 
                            event_id, 
                            event_type, 
                            node_id, 
                            node_name, 
                            node_type, 
                            status, 
                            duration, 
                            timestamp, 
                            input_context, 
                            output_result, 
                            metadata, 
                            error
                        FROM event_log 
                        WHERE execution_id = %s
                        ORDER BY timestamp
                    """, (execution_id,))

                    rows = await cursor.fetchall()
                    if rows:
                        events = []
                        for row in rows:
                            event_data = {
                                "event_id": row[0],
                                "event_type": row[1],
                                "node_id": row[2],
                                "node_name": row[3],
                                "node_type": row[4],
                                "status": row[5],
                                "duration": row[6],
                                "timestamp": row[7].isoformat() if row[7] else None,
                                "input_context": json.loads(row[8]) if row[8] else None,
                                "output_result": json.loads(row[9]) if row[9] else None,
                                "metadata": json.loads(row[10]) if row[10] else None,
                                "error": row[11],
                                "execution_id": execution_id,
                                "resource_path": None,
                                "resource_version": None,
                                "normalized_status": self._normalize_status(row[5])
                            }

                            if event_data["metadata"] and "playbook_path" in event_data["metadata"]:
                                event_data["resource_path"] = event_data["metadata"]["playbook_path"]

                            if event_data["input_context"] and "path" in event_data["input_context"]:
                                event_data["resource_path"] = event_data["input_context"]["path"]

                            if event_data["input_context"] and "version" in event_data["input_context"]:
                                event_data["resource_version"] = event_data["input_context"]["version"]

                            events.append(event_data)

                        return {"events": events}

                    return None
        except Exception as e:
            logger.exception(f"Error getting events by execution_id: {e}")
            return None

    async def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single event by its ID.

        Args:
            event_id: The ID of the event

        Returns:
            A dictionary containing the event or None if not found
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        SELECT 
                            event_id, 
                            event_type, 
                            node_id, 
                            node_name, 
                            node_type, 
                            status, 
                            duration, 
                            timestamp, 
                            input_context, 
                            output_result, 
                            metadata, 
                            error,
                            execution_id
                        FROM event_log 
                        WHERE event_id = %s
                    """, (event_id,))

                    row = await cursor.fetchone()
                    if row:
                        event_data = {
                            "event_id": row[0],
                            "event_type": row[1],
                            "node_id": row[2],
                            "node_name": row[3],
                            "node_type": row[4],
                            "status": row[5],
                            "duration": row[6],
                            "timestamp": row[7].isoformat() if row[7] else None,
                            "input_context": json.loads(row[8]) if row[8] else None,
                            "output_result": json.loads(row[9]) if row[9] else None,
                            "metadata": json.loads(row[10]) if row[10] else None,
                            "error": row[11],
                            "execution_id": row[12],
                            "resource_path": None,
                            "resource_version": None
                        }
                        if event_data["metadata"] and "playbook_path" in event_data["metadata"]:
                            event_data["resource_path"] = event_data["metadata"]["playbook_path"]

                        if event_data["input_context"] and "path" in event_data["input_context"]:
                            event_data["resource_path"] = event_data["input_context"]["path"]

                        if event_data["input_context"] and "version" in event_data["input_context"]:
                            event_data["resource_version"] = event_data["input_context"]["version"]
                        return {"events": [event_data]}

                    return None
        except Exception as e:
            logger.exception(f"Error getting event by ID: {e}")
            return None

    async def get_event(self, id_param: str) -> Optional[Dict[str, Any]]:
        """
        Get events by execution_id or event_id (legacy method for backward compatibility).

        Args:
            id_param: Either an execution_id or an event_id

        Returns:
            A dictionary containing events or None if not found
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        SELECT COUNT(*) FROM event_log WHERE execution_id = %s
                    """, (id_param,))
                    row = await cursor.fetchone()
                    count = row[0] if row else 0

                    if count > 0:
                        events = await self.get_events_by_execution_id(id_param)
                        if events:
                            return events

                event = await self.get_event_by_id(id_param)
                if event:
                    return event

                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute("""
                            SELECT DISTINCT execution_id FROM event_log
                            WHERE event_id = %s
                        """, (id_param,))
                        execution_ids = [row[0] for row in await cursor.fetchall()]

                        if execution_ids:
                            events = await self.get_events_by_execution_id(execution_ids[0])
                            if events:
                                return events

                return None
        except Exception as e:
            logger.exception(f"Error in get_event: {e}")
            return None

def get_event_service() -> EventService:
    return EventService()



def get_event_service_dependency() -> EventService:
    return EventService()



def _evaluate_broker_for_execution(execution_id: str):
    """Placeholder stub; real implementation assigned later in the file."""
    return None



async def evaluate_broker_for_execution(
    execution_id: str,
    get_async_db_connection=get_async_db_connection,
    get_catalog_service=get_catalog_service,
    AsyncClientClass=None,
):
    """Lightweight async evaluator used for tests.

    This function intentionally accepts its dependencies so tests can inject
    fakes without importing the main server module (which may be large).
    """
    logger.info(f"=== EVALUATE_BROKER_FOR_EXECUTION: Starting evaluation for execution_id={execution_id} ===")
    try:
        playbook_path = None
        playbook_version = None
        workload = {}

        # Read earliest event for execution to extract context
        logger.debug(f"EVALUATE_BROKER_FOR_EXECUTION: Reading event data for execution_id={execution_id}")
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT input_context, metadata FROM event_log
                    WHERE execution_id = %s
                    ORDER BY timestamp ASC
                    LIMIT 1
                    """,
                    (execution_id,)
                )
                row = await cur.fetchone()
                if row:
                    input_context = json.loads(row[0]) if row[0] else {}
                    metadata = json.loads(row[1]) if row[1] else {}
                    playbook_path = input_context.get('path') or metadata.get('playbook_path') or metadata.get('resource_path')
                    playbook_version = input_context.get('version') or metadata.get('resource_version')
                    workload = input_context.get('workload') or {}

        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Extracted playbook_path={playbook_path}, playbook_version={playbook_version}")

        if not playbook_path:
            logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: No playbook_path found for execution_id={execution_id}")
            return

        # Fetch playbook content
        logger.debug(f"EVALUATE_BROKER_FOR_EXECUTION: Fetching playbook content for {playbook_path} v{playbook_version}")
        catalog = get_catalog_service()
        # catalog.fetch_entry may be async
        entry = None
        if asyncio.iscoroutinefunction(getattr(catalog, 'fetch_entry', None)):
            entry = await catalog.fetch_entry(playbook_path, playbook_version or '')
        else:
            entry = catalog.fetch_entry(playbook_path, playbook_version or '')

        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Fetched entry: {entry is not None}")
        if not entry:
            logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: No entry found for playbook {playbook_path}")
            return

        # Parse playbook
        logger.debug(f"EVALUATE_BROKER_FOR_EXECUTION: Parsing playbook content")
        try:
            import yaml

            pb = yaml.safe_load(entry.get('content') or '') or {}
            # Handle different playbook structures
            workflow = pb.get('workflow', [])
            steps = pb.get('steps') or pb.get('tasks') or workflow
            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Found {len(steps)} steps in playbook (workflow: {len(workflow)}, steps: {len(pb.get('steps', []))})")
        except Exception as e:
            logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Error parsing playbook: {e}")
            steps = []

        if not steps:
            logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: No steps found in playbook")
            return

        # Determine next step index by counting completed events and fail-fast if any error
        completed = 0
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT status FROM event_log WHERE execution_id = %s ORDER BY timestamp", (execution_id,))
                rows = await cur.fetchall()
                for r in rows:
                    s = (r[0] or '').lower()
                    if ('failed' in s) or ('error' in s):
                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Detected error status '{s}' for execution {execution_id}; stopping further scheduling")
                        return
                    if 'completed' in s or 'success' in s:
                        completed += 1

        next_idx = completed
        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Completed steps: {completed}, Next step index: {next_idx}, Total steps: {len(steps)}")
        if next_idx >= len(steps):
            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: All steps completed for execution {execution_id}")
            return

        next_step = steps[next_idx]
        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Next step: {next_step}")

        # Normalize to task config
        if isinstance(next_step, dict):
            if 'call' in next_step:
                task_cfg = next_step['call']
            elif 'task' in next_step:
                task_cfg = next_step['task']
            elif 'action' in next_step:
                task_cfg = {'type': next_step.get('action'), 'config': next_step.get('config', {})}
            elif 'step' in next_step:
                # Handle workflow format with 'step' entries
                step_name = next_step.get('step')
                if step_name == 'start':
                    # Start step is just a control step, create a simple task
                    task_cfg = {'type': 'python', 'name': 'start', 'code': 'pass'}
                elif step_name == 'end':
                    # End step is just a control step
                    task_cfg = {'type': 'python', 'name': 'end', 'code': 'pass'}
                elif 'type' in next_step and next_step['type'] == 'workbook':
                    # Handle workbook steps
                    task_cfg = {
                        'type': next_step.get('type', 'workbook'),
                        'name': next_step.get('name', step_name),
                        'with': next_step.get('with', {})
                    }
                else:
                    # For other control steps, create a simple task
                    task_cfg = {'type': 'python', 'name': step_name, 'code': 'pass'}
            else:
                task_cfg = next_step
        else:
            return

        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Created task config: {task_cfg}")

        # Pick a worker base_url from runtime table (first ready)
        worker_base = None
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT base_url FROM runtime WHERE component_type = 'worker_pool' AND status = 'ready' ORDER BY updated_at LIMIT 1")
                r = await cur.fetchone()
                if r:
                    worker_base = r[0]

        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Found worker_base: {worker_base}")

        # For queue-based execution, we don't need a specific worker to be registered
        # Any worker can pick up jobs from the queue
        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Enqueuing job for execution {execution_id}, step {next_idx+1}")
        try:
            # Enqueue job for worker instead of direct HTTP call
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO noetl.queue (execution_id, node_id, action, input_context, priority, max_attempts, available_at)
                        VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            execution_id,
                            f"{execution_id}-step-{next_idx+1}",
                            json.dumps(task_cfg),
                            json.dumps(workload),
                            0,  # priority
                            5,  # max_attempts
                            None,  # available_at (now)
                        )
                    )
                    job_row = await cur.fetchone()
                    await conn.commit()

            logger.info(f"Enqueued job {job_row[0] if job_row else 'unknown'} for execution {execution_id}, step {next_idx+1}")
        except Exception as e:
            logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Error enqueuing job: {e}")
            import traceback
            logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Traceback: {traceback.format_exc()}")

        return

    except Exception:
        # swallow errors in test helper
        return
