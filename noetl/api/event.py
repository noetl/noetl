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

@router.post("/context/render", response_class=JSONResponse)
async def render_context(request: Request):
    """
    Render a Jinja2 template/object against the server-side execution context.
    Body:
      { execution_id: str, template: any, extra_context?: dict, strict?: bool }
    Context composed from DB:
      - work: workload (from earliest event input_context.workload, if present)
      - results: map of node_name -> output_result for all prior events in execution
    """
    try:
        body = await request.json()
        execution_id = body.get("execution_id")
        template = body.get("template")
        extra_context = body.get("extra_context") or {}
        strict = bool(body.get("strict", True))
        if not execution_id:
            raise HTTPException(status_code=400, detail="execution_id is required")
        if "template" not in body:
            raise HTTPException(status_code=400, detail="template is required")

        workload = {}
        results: Dict[str, Any] = {}
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT input_context FROM event_log
                    WHERE execution_id = %s
                    ORDER BY timestamp ASC
                    LIMIT 1
                    """,
                    (execution_id,)
                )
                row = await cur.fetchone()
                if row and row.get("input_context"):
                    try:
                        ctx_first = json.loads(row["input_context"]) if isinstance(row["input_context"], str) else row["input_context"]
                        workload = (ctx_first or {}).get("workload") or {}
                    except Exception:
                        workload = {}

                await cur.execute(
                    """
                    SELECT node_name, output_result
                    FROM event_log
                    WHERE execution_id = %s
                    ORDER BY timestamp
                    """,
                    (execution_id,)
                )
                rows = await cur.fetchall()
                for r in rows:
                    node_name = r.get("node_name")
                    out = r.get("output_result")
                    if node_name and out:
                        try:
                            results[node_name] = json.loads(out) if isinstance(out, str) else out
                        except Exception:
                            results[node_name] = out

        base_ctx: Dict[str, Any] = {"work": workload, "workload": workload, "results": results}
        # Allow direct references to prior step names (e.g., {{ evaluate_weather_directly.* }})
        try:
            if isinstance(results, dict):
                base_ctx.update(results)
        except Exception:
            pass
        # Back-compat: expose workload fields at top level (e.g., {{ temperature_threshold }})
        base_ctx["context"] = base_ctx["work"]
        if isinstance(workload, dict):
            try:
                base_ctx.update(workload)
            except Exception:
                pass
        # Merge any extra context provided by caller (env, job, etc.)
        if isinstance(extra_context, dict):
            try:
                base_ctx.update(extra_context)
                # Ensure job.uuid exists if job provided without uuid
                job_obj = base_ctx.get("job")
                if isinstance(job_obj, dict) and "uuid" not in job_obj:
                    # Reuse id when present to keep stability
                    if "id" in job_obj and job_obj["id"] is not None:
                        job_obj["uuid"] = str(job_obj["id"])
                    else:
                        from uuid import uuid4
                        job_obj["uuid"] = str(uuid4())
            except Exception:
                pass

        # If template contains a 'work' object, merge it into the rendering context so
        # step-scoped values like {{ city }} are available during task rendering.
        try:
            if isinstance(template, dict) and isinstance(template.get("work"), dict):
                incoming_work = template.get("work") or {}
                # Promote incoming work to top-level keys
                base_ctx["work"] = incoming_work
                base_ctx["context"] = incoming_work
                for k, v in incoming_work.items():
                    # do not overwrite existing keys from results unless missing
                    if k not in base_ctx:
                        base_ctx[k] = v
        except Exception:
            pass

        from jinja2 import Environment, StrictUndefined, BaseLoader
        from noetl.render import render_template
        env = Environment(loader=BaseLoader(), undefined=StrictUndefined)

        # Best-effort rendering: render 'work' and 'task' separately to avoid failing the whole request
        rendered: Any
        if isinstance(template, dict):
            out: Dict[str, Any] = {}
            if 'work' in template:
                try:
                    out['work'] = render_template(env, template.get('work'), base_ctx, rules=None, strict_keys=False)
                except Exception:
                    out['work'] = template.get('work')
            if 'task' in template:
                task_tpl = template.get('task')
                try:
                    # Render task non-strict to avoid error logs for not-yet-defined values
                    # The worker has fallbacks for unresolved 'with' params (alerts/items/city)
                    task_rendered = render_template(env, task_tpl, base_ctx, rules=None, strict_keys=False)
                except Exception:
                    task_rendered = task_tpl
                # If task is a JSON string, try parsing to dict for convenience
                if isinstance(task_rendered, str):
                    try:
                        import json as _json
                        out['task'] = _json.loads(task_rendered)
                    except Exception:
                        out['task'] = task_rendered
                else:
                    out['task'] = task_rendered
            # Pass through any other keys without rendering
            for k, v in template.items():
                if k not in out:
                    out[k] = v
            rendered = out
        else:
            # Single value template
            try:
                rendered = render_template(env, template, base_ctx, rules=None, strict_keys=False)
            except Exception:
                rendered = template

        return {"status": "ok", "rendered": rendered, "context_keys": list(base_ctx.keys())}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error rendering context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
                try:
                    asyncio.create_task(evaluate_broker_for_execution(execution_id))
                except Exception:
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
            trace_component = event_data.get("trace_component")
            error = event_data.get("error")
            traceback_text = event_data.get("traceback")
            input_context_dict = event_data.get("context", {})
            output_result_dict = event_data.get("result", {})
            input_context = json.dumps(input_context_dict)
            output_result = json.dumps(output_result_dict)
            metadata_str = json.dumps(metadata)
            trace_component_str = json.dumps(trace_component) if trace_component is not None else None

            async with get_async_db_connection() as conn:
                  async with conn.cursor() as cursor:
                      await cursor.execute("""
                          SELECT COUNT(*) FROM event_log
                          WHERE execution_id = %s AND event_id = %s
                      """, (execution_id, event_id))

                      row = await cursor.fetchone()
                      exists = row[0] > 0 if row else False

                      loop_id_val = event_data.get('loop_id')
                      loop_name_val = event_data.get('loop_name')
                      iterator_val = event_data.get('iterator')
                      current_index_val = event_data.get('current_index')
                      current_item_val = json.dumps(event_data.get('current_item')) if event_data.get('current_item') is not None else None

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
                                  trace_component = %s::jsonb,
                                  loop_id = %s,
                                  loop_name = %s,
                                  iterator = %s,
                                  current_index = %s,
                                  current_item = %s,
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
                              trace_component_str,
                              loop_id_val,
                              loop_name_val,
                              iterator_val,
                              current_index_val,
                              current_item_val,
                              execution_id,
                              event_id
                          ))
                      else:
                          await cursor.execute("""
                              INSERT INTO event_log (
                                  execution_id, event_id, parent_event_id, timestamp, event_type,
                                  node_id, node_name, node_type, status, duration,
                                  input_context, output_result, metadata, error, trace_component,
                                  loop_id, loop_name, iterator, current_index, current_item
                              ) VALUES (
                                  %s, %s, %s, CURRENT_TIMESTAMP, %s,
                                  %s, %s, %s, %s, %s,
                                  %s, %s, %s, %s,
                                  %s,
                                  %s, %s, %s, %s, %s
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
                              error,
                              trace_component_str,
                              loop_id_val,
                              loop_name_val,
                              iterator_val,
                              current_index_val,
                              current_item_val
                          ))

                      try:
                          status_l = (str(status) if status is not None else '').lower()
                          evt_l = (str(event_type) if event_type is not None else '').lower()
                          is_error = ("error" in status_l) or ("failed" in status_l) or ("error" in evt_l) or (error is not None)
                          if is_error:
                              from noetl.schema import DatabaseSchema
                              ds = DatabaseSchema(auto_setup=False)
                              err_type = event_type or 'action_error'
                              err_msg = str(error) if error is not None else 'Unknown error'
                              await ds.log_error_async(
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
                          pass

                      try:
                          if str(event_type).lower() in {"execution_start", "execution_started", "start"}:
                              try:
                                  await cursor.execute(
                                      """
                                      INSERT INTO workload (execution_id, data)
                                      VALUES (%s, %s)
                                      ON CONFLICT (execution_id) DO UPDATE SET data = EXCLUDED.data
                                      """,
                                      (execution_id, input_context)
                                  )
                              except Exception:
                                  pass
                      except Exception:
                          pass

                      await conn.commit()

            logger.info(f"Event emitted: {event_id} - {event_type} - {status}")

            try:
                evt_l = (str(event_type) if event_type is not None else '').lower()
                if evt_l in {"execution_start", "action_completed", "action_error"}:
                    try:
                        if asyncio.get_event_loop().is_running():
                            asyncio.create_task(evaluate_broker_for_execution(execution_id))
                        else:
                            await evaluate_broker_for_execution(execution_id)
                    except RuntimeError:
                        await evaluate_broker_for_execution(execution_id)
            except Exception:
                logger.debug("Failed to schedule broker evaluation from emit", exc_info=True)

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
    """Server-side broker evaluator.

    - Builds execution context (workload + results) from event_log
    - Parses playbook and advances to the next actionable step
    - Evaluates step-level pass/when using server-side rendering
    - Emits skip-complete events for skipped steps
    - Enqueues the first actionable step to the queue for workers
    """
    logger.info(f"=== EVALUATE_BROKER_FOR_EXECUTION: Starting for execution_id={execution_id} ===")
    try:
        playbook_path = None
        playbook_version = None
        workload = {}
        results_ctx: Dict[str, Any] = {}

        logger.debug(f"EVALUATE_BROKER_FOR_EXECUTION: Reading execution context for {execution_id}")
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
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
                    try:
                        input_context = json.loads(row["input_context"]) if row.get("input_context") else {}
                    except Exception:
                        input_context = row.get("input_context") or {}
                    try:
                        metadata = json.loads(row["metadata"]) if row.get("metadata") else {}
                    except Exception:
                        metadata = row.get("metadata") or {}
                    playbook_path = input_context.get('path') or metadata.get('playbook_path') or metadata.get('resource_path')
                    playbook_version = input_context.get('version') or metadata.get('resource_version')
                    workload = input_context.get('workload') or {}

                await cur.execute(
                    """
                    SELECT node_name, output_result
                    FROM event_log
                    WHERE execution_id = %s AND output_result IS NOT NULL
                    ORDER BY timestamp
                    """,
                    (execution_id,)
                )
                rows = await cur.fetchall()
                for r in rows:
                    node_name = r.get("node_name")
                    out = r.get("output_result")
                    if not node_name:
                        continue
                    try:
                        results_ctx[node_name] = json.loads(out) if isinstance(out, str) else out
                    except Exception:
                        results_ctx[node_name] = out

        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Playbook path={playbook_path}, version={playbook_version}")
        if not playbook_path:
            logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: No playbook_path found for execution_id={execution_id}")
            return

        catalog = get_catalog_service()
        entry = None
        if asyncio.iscoroutinefunction(getattr(catalog, 'fetch_entry', None)):
            entry = await catalog.fetch_entry(playbook_path, playbook_version or '')
        else:
            entry = catalog.fetch_entry(playbook_path, playbook_version or '')
        if not entry:
            logger.warning(f"EVALUATE_BROKER_FOR_EXECUTION: No entry found for playbook {playbook_path}")
            return

        try:
            import yaml
            pb = yaml.safe_load(entry.get('content') or '') or {}
            workflow = pb.get('workflow', [])
            steps = pb.get('steps') or pb.get('tasks') or workflow
            tasks_def_list = pb.get('workbook') or pb.get('tasks') or []
            tasks_def_map: Dict[str, Any] = {}
            if isinstance(tasks_def_list, list):
                for _t in tasks_def_list:
                    if isinstance(_t, dict):
                        _nm = _t.get('name') or _t.get('task')
                        if _nm:
                            tasks_def_map[str(_nm)] = _t
        except Exception as e:
            logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Error parsing playbook: {e}")
            steps = []
        if not steps:
            logger.warning("EVALUATE_BROKER_FOR_EXECUTION: No steps found in playbook")
            return

        try:
            tasks_def_list = pb.get('workbook') or pb.get('tasks') or []
            tasks_def_map = {}
            if isinstance(tasks_def_list, list):
                for t in tasks_def_list:
                    if isinstance(t, dict):
                        nm = t.get('name') or t.get('task')
                        if nm:
                            tasks_def_map[str(nm)] = t
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cur:
                    for i, st in enumerate(steps):
                        if not isinstance(st, dict):
                            continue
                        sname = st.get('step') or st.get('name') or st.get('task') or f"step-{i+1}"
                        stype = st.get('type') or ('workbook' if 'task' in st else None)
                        sdesc = st.get('desc') or st.get('description')
                        sid = f"{execution_id}-step-{i+1}"
                        try:
                            await cur.execute(
                                """
                                INSERT INTO noetl.workflow (execution_id, step_id, step_name, step_type, description, raw_config)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT DO NOTHING
                                """,
                                (execution_id, sid, sname, stype, sdesc, json.dumps(st))
                            )
                        except Exception:
                            pass

                    for st in steps:
                        if not isinstance(st, dict):
                            continue
                        from_name = st.get('step') or st.get('name') or st.get('task')
                        nxt = st.get('next') or []
                        if not from_name or not isinstance(nxt, list):
                            continue
                        for case in nxt:
                            if not isinstance(case, dict):
                                continue
                            cond_text = None
                            targets = None
                            if 'when' in case:
                                cond_text = case.get('when')
                                targets = case.get('then')
                            elif 'else' in case:
                                cond_text = 'else'
                                targets = case.get('else')
                            if not isinstance(targets, list):
                                continue
                            for tgt in targets:
                                to_name = None
                                with_params = None
                                if isinstance(tgt, dict):
                                    to_name = tgt.get('step') or tgt.get('name') or tgt.get('task')
                                    with_params = tgt.get('with')
                                else:
                                    to_name = str(tgt)
                                if not to_name:
                                    continue
                                try:
                                    await cur.execute(
                                        """
                                        INSERT INTO noetl.transition (execution_id, from_step, to_step, condition, with_params)
                                        VALUES (%s, %s, %s, %s, %s)
                                        ON CONFLICT DO NOTHING
                                        """,
                                        (execution_id, from_name, to_name, cond_text or '', json.dumps(with_params) if with_params is not None else None)
                                    )
                                except Exception:
                                    pass

                    if isinstance(tasks_def_list, list):
                        for wi, wt in enumerate(tasks_def_list, start=1):
                            if not isinstance(wt, dict):
                                continue
                            tname = wt.get('name') or wt.get('task') or f"task-{wi}"
                            ttype = (wt.get('type') or '').lower() or 'workbook'
                            tid = f"{execution_id}-wtask-{wi}"
                            try:
                                await cur.execute(
                                    """
                                    INSERT INTO noetl.workbook (execution_id, task_id, task_name, task_type, raw_config)
                                    VALUES (%s, %s, %s, %s, %s)
                                    ON CONFLICT DO NOTHING
                                    """,
                                    (execution_id, tid, tname, ttype, json.dumps(wt))
                                )
                            except Exception:
                                pass
                    try:
                        await conn.commit()
                    except Exception:
                        pass
        except Exception:
            logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Materialization failed", exc_info=True)

        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT status FROM event_log WHERE execution_id = %s ORDER BY timestamp",
                    (execution_id,)
                )
                rows = await cur.fetchall()
                for r in rows:
                    s = (r[0] or '').lower()
                    if ('failed' in s) or ('error' in s):
                        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Found error status '{s}' for {execution_id}; stop scheduling")
                        return

        from jinja2 import Environment, StrictUndefined, BaseLoader
        from noetl.render import render_template
        jenv = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        base_ctx = {
            "work": workload,
            "workload": workload,
            "results": results_ctx,
            "context": workload,
        }
        # Promote step results and workload fields to top-level for direct Jinja access
        try:
            if isinstance(results_ctx, dict):
                base_ctx.update(results_ctx)
        except Exception:
            pass
        try:
            if isinstance(workload, dict):
                for k, v in workload.items():
                    if k not in base_ctx:
                        base_ctx[k] = v
        except Exception:
            pass
        # Alias workbook task results under their workflow step names (e.g., aggregate_alerts -> aggregate_alerts_task)
        try:
            if isinstance(steps, list):
                for st in steps:
                    if isinstance(st, dict) and (st.get('type') or '').lower() == 'workbook':
                        step_nm = st.get('step') or st.get('name') or st.get('task')
                        task_nm = st.get('task') or st.get('name') or step_nm
                        if step_nm and task_nm and isinstance(results_ctx, dict) and task_nm in results_ctx and step_nm not in base_ctx:
                            base_ctx[step_nm] = results_ctx[task_nm]
        except Exception:
            pass

        step_index: Dict[str, int] = {}
        for i, st in enumerate(steps):
            if isinstance(st, dict):
                _nm = st.get('step') or st.get('name') or st.get('task')
                if _nm:
                    step_index[str(_nm)] = i

        idx: Optional[int] = None
        chosen_target_name: Optional[str] = None
        transition_cond_text: Optional[str] = None
        transition_vars: Optional[Dict[str, Any]] = None
        last_step_name: Optional[str] = None
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT node_name FROM event_log
                    WHERE execution_id = %s AND lower(status) IN ('completed','success')
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (execution_id,)
                )
                rr = await cur.fetchone()
                if rr:
                    last_step_name = rr.get('node_name')

        if last_step_name and last_step_name in step_index:
            prev_cfg = steps[step_index[last_step_name]]
            nxt = prev_cfg.get('next') if isinstance(prev_cfg, dict) else None
            if isinstance(nxt, list):
                for case in nxt:
                    if not isinstance(case, dict):
                        continue
                    if 'when' in case:
                        cond_text = case.get('when')
                        try:
                            cond_val = render_template(jenv, cond_text, base_ctx, strict_keys=False)
                        except Exception:
                            cond_val = False
                        if bool(cond_val):
                            targets = case.get('then')
                            if isinstance(targets, list) and targets:
                                tgt = targets[0]
                                if isinstance(tgt, dict):
                                    chosen_target_name = tgt.get('step') or tgt.get('name') or tgt.get('task')
                                    transition_vars = tgt.get('with')
                                else:
                                    chosen_target_name = str(tgt)
                                transition_cond_text = str(cond_text)
                                break
                    elif 'else' in case:
                        targets = case.get('else')
                        if isinstance(targets, list) and targets:
                            tgt = targets[0]
                            if isinstance(tgt, dict):
                                chosen_target_name = tgt.get('step') or tgt.get('name') or tgt.get('task')
                                transition_vars = tgt.get('with')
                            else:
                                chosen_target_name = str(tgt)
                            transition_cond_text = 'else'
                            break
        if chosen_target_name and chosen_target_name in step_index:
            idx = step_index[chosen_target_name]
            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Next step via transition: {chosen_target_name} (idx={idx})")
        if idx is None:
            completed = 0
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT status FROM event_log WHERE execution_id = %s ORDER BY timestamp", (execution_id,))
                    rows = await cur.fetchall()
                    for r in rows:
                        s = (r[0] or '').lower()
                        if 'completed' in s or 'success' in s:
                            completed += 1
            idx = completed
            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Fallback next index={idx}")
        if idx is None or idx >= len(steps):
            logger.info("EVALUATE_BROKER_FOR_EXECUTION: No further steps to schedule")
            return

        from jinja2 import Environment, StrictUndefined, BaseLoader
        from noetl.render import render_template
        jenv = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        base_ctx = {
            "work": workload,
            "workload": workload,
            "results": results_ctx,
            "context": workload,
        }
        try:
            if isinstance(results_ctx, dict):
                base_ctx.update(results_ctx)
        except Exception:
            pass
        try:
            if isinstance(workload, dict):
                for k, v in workload.items():
                    if k not in base_ctx:
                        base_ctx[k] = v
        except Exception:
            pass
        try:
            if isinstance(steps, list):
                for st in steps:
                    if isinstance(st, dict) and (st.get('type') or '').lower() == 'workbook':
                        step_nm = st.get('step') or st.get('name') or st.get('task')
                        task_nm = st.get('task') or st.get('name') or step_nm
                        if step_nm and task_nm and isinstance(results_ctx, dict) and task_nm in results_ctx and step_nm not in base_ctx:
                            base_ctx[step_nm] = results_ctx[task_nm]
        except Exception:
            pass

        event_service = get_event_service()
        while idx < len(steps):
            step = steps[idx]
            if not isinstance(step, dict):
                break

            step_name = step.get('step') or step.get('task') or step.get('name') or f"step-{idx+1}"
            skip_reason = None
            if 'pass' in step:
                try:
                    pass_val = render_template(jenv, step.get('pass'), base_ctx, strict_keys=False)
                except Exception:
                    pass_val = step.get('pass')
                if isinstance(pass_val, str):
                    pv = pass_val.strip().lower()
                    pass_bool = pv in {'1','true','yes','on'}
                else:
                    pass_bool = bool(pass_val)
                if pass_bool:
                    skip_reason = 'pass=true'

            if skip_reason is None and 'when' in step:
                try:
                    when_val = render_template(jenv, step.get('when'), base_ctx, strict_keys=False)
                except Exception:
                    when_val = step.get('when')
                when_bool = bool(when_val)
                if isinstance(when_val, str):
                    wv = when_val.strip().lower()
                    if wv in {'', '0', 'false', 'no', 'off', 'none', 'null'}:
                        when_bool = False
                if not when_bool:
                    skip_reason = 'when=false'

            if skip_reason:
                logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Skipping step {idx+1} ({step_name}) due to {skip_reason}")
                try:
                    await event_service.emit({
                        "execution_id": execution_id,
                        "event_type": "action_completed",
                        "status": "COMPLETED",
                        "node_id": f"{execution_id}-step-{idx+1}",
                        "node_name": step_name,
                        "node_type": "task",
                        "result": {"skipped": True, "reason": skip_reason},
                        "context": {"workload": workload},
                    })
                except Exception:
                    logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to emit skip event", exc_info=True)
                idx += 1
                continue
            break

        if idx >= len(steps):
            logger.info("EVALUATE_BROKER_FOR_EXECUTION: All remaining steps were skipped")
            return

        next_step = steps[idx]
        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Next actionable step index={idx}, def={next_step}")

        if isinstance(next_step, dict):
            _sname = next_step.get('step') or next_step.get('name')
            _stype = (next_step.get('type') or '').lower()
            if (_sname in {'start', 'end'} or (_stype == '' and not any(k in next_step for k in ('task','action','call','loop')))) and ('loop' not in next_step):
                try:
                    await get_event_service().emit({
                        'execution_id': execution_id,
                        'event_type': 'action_completed',
                        'status': 'COMPLETED',
                        'node_id': f'{execution_id}-step-{idx+1}',
                        'node_name': _sname or f'step-{idx+1}',
                        'node_type': 'task',
                        'result': {'skipped': True, 'reason': 'control_step'},
                        'context': {'workload': workload}
                    })
                except Exception:
                    logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to emit control step completion", exc_info=True)
                return

        if isinstance(next_step, dict) and 'loop' in next_step:
            loop_spec = next_step.get('loop') or {}
            iterator = (loop_spec.get('iterator') or 'item').strip()
            try:
                items = render_template(jenv, loop_spec.get('in', []), base_ctx, strict_keys=False)
                if isinstance(items, str):
                    try:
                        items = json.loads(items)
                    except Exception:
                        items = [items]
            except Exception:
                items = []
            if not isinstance(items, list):
                items = []
            flt = loop_spec.get('filter')
            def _passes(it):
                if not flt:
                    return True
                try:
                    fctx = dict(base_ctx)
                    fctx[iterator] = it
                    val = render_template(jenv, flt, fctx, strict_keys=False)
                    if val is None:
                        return True
                    if isinstance(val, str) and val.strip() == "":
                        return True
                    return bool(val)
                except Exception:
                    return True
            body_step = None
            nxt = next_step.get('next') or []
            if isinstance(nxt, list) and nxt:
                t = nxt[0]
                body_step = (t.get('step') or t.get('name') or t.get('task')) if isinstance(t, dict) else str(t)
            body_task_cfg = None
            # Determine the concrete body step configuration from the workflow definition
            body_step_cfg = None
            try:
                for st_cfg in steps:
                    if isinstance(st_cfg, dict) and (
                        st_cfg.get('step') == body_step or st_cfg.get('name') == body_step or st_cfg.get('task') == body_step
                    ):
                        body_step_cfg = st_cfg
                        break
            except Exception:
                body_step_cfg = None

            if isinstance(body_step_cfg, dict):
                if 'call' in body_step_cfg:
                    body_task_cfg = body_step_cfg['call']
                elif 'action' in body_step_cfg:
                    body_task_cfg = {"type": body_step_cfg.get('action'), **({k: v for k, v in body_step_cfg.items() if k not in {'action'}})}
                elif (body_step_cfg.get('type') or '').lower() == 'workbook':
                    # Resolve workbook task by its task/name
                    tname = body_step_cfg.get('task') or body_step_cfg.get('name') or body_step
                    base_task = locals().get('tasks_def_map', {}).get(str(tname), {})
                    if not isinstance(base_task, dict) or not base_task:
                        try:
                            _tlist = (locals().get('pb') or {}).get('workbook') or (locals().get('pb') or {}).get('tasks') or []
                            for _t in _tlist:
                                if isinstance(_t, dict) and (_t.get('name') == tname or _t.get('task') == tname):
                                    base_task = _t
                                    break
                        except Exception:
                            pass
                    if isinstance(base_task, dict) and base_task:
                        body_task_cfg = dict(base_task)
                        sw = body_step_cfg.get('with', {}) if isinstance(body_step_cfg.get('with'), dict) else {}
                        bw = base_task.get('with', {}) if isinstance(base_task.get('with'), dict) else {}
                        mw = {**bw, **sw}
                        if mw:
                            body_task_cfg['with'] = mw
            # Final fallback to a no-op python task to keep pipeline moving
            if body_task_cfg is None:
                body_task_cfg = {'type': 'python', 'name': body_step or (next_step.get('step') or 'loop_body'), 'code': 'def main(**kwargs):\n    return {}'}

            scheduled_any = False
            for idx_it, item in enumerate(items):
                if not _passes(item):
                    continue
                iter_node_id = f"{execution_id}-step-{idx+1}-iter-{idx_it}"
                try:
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("SELECT 1 FROM noetl.queue WHERE execution_id=%s AND node_id=%s LIMIT 1", (execution_id, iter_node_id))
                            if await cur.fetchone():
                                continue
                except Exception:
                    pass
                iter_work = dict(workload) if isinstance(workload, dict) else {}
                iter_work[iterator] = item
                try:
                    rendered_work = render_template(jenv, iter_work, base_ctx, strict_keys=False)
                except Exception:
                    rendered_work = iter_work
                try:
                    if isinstance(rendered_work, dict):
                        rendered_work['_loop'] = {
                            'loop_id': f"{execution_id}:{prev_cfg.get('step')}",
                            'loop_name': prev_cfg.get('step') or prev_cfg.get('name'),
                            'iterator': iterator,
                            'current_index': idx_it,
                            'current_item': item,
                            'items_count': len(items)
                        }
                except Exception:
                    pass
                try:
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                """
                                INSERT INTO noetl.queue (execution_id, node_id, action, input_context, priority, max_attempts, available_at)
                                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
                                RETURNING id
                                """,
                                (execution_id, iter_node_id, json.dumps(body_task_cfg), json.dumps(rendered_work), 0, 5, None)
                            )
                            await conn.commit()
                    scheduled_any = True
                except Exception:
                    logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to enqueue loop iteration (next_step)", exc_info=True)
            if scheduled_any:
                try:
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                """
                                INSERT INTO noetl.transition (execution_id, from_step, to_step, condition, with_params)
                                VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT DO NOTHING
                                """,
                                (execution_id, next_step.get('step') or next_step.get('name'), body_step, 'evaluated:direct', None)
                            )
                            await conn.commit()
                except Exception:
                    pass
                return

        if isinstance(next_step, dict) and 'end_loop' in next_step:
            loop_name = next_step.get('end_loop')
            end_step_name = next_step.get('step') or f"end_{loop_name}"
            try:
                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "SELECT 1 FROM noetl.event_log WHERE execution_id=%s AND node_name=%s AND lower(status) IN ('completed','success') LIMIT 1",
                            (execution_id, end_step_name)
                        )
                        done = await cur.fetchone()
                        if done:
                            return
            except Exception:
                pass

            loop_cfg = None
            for st in steps:
                if isinstance(st, dict) and (st.get('step') == loop_name or st.get('name') == loop_name):
                    loop_cfg = st; break
            first_body = None
            if isinstance(loop_cfg, dict):
                nxt = loop_cfg.get('next') or []
                if isinstance(nxt, list) and nxt:
                    t = nxt[0]
                    if isinstance(t, dict):
                        first_body = t.get('step') or t.get('name') or t.get('task')
                    else:
                        first_body = str(t)
            loop_results = []
            try:
                async with get_async_db_connection() as conn:
                    async with conn.cursor(row_factory=dict_row) as cur:
                        if first_body:
                            await cur.execute(
                                """
                                SELECT node_id, output_result FROM noetl.event_log
                                WHERE execution_id=%s AND node_name=%s AND lower(status) IN ('completed','success')
                                ORDER BY timestamp
                                """,
                                (execution_id, first_body)
                            )
                            rows = await cur.fetchall()
                            for r in rows:
                                data = r.get('output_result')
                                try:
                                    data = json.loads(data) if isinstance(data, str) else data
                                except Exception:
                                    pass
                                loop_results.append({first_body: data})

                        # Fallback: if the first body step is a workbook wrapper that produced empty
                        # results, try to use its underlying task's results (e.g., evaluate_weather_directly)
                        try:
                            if (not loop_results) or all(
                                isinstance(item.get(first_body), dict) and not item.get(first_body)
                                for item in loop_results if isinstance(item, dict)
                            ):
                                # Find the step config to resolve its workbook task name
                                fallback_name = None
                                for st_cfg in steps:
                                    if isinstance(st_cfg, dict) and (
                                        st_cfg.get('step') == first_body or st_cfg.get('name') == first_body
                                    ):
                                        if (st_cfg.get('type') or '').lower() == 'workbook':
                                            fallback_name = st_cfg.get('task') or st_cfg.get('name')
                                        break
                                if fallback_name:
                                    await cur.execute(
                                        """
                                        SELECT node_id, output_result FROM noetl.event_log
                                        WHERE execution_id=%s AND node_name=%s AND lower(status) IN ('completed','success')
                                        ORDER BY timestamp
                                        """,
                                        (execution_id, fallback_name)
                                    )
                                    rows = await cur.fetchall()
                                    tmp_results = []
                                    for r in rows:
                                        data = r.get('output_result')
                                        try:
                                            data = json.loads(data) if isinstance(data, str) else data
                                        except Exception:
                                            pass
                                        tmp_results.append({first_body: data})
                                    if tmp_results:
                                        loop_results = tmp_results
                        except Exception:
                            pass
            except Exception:
                pass

            agg_result = {}
            try:
                result_map = next_step.get('result') or {}
                agg_ctx = dict(base_ctx)
                agg_ctx[f"{loop_name}_results"] = loop_results
                agg_ctx["loop_results"] = loop_results
                if isinstance(result_map, dict):
                    for k, v in result_map.items():
                        try:
                            agg_result[k] = render_template(jenv, v, agg_ctx, strict_keys=False)
                        except Exception:
                            agg_result[k] = v
            except Exception:
                pass

            try:
                await get_event_service().emit({
                    'execution_id': execution_id,
                    'event_type': 'action_completed',
                    'status': 'COMPLETED',
                    'node_id': f'{execution_id}-step-{idx+1}',
                    'node_name': end_step_name,
                    'node_type': 'task',
                    'result': agg_result or {'results': loop_results},
                    'context': {'workload': workload},
                })
            except Exception:
                logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to emit end_loop aggregation", exc_info=True)
            return

        if last_step_name and isinstance(prev_cfg := steps[step_index[last_step_name]], dict) and 'loop' in prev_cfg:
            loop_spec = prev_cfg.get('loop') or {}
            iterator = (loop_spec.get('iterator') or 'item').strip()
            items = []
            try:
                items = render_template(jenv, loop_spec.get('in', []), base_ctx, strict_keys=False)
                if isinstance(items, str):
                    try:
                        items = json.loads(items)
                    except Exception:
                        items = [items]
            except Exception:
                items = []
            if not isinstance(items, list):
                items = []
            filter_expr = loop_spec.get('filter')
            def _passes(it):
                if not filter_expr:
                    return True
                try:
                    fctx = dict(base_ctx)
                    fctx[iterator] = it
                    val = render_template(jenv, filter_expr, fctx, strict_keys=False)
                    return bool(val)
                except Exception:
                    return True
            body_step_name = None
            prev_nxt = prev_cfg.get('next') or []
            if isinstance(prev_nxt, list) and prev_nxt:
                t = prev_nxt[0]
                body_step_name = (t.get('step') or t.get('name') or t.get('task')) if isinstance(t, dict) else str(t)
            body_task_cfg = None
            if isinstance(next_step, dict):
                if 'call' in next_step:
                    body_task_cfg = next_step['call']
                elif 'action' in next_step:
                    body_task_cfg = {"type": next_step.get('action'), **({k: v for k, v in next_step.items() if k not in {'action'}})}
                elif 'step' in next_step:
                    nm = next_step.get('step')
                    # Resolve to a workbook task definition by name when available (independent of edge type)
                    tname = next_step.get('task') or next_step.get('name') or nm
                    base_task = locals().get('tasks_def_map', {}).get(str(tname), {})
                    if not isinstance(base_task, dict) or not base_task:
                        try:
                            _tlist = (locals().get('pb') or {}).get('workbook') or (locals().get('pb') or {}).get('tasks') or []
                            for _t in _tlist:
                                if isinstance(_t, dict) and ( _t.get('name') == tname or _t.get('task') == tname ):
                                    base_task = _t
                                    break
                        except Exception:
                            pass
                    if isinstance(base_task, dict) and base_task:
                        body_task_cfg = dict(base_task)
                        sw = next_step.get('with', {}) if isinstance(next_step.get('with'), dict) else {}
                        bw = base_task.get('with', {}) if isinstance(base_task.get('with'), dict) else {}
                        mw = {**bw, **sw}
                        if mw:
                            body_task_cfg['with'] = mw
                    else:
                        body_task_cfg = {'type': 'python', 'name': nm, 'code': 'def main(**kwargs):\n    return {}'}
                else:
                    body_task_cfg = next_step
            scheduled_any = False
            for idx_it, item in enumerate(items):
                if not _passes(item):
                    continue
                iter_node_id = f"{execution_id}-step-{idx+1}-iter-{idx_it}"
                try:
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("SELECT 1 FROM noetl.queue WHERE execution_id=%s AND node_id=%s LIMIT 1", (execution_id, iter_node_id))
                            if await cur.fetchone():
                                continue
                except Exception:
                    pass
                iter_work = dict(workload) if isinstance(workload, dict) else {}
                iter_work[iterator] = item
                try:
                    rendered_work = render_template(jenv, iter_work, base_ctx, strict_keys=False)
                except Exception:
                    rendered_work = iter_work
                try:
                    if isinstance(rendered_work, dict):
                        rendered_work['_loop'] = {
                            'loop_id': f"{execution_id}:{next_step.get('step') or next_step.get('name')}",
                            'loop_name': next_step.get('step') or next_step.get('name'),
                            'iterator': iterator,
                            'current_index': idx_it,
                            'current_item': item,
                            'items_count': len(items)
                        }
                except Exception:
                    pass
                try:
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                """
                                INSERT INTO noetl.queue (execution_id, node_id, action, input_context, priority, max_attempts, available_at)
                                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
                                RETURNING id
                                """,
                                (execution_id, iter_node_id, json.dumps(body_task_cfg), json.dumps(rendered_work), 0, 5, None)
                            )
                            await conn.commit()
                    scheduled_any = True
                except Exception:
                    logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to enqueue loop iteration", exc_info=True)
            if scheduled_any:
                try:
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                """
                                INSERT INTO noetl.transition (execution_id, from_step, to_step, condition, with_params)
                                VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT DO NOTHING
                                """,
                                (execution_id, last_step_name, body_step_name or (next_step.get('step') if isinstance(next_step, dict) else None), 'evaluated:direct', None)
                            )
                            await conn.commit()
                except Exception:
                    pass
                return

        if isinstance(next_step, dict) and 'loop' in next_step:
            try:
                await get_event_service().emit({
                    'execution_id': execution_id,
                    'event_type': 'action_completed',
                    'status': 'COMPLETED',
                    'node_id': f'{execution_id}-step-{idx+1}',
                    'node_name': next_step.get('step') or next_step.get('name') or f'step-{idx+1}',
                    'node_type': 'task',
                    'result': {'skipped': True, 'reason': 'empty_loop'},
                    'context': {'workload': workload}
                })
            except Exception:
                logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to emit empty_loop completion", exc_info=True)
            return

        if isinstance(next_step, dict):
            if 'call' in next_step:
                task_cfg = next_step['call']
            elif 'action' in next_step:
                task_cfg = {"type": next_step.get('action'), **({k: v for k, v in next_step.items() if k not in {'action'}})}
            elif 'step' in next_step:
                step_name = next_step.get('step')
                if step_name in {'start', 'end'}:
                    task_cfg = {'type': 'python', 'name': step_name, 'code': 'def main(**kwargs):\n    return {}'}
                else:
                    tname = next_step.get('task') or next_step.get('name') or step_name
                    base_task = locals().get('tasks_def_map', {}).get(str(tname), {})
                    if not isinstance(base_task, dict) or not base_task:
                        # Attempt to recover by rebuilding the task map from the parsed playbook
                        try:
                            _tlist = (locals().get('pb') or {}).get('workbook') or (locals().get('pb') or {}).get('tasks') or []
                            for _t in _tlist:
                                if isinstance(_t, dict) and ( _t.get('name') == tname or _t.get('task') == tname ):
                                    base_task = _t
                                    break
                        except Exception:
                            pass
                    if not isinstance(base_task, dict) or not base_task:
                        task_cfg = {'type': 'python', 'name': tname or step_name, 'code': 'def main(**kwargs):\n    return {}'}
                    else:
                        step_with = next_step.get('with', {}) if isinstance(next_step.get('with'), dict) else {}
                        merged_with = {}
                        if isinstance(base_task.get('with'), dict):
                            merged_with.update(base_task.get('with'))
                        if isinstance(step_with, dict):
                            merged_with.update(step_with)
                        task_cfg = dict(base_task)
                        task_cfg['name'] = tname or step_name
                        if merged_with:
                            try:
                                mw = dict(merged_with)
                                city_val = mw.get('city')
                                if city_val is not None and not isinstance(city_val, (dict, list)):
                                    if isinstance(city_val, str):
                                        s = city_val.strip()
                                        if s.startswith('{') and s.endswith('}'):
                                            try:
                                                import json as _json, ast as _ast
                                                try:
                                                    mw['city'] = _json.loads(s)
                                                except Exception:
                                                    mw['city'] = _ast.literal_eval(s)
                                            except Exception:
                                                pass
                                        if not isinstance(mw.get('city'), dict):
                                            w_cities = workload.get('cities') if isinstance(workload, dict) else None
                                            if isinstance(w_cities, list) and w_cities:
                                                first_city = w_cities[0]
                                                if isinstance(first_city, dict):
                                                    mw['city'] = first_city
                                # District safety: if unresolved or empty string, synthesize
                                if isinstance(mw.get('district'), str) and not mw.get('district').strip():
                                    mw['district'] = {"name": "Unknown"}
                                merged_with = mw
                            except Exception:
                                pass
                            task_cfg['with'] = merged_with
            else:
                task_cfg = next_step
        else:
            return

        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Task config prepared: {task_cfg}")

        try:
            try:
                from uuid import uuid4
                pre_ctx = dict(base_ctx)
                pre_ctx['env'] = dict(os.environ)
                pre_ctx['job'] = {'uuid': str(uuid4())}
                rendered_workload = render_template(jenv, workload, pre_ctx, strict_keys=False)
            except Exception:
                rendered_workload = workload
            node_id = f"{execution_id}-step-{idx+1}"
            step_name_guard = None
            if isinstance(next_step, dict):
                step_name_guard = next_step.get('step') or next_step.get('name') or next_step.get('task')
            try:
                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "SELECT 1 FROM noetl.queue WHERE execution_id = %s AND node_id = %s AND status IN ('queued','leased') LIMIT 1",
                            (execution_id, node_id)
                        )
                        q_row = await cur.fetchone()
                        if q_row:
                            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Job already queued for {node_id}; skipping")
                            return
                        if step_name_guard:
                            await cur.execute(
                                """
                                SELECT 1 FROM noetl.event_log 
                                WHERE execution_id = %s AND node_name = %s AND lower(status) IN ('completed','success')
                                LIMIT 1
                                """,
                                (execution_id, step_name_guard)
                            )
                            done = await cur.fetchone()
                            if done:
                                logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Step {step_name_guard} already completed; skipping enqueue")
                                return
            except Exception:
                logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Guard check failed; proceeding", exc_info=True)
            if 'transition_vars' in locals() and transition_vars:
                try:
                    rendered_vars = render_template(jenv, transition_vars, base_ctx, strict_keys=False)
                    if isinstance(rendered_vars, dict) and isinstance(rendered_workload, dict):
                        rendered_workload = {**rendered_workload, **rendered_vars}
                except Exception:
                    pass

            retries = 3
            delay = 0.1
            for attempt in range(1, retries + 1):
                try:
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
                                    node_id,
                                    json.dumps(task_cfg),
                                    json.dumps(rendered_workload),
                                    0,
                                    5,
                                    None,
                                )
                            )
                            row = await cur.fetchone()
                            try:
                                if locals().get('last_step_name') and (locals().get('chosen_target_name') or step_name_guard):
                                    to_name = (locals().get('chosen_target_name') or step_name_guard)
                                    cond_val = 'evaluated:' + (locals().get('transition_cond_text') or 'direct')
                                    await cur.execute(
                                        """
                                        INSERT INTO noetl.transition (execution_id, from_step, to_step, condition, with_params)
                                        VALUES (%s, %s, %s, %s, %s)
                                        ON CONFLICT DO NOTHING
                                        """,
                                        (
                                            execution_id,
                                            locals().get('last_step_name'),
                                            to_name,
                                            cond_val,
                                            json.dumps(locals().get('transition_vars')) if locals().get('transition_vars') is not None else None
                                        )
                                    )
                            except Exception:
                                pass
                            await conn.commit()
                    break
                except Exception as e:
                    if 'deadlock detected' in str(e).lower() and attempt < retries:
                        try:
                            import asyncio as _a
                            await _a.sleep(delay)
                        except Exception:
                            pass
                        delay *= 2
                        continue
                    else:
                        raise
            logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Enqueued job {row[0] if row else 'unknown'} for step {idx+1}")
        except Exception as e:
            logger.error(f"EVALUATE_BROKER_FOR_EXECUTION: Error enqueuing job: {e}")
            import traceback as _tb
            logger.error(_tb.format_exc())
        return
    except Exception:
        logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Unhandled exception", exc_info=True)
        return
