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
    convert_snowflake_ids_for_api,
    snowflake_id_to_int,
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


@router.post("/broker/evaluate/{execution_id}")
async def trigger_broker_evaluation(execution_id: str):
    """Manually trigger broker evaluation for an execution, including loop completion checks."""
    try:
        await evaluate_broker_for_execution(execution_id)
        return {"status": "success", "message": f"Broker evaluation triggered for execution {execution_id}"}
    except Exception as e:
        logger.error(f"Failed to trigger broker evaluation for {execution_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger broker evaluation: {str(e)}")

@router.post("/loop/complete/{execution_id}")
async def trigger_loop_completion(execution_id: str):
    """Manually trigger loop completion check for an execution."""
    try:
        await check_and_process_completed_loops(execution_id)
        return {"status": "success", "message": f"Loop completion check triggered for execution {execution_id}"}
    except Exception as e:
        logger.error(f"Failed to trigger loop completion for {execution_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger loop completion: {str(e)}")


def encode_task_for_queue(task_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply base64 encoding to multiline code/commands in task configuration
    to prevent serialization issues when passing through JSON in queue table.
    Only base64 versions are stored - original fields are removed to ensure single method of handling.
    
    Args:
        task_config: The original task configuration
        
    Returns:
        Modified task configuration with base64 encoded fields, original fields removed
    """
    if not isinstance(task_config, dict):
        return task_config
    
    import base64
    encoded_task = dict(task_config)
    
    try:
        # Encode Python code and remove original
        code_val = encoded_task.get('code')
        if isinstance(code_val, str) and code_val.strip():
            encoded_task['code_b64'] = base64.b64encode(code_val.encode('utf-8')).decode('ascii')
            # Remove original to ensure only base64 is used
            encoded_task.pop('code', None)
            
        # Encode command/commands for PostgreSQL and DuckDB and remove originals
        for field in ('command', 'commands'):
            cmd_val = encoded_task.get(field)
            if isinstance(cmd_val, str) and cmd_val.strip():
                encoded_task[f'{field}_b64'] = base64.b64encode(cmd_val.encode('utf-8')).decode('ascii')
                # Remove original to ensure only base64 is used
                encoded_task.pop(field, None)
                
    except Exception:
        logger.debug("ENCODE_TASK_FOR_QUEUE: Failed to encode task fields with base64", exc_info=True)
        
    return encoded_task

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
                        workload = ctx_first.get("workload", {}) if isinstance(ctx_first, dict) else {}
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

        # Fetch playbook to get step aliases
        playbook_path = None
        playbook_version = None
        steps = []
        # The event_log table doesn't have playbook_path/version columns; derive from
        # the earliest event's input_context/metadata like evaluate_broker_for_execution
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
                    playbook_path = (input_context.get('path') or
                                     (metadata.get('playbook_path') if isinstance(metadata, dict) else None) or
                                     (metadata.get('resource_path') if isinstance(metadata, dict) else None))
                    playbook_version = (input_context.get('version') or
                                        (metadata.get('resource_version') if isinstance(metadata, dict) else None))

        if playbook_path:
            try:
                catalog = get_catalog_service()
                entry = await catalog.fetch_entry(playbook_path, playbook_version or '')
                if entry:
                    import yaml
                    pb = yaml.safe_load(entry.get('content') or '') or {}
                    workflow = pb.get('workflow', [])
                    steps = pb.get('steps') or pb.get('tasks') or workflow
            except Exception:
                pass

        base_ctx: Dict[str, Any] = {"work": workload, "workload": workload, "results": results}
        # Allow direct references to prior step names (e.g., {{ evaluate_weather_directly.* }})
        try:
            if isinstance(results, dict):
                base_ctx.update(results)
                # Flatten common result wrappers to expose fields directly (e.g., evaluate_weather_directly.max_temp)
                for _k, _v in list(results.items()):
                    try:
                        if isinstance(_v, dict) and 'data' in _v:
                            base_ctx[_k] = _v.get('data')
                    except Exception:
                        pass
        except Exception:
            pass
        # Alias workbook task results under their workflow step names (e.g., aggregate_alerts -> aggregate_alerts_task)
        try:
            if isinstance(steps, list):
                for st in steps:
                    if isinstance(st, dict) and (st.get('type') or '').lower() == 'workbook':
                        step_nm = st.get('step') or st.get('name') or st.get('task')
                        task_nm = st.get('task') or st.get('name') or step_nm
                        if step_nm and task_nm and isinstance(results, dict) and task_nm in results and step_nm not in base_ctx:
                            val = results[task_nm]
                            # Flatten common wrapper {'status':..,'data':...} to expose fields directly
                            if isinstance(val, dict) and 'data' in val:
                                base_ctx[step_nm] = val.get('data')
                            else:
                                base_ctx[step_nm] = val
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
                        try:
                            job_obj["uuid"] = get_snowflake_id_str()
                        except Exception:
                            try:
                                job_obj["uuid"] = str(get_snowflake_id())
                            except Exception:
                                from uuid import uuid4
                                job_obj["uuid"] = str(uuid4())
            except Exception:
                pass
        try:
            if "job" not in base_ctx:
                try:
                    base_ctx["job"] = {"uuid": get_snowflake_id_str()}
                except Exception:
                    try:
                        base_ctx["job"] = {"uuid": str(get_snowflake_id())}
                    except Exception:
                        from uuid import uuid4
                        base_ctx["job"] = {"uuid": str(uuid4())}
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
                    FROM noetl.event_log
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
                    SELECT output_result FROM noetl.event_log
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
                        FROM noetl.event_log
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

@router.post("/events", response_class=JSONResponse)
async def create_event(
    request: Request,
    background_tasks: BackgroundTasks
):
    try:
        body = await request.json()
        
        # Debug all incoming events
        if body.get('event_type') == 'execution_complete':
            logger.info(f"EVENT_DEBUG: Received execution_complete event: {body}")
        
        event_service = get_event_service()
        result = await event_service.emit(body)
        
        # Check if this is a child execution completion event
        if body.get('event_type') == 'execution_complete':
            try:
                meta = body.get('meta', {})
                parent_execution_id = meta.get('parent_execution_id')
                parent_step = meta.get('parent_step')
                exec_id = body.get('execution_id')
                
                if parent_execution_id and parent_step and exec_id and parent_execution_id != exec_id:
                    logger.info(f"COMPLETION_HANDLER: Child execution {exec_id} completed for parent {parent_execution_id} step {parent_step}")
                    
                    # Extract result from the event
                    child_result = body.get('result')
                    if not child_result:
                        # Try to get meaningful result from step results
                        from noetl.common import get_async_db_connection as get_db_conn
                        async with get_db_conn() as conn:
                            async with conn.cursor() as cur:
                                # Try to find meaningful results by step name priority
                                for step_name in ['evaluate_weather_step', 'evaluate_weather', 'alert_step', 'log_step']:
                                    await cur.execute(
                                        """
                                        SELECT output_result FROM noetl.event_log
                                        WHERE execution_id = %s
                                          AND node_name = %s
                                          AND event_type = 'action_completed'
                                          AND lower(status) IN ('completed','success')
                                          AND output_result IS NOT NULL
                                          AND output_result != '{}'
                                          AND NOT (output_result::text LIKE '%"skipped": true%')
                                          AND NOT (output_result::text LIKE '%"reason": "control_step"%')
                                        ORDER BY timestamp DESC
                                        LIMIT 1
                                        """,
                                        (exec_id, step_name)
                                    )
                                    result_row = await cur.fetchone()
                                    if result_row:
                                        result_data = result_row[0] if isinstance(result_row, tuple) else result_row.get('output_result')
                                        try:
                                            import json
                                            child_result = json.loads(result_data) if isinstance(result_data, str) else result_data
                                            # Extract data if wrapped
                                            if isinstance(child_result, dict) and 'data' in child_result:
                                                child_result = child_result['data']
                                            break
                                        except Exception:
                                            pass
                    
                    if child_result:
                        # Find the iteration node_id pattern by looking up the loop_iteration event for this child
                        from noetl.common import get_async_db_connection as get_db_conn
                        async with get_db_conn() as conn:
                            async with conn.cursor() as cur:
                                await cur.execute(
                                    """
                                    SELECT node_id FROM noetl.event_log
                                    WHERE execution_id = %s
                                      AND event_type = 'loop_iteration'
                                      AND node_name = %s
                                      AND input_context LIKE %s
                                    ORDER BY timestamp DESC
                                    LIMIT 1
                                    """,
                                    (parent_execution_id, parent_step, f'%"child_execution_id": "{exec_id}"%')
                                )
                                iter_row = await cur.fetchone()
                                iter_node_id = None
                                if iter_row:
                                    iter_node_id = iter_row[0] if isinstance(iter_row, tuple) else iter_row.get('node_id')
                                
                                # Emit action_completed event for the parent loop to aggregate
                                await event_service.emit({
                                    'execution_id': parent_execution_id,
                                    'event_type': 'action_completed',
                                    'status': 'COMPLETED',
                                    'node_id': iter_node_id or f'{parent_execution_id}-step-X-iter-{exec_id}',
                                    'node_name': parent_step,
                                    'node_type': 'task',
                                    'output_result': child_result,
                                    'context': {
                                        'child_execution_id': exec_id,
                                        'parent_step': parent_step,
                                        'return_step': None
                                    }
                                })
                                logger.info(f"COMPLETION_HANDLER: Emitted action_completed for parent {parent_execution_id} step {parent_step} from child {exec_id} with result: {child_result}")
            except Exception:
                logger.debug("Failed to handle execution_complete event", exc_info=True)
        
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
        # Convert execution_id from string to int for database queries
        execution_id_int = snowflake_id_to_int(execution_id)
        
        event_service = get_event_service()
        events = await event_service.get_events_by_execution_id(execution_id_int)
        if not events:
            raise HTTPException(
                status_code=404,
                detail=f"No events found for execution '{execution_id}'."
            )
        # Convert snowflake IDs to strings for API compatibility
        events = convert_snowflake_ids_for_api(events)
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
        # Convert snowflake IDs to strings for API compatibility
        executions = convert_snowflake_ids_for_api(executions)
        return executions
    except Exception as e:
        logger.error(f"Error getting executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/executions/{execution_id}", response_class=JSONResponse)
async def get_execution(execution_id: str):
    try:
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

        # Convert snowflake IDs to strings for API compatibility
        execution_data = convert_snowflake_ids_for_api(execution_data)

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
            # Generate event_id using snowflake when not provided
            try:
                snow = get_snowflake_id_str()
            except Exception:
                try:
                    snow = str(get_snowflake_id())
                except Exception:
                    snow = None
            event_id = event_data.get("event_id", snow or f"evt_{os.urandom(16).hex()}")
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
                      # Default parent_event_id if missing: link to previous event in the same execution
                      if not parent_event_id:
                          try:
                              await cursor.execute("SELECT event_id FROM event_log WHERE execution_id = %s ORDER BY timestamp DESC LIMIT 1", (execution_id,))
                              _prev = await cursor.fetchone()
                              if _prev and _prev[0]:
                                  parent_event_id = _prev[0]
                          except Exception:
                              pass
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
                      
                      # Extract parent_execution_id from metadata or event_data
                      parent_execution_id = None
                      if metadata and isinstance(metadata, dict):
                          parent_execution_id = metadata.get('parent_execution_id')
                      if not parent_execution_id:
                          parent_execution_id = event_data.get('parent_execution_id')
                      if not parent_execution_id and metadata and isinstance(metadata, dict):
                          # Convert string to int if needed for bigint
                          parent_exec_str = metadata.get('parent_execution_id')
                          if parent_exec_str:
                              try:
                                  parent_execution_id = int(parent_exec_str)
                              except (ValueError, TypeError):
                                  pass

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
                                  execution_id, event_id, parent_event_id, parent_execution_id, timestamp, event_type,
                                  node_id, node_name, node_type, status, duration,
                                  input_context, output_result, metadata, error, trace_component,
                                  loop_id, loop_name, iterator, current_index, current_item
                              ) VALUES (
                                  %s, %s, %s, %s, CURRENT_TIMESTAMP, %s,
                                  %s, %s, %s, %s, %s,
                                  %s, %s, %s, %s,
                                  %s,
                                  %s, %s, %s, %s, %s
                              )
                          """, (
                              execution_id,
                              event_id,
                              parent_event_id,
                              parent_execution_id,
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
                # Re-evaluate broker on key lifecycle events, including task completion/errors
                if evt_l in {"execution_start", "action_completed", "action_error", "task_complete", "task_error", "loop_iteration"}:
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
        # Guard to prevent re-enqueuing post-loop steps per-item immediately
        # after an end_loop aggregation. Without this, steps following a loop
        # can be incorrectly treated as loop bodies, preventing final steps
        # (like logging and DB writes) from running.
        just_aggregated_end_loop: bool = False
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

        # PROACTIVE COMPLETION HANDLER: Check for completed child executions and process their results
        await check_and_process_completed_child_executions(execution_id)
        
        # LOOP COMPLETION HANDLER: Check for completed loops and emit end_loop events
        await check_and_process_completed_loops(execution_id)

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
                # Flatten common wrappers (id/status/data) to expose fields directly
                for _k, _v in list(results_ctx.items()):
                    try:
                        if isinstance(_v, dict) and 'data' in _v:
                            base_ctx[_k] = _v.get('data')
                    except Exception:
                        pass
                # Promote keys from control-step results (e.g., end_loop aggregations like alerts)
                try:
                    for _k, _v in list(results_ctx.items()):
                        if isinstance(_v, dict):
                            for _ck, _cv in _v.items():
                                if _ck not in base_ctx:
                                    base_ctx[_ck] = _cv
                except Exception:
                    pass
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
                            val = results_ctx[task_nm]
                            if isinstance(val, dict) and 'data' in val:
                                base_ctx[step_nm] = val.get('data')
                            else:
                                base_ctx[step_nm] = val
        except Exception:
            pass

        step_index: Dict[str, int] = {}
        for i, st in enumerate(steps):
            if isinstance(st, dict):
                # Index by all identifiers to resolve last_step_name reliably
                for key_name in ('step', 'name', 'task'):
                    val = st.get(key_name)
                    if val:
                        step_index[str(val)] = i

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
            
            # Check if this is a child execution that should emit execution_complete
            try:
                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "SELECT parent_execution_id FROM noetl.event_log WHERE execution_id = %s AND parent_execution_id IS NOT NULL LIMIT 1",
                            (execution_id,)
                        )
                        parent_row = await cur.fetchone()
                        
                        if parent_row and parent_row[0]:
                            # This is a child execution - check if we already emitted execution_complete
                            await cur.execute(
                                "SELECT 1 FROM noetl.event_log WHERE execution_id = %s AND event_type = 'execution_complete' LIMIT 1",
                                (execution_id,)
                            )
                            completion_exists = await cur.fetchone()
                            
                            if not completion_exists:
                                # Find the final return value from the last completed step with a return statement
                                final_result = None
                                try:
                                    # Look for the end step with return statement and process its return template
                                    for step in reversed(steps):
                                        if isinstance(step, dict) and 'return' in step:
                                            step_name = step.get('step') or step.get('task') or step.get('name')
                                            return_template = step.get('return')
                                            
                                            if step_name and return_template:
                                                # Build context for return template evaluation
                                                try:
                                                    from jinja2 import Environment, StrictUndefined, BaseLoader
                                                    from noetl.render import render_template
                                                    jenv = Environment(loader=BaseLoader(), undefined=StrictUndefined)
                                                    
                                                    # Build context with all completed step results
                                                    return_ctx = {"work": workload, "workload": workload, "results": results_ctx}
                                                    return_ctx.update(results_ctx)
                                                    
                                                    # Evaluate the return template
                                                    final_result = render_template(jenv, return_template, return_ctx, rules=None, strict_keys=False)
                                                    logger.info(f"CHILD_EXECUTION_COMPLETE: Evaluated return template '{return_template}' to: {final_result}")
                                                    break
                                                except Exception as e:
                                                    logger.debug(f"Failed to evaluate return template: {e}", exc_info=True)
                                                    # Fallback: try to get the direct result from the referenced step
                                                    if isinstance(return_template, str) and return_template.startswith('{{') and return_template.endswith('}}'):
                                                        # Extract step name from template like "{{ evaluate_weather_step }}"
                                                        step_ref = return_template.strip('{}').strip()
                                                        if step_ref in results_ctx:
                                                            final_result = results_ctx[step_ref]
                                                            break
                                except Exception:
                                    pass
                                
                                # Emit execution_complete event
                                event_service = get_event_service()
                                completion_event = {
                                    "execution_id": execution_id,
                                    "event_type": "execution_complete",
                                    "status": "completed",
                                    "node_name": playbook_path or "unknown",
                                    "node_type": "playbook",
                                    "result": final_result or {},
                                    "context": {"execution_id": execution_id},
                                    "meta": {"parent_execution_id": parent_row[0]}
                                }
                                
                                logger.info(f"CHILD_EXECUTION_COMPLETE: Emitting execution_complete for child {execution_id} with result: {final_result}")
                                await event_service.emit(completion_event)
            except Exception as e:
                logger.debug(f"Error handling child execution completion: {e}", exc_info=True)
            
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

        # Inline loop handler: if a step has a 'loop' attribute and also defines an action
        # (python/http/duckdb/postgres/secrets/workbook or a named task), schedule that action
        # for each item in parallel. When all items complete, emit a completion for the step
        # with an aggregated result and proceed using this step's 'next' transitions.
        if isinstance(next_step, dict) and ('loop' in next_step) and ((next_step.get('type') or '').lower() != 'loop'):
            try:
                step_nm = next_step.get('step') or next_step.get('name') or next_step.get('task') or f'step-{idx+1}'
                # Build loop spec from attribute
                lspec = next_step.get('loop') or {}
                iterator = (lspec.get('iterator') or 'item').strip()
                try:
                    items = render_template(jenv, lspec.get('in', []), base_ctx, strict_keys=False)
                    if isinstance(items, str):
                        try:
                            # Try JSON first (for proper JSON strings)
                            items = json.loads(items)
                        except Exception:
                            try:
                                # Fallback to ast.literal_eval for Python-like strings  
                                import ast
                                items = ast.literal_eval(items)
                            except Exception:
                                items = [items]
                except Exception:
                    items = []
                if not isinstance(items, list):
                    items = []
                fexpr = lspec.get('filter')
                def _accept(it):
                    if not fexpr:
                        return True
                    try:
                        fctx = dict(base_ctx)
                        fctx[iterator] = it
                        val = render_template(jenv, fexpr, fctx, strict_keys=False)
                        if val is None:
                            return True
                        if isinstance(val, str) and val.strip() == '':
                            return True
                        return bool(val)
                    except Exception:
                        return True
                items_f = [it for it in items if _accept(it)]

                # Check if the step already has a completion event (exclude iteration events with iter- in node_id)
                try:
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                "SELECT 1 FROM noetl.event_log WHERE execution_id=%s AND node_name=%s AND lower(status) IN ('completed','success') AND node_id NOT LIKE %s LIMIT 1",
                                (execution_id, step_nm, f"{execution_id}-step-%-iter-%")
                            )
                            done_evt = await cur.fetchone()
                except Exception:
                    done_evt = None

                # Count completed per-item events for this step's action
                done_count = 0
                try:
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            if str(locals().get('step_type_lower','')) == 'playbook':
                                # Count completed loop item mapping events for playbook loops
                                await cur.execute(
                                    """
                                    SELECT COUNT(*) FROM noetl.event_log
                                    WHERE execution_id = %s
                                      AND node_name = %s
                                      AND event_type = 'loop_item_completed'
                                      AND lower(status) IN ('completed','success')
                                    """,
                                    (execution_id, step_nm)
                                )
                            else:
                                await cur.execute(
                                    "SELECT COUNT(*) FROM noetl.event_log WHERE execution_id=%s AND node_name=%s AND lower(status) IN ('completed','success')",
                                    (execution_id, step_nm)
                                )
                            r = await cur.fetchone()
                            done_count = (r[0] or 0) if r else 0
                except Exception:
                    pass

                expected = len(items_f)
                
                # Define step_type_lower before aggregation logic
                step_type_lower = str(next_step.get('type') or '').strip().lower()

                logger.debug(f"INLINE LOOP CHECK: step={step_nm}, expected={expected}, done_count={done_count}, done_evt={done_evt}, step_type={step_type_lower}")
                logger.debug(f"INLINE LOOP AGGREGATION CONDITIONS: expected > 0? {expected > 0}, done_count >= expected? {done_count >= expected}, not done_evt? {not done_evt}")

                # Check for completed loop iterations (action_completed events with iter- in node_id)
                iter_complete_count = 0
                try:
                    async with get_async_db_connection() as conn:
                        async with conn.cursor(row_factory=dict_row) as cur:
                            await cur.execute(
                                """
                                SELECT COUNT(*) as iter_count FROM noetl.event_log
                                WHERE execution_id = %s
                                  AND node_name = %s
                                  AND event_type = 'action_completed'
                                  AND node_id LIKE %s
                                  AND lower(status) IN ('completed','success')
                                """,
                                (execution_id, step_nm, f"{execution_id}-step-%-iter-%")
                            )
                            result = await cur.fetchone()
                            iter_complete_count = result['iter_count'] if result else 0
                except Exception:
                    pass

                logger.debug(f"INLINE LOOP CHECK: step={step_nm}, expected={expected}, done_count={done_count}, iter_complete_count={iter_complete_count}, done_evt={done_evt}, step_type={step_type_lower}")

                # If all items completed and no aggregate completion emitted, emit aggregate completion
                if expected > 0 and iter_complete_count >= expected and not done_evt:
                    logger.debug(f"INLINE LOOP AGGREGATION: Starting aggregation for {step_nm}, expected={expected}, done_count={done_count}, done_evt={done_evt}")
                    # Build aggregated result as list of outputs for this node
                    agg_list = []
                    try:
                        async with get_async_db_connection() as conn:
                            async with conn.cursor(row_factory=dict_row) as cur:
                                if step_type_lower == 'playbook':
                                    # For playbook type loops, get results from action_completed iteration events
                                    await cur.execute(
                                        """
                                        SELECT output_result FROM noetl.event_log
                                        WHERE execution_id = %s
                                          AND node_name = %s
                                          AND event_type = 'action_completed'
                                          AND node_id LIKE %s
                                          AND lower(status) IN ('completed','success')
                                        ORDER BY timestamp
                                        """,
                                        (execution_id, step_nm, f"{execution_id}-step-%-iter-%")
                                    )
                                    rows = await cur.fetchall()
                                    for rr in rows:
                                        output_result = rr.get('output_result')
                                        try:
                                            # Parse the output_result which contains the execution info
                                            if isinstance(output_result, str):
                                                output_data = json.loads(output_result)
                                            else:
                                                output_data = output_result
                                            
                                            # Extract the actual result data from the child execution
                                            if isinstance(output_data, dict) and 'data' in output_data:
                                                result_data = output_data['data']
                                                # If it contains execution_id, we need to fetch the actual result
                                                if isinstance(result_data, dict) and 'execution_id' in result_data:
                                                    child_exec_id = result_data['execution_id']
                                                    # TODO: Fetch the actual result from the child execution
                                                    # For now, just use the status info
                                                    agg_list.append(result_data)
                                                else:
                                                    agg_list.append(result_data)
                                            else:
                                                agg_list.append(output_data)
                                        except Exception:
                                            # If parsing fails, just include the raw output
                                            if output_result is not None:
                                                agg_list.append(output_result)
                                else:
                                    # For non-playbook loops, use the original logic
                                    await cur.execute(
                                        """
                                        SELECT output_result FROM noetl.event_log
                                        WHERE execution_id=%s AND node_name=%s AND lower(status) IN ('completed','success')
                                        ORDER BY timestamp
                                        """,
                                        (execution_id, step_nm)
                                    )
                                    rows = await cur.fetchall()
                                    for rr in rows:
                                        data = rr.get('output_result')
                                        try:
                                            data = json.loads(data) if isinstance(data, str) else data
                                            # Extract the actual data if it's wrapped
                                            if isinstance(data, dict) and 'data' in data:
                                                data = data['data']
                                        except Exception:
                                            pass
                                        # Skip null/empty results but include all actual data
                                        if data is not None:
                                            agg_list.append(data)
                    except Exception:
                        pass
                    try:
                        await get_event_service().emit({
                            'execution_id': execution_id,
                            'event_type': 'action_completed',
                            'status': 'COMPLETED',
                            'node_id': f'{execution_id}-step-{idx+1}',
                            'node_name': step_nm,
                            'node_type': 'task',
                            'result': {'results': agg_list, 'count': len(agg_list)},
                            'context': {'workload': workload},
                        })
                    except Exception:
                        logger.debug("INLINE LOOP: Failed to emit aggregate completion", exc_info=True)
                    return

                # Schedule per-item jobs if not already scheduled (or partially scheduled)
                scheduled_any = False
                # Build task config from the step itself
                # Adapted from general task_cfg builder below
                if step_type_lower == 'playbook':
                    # Proxy sub-playbook call via python on worker, waiting for completion
                    sub_path = next_step.get('path') or ''
                    return_step = next_step.get('return', 'fetch_and_evaluate')  # Use return attribute or default
                    task_code = (
                        "def main(playbook_id, parameters, parent_execution_id=None, parent_event_id=None, parent_step=None, return_step='fetch_and_evaluate'):\n"
                        "    import os, httpx, time\n"
                        "    host = os.environ.get('NOETL_HOST','localhost')\n"
                        "    port = os.environ.get('NOETL_PORT','8082')\n"
                        "    base = f'http://{host}:{port}/api'\n"
                        "    try:\n"
                        "        # Normalize parameters\n"
                        "        params = parameters.get('parameters', parameters) if isinstance(parameters, dict) else parameters\n"
                        "        payload = {'playbook_id': playbook_id, 'parameters': params, 'merge': True}\n"
                        "        # Parent linkage if provided (explicit args take precedence)\n"
                        "        peid = parent_execution_id or (params.get('parent_execution_id') if isinstance(params, dict) else None)\n"
                        "        pveid = parent_event_id or (params.get('parent_event_id') if isinstance(params, dict) else None)\n"
                        "        if peid: payload['parent_execution_id'] = peid\n"
                        "        if pveid: payload['parent_event_id'] = pveid\n"
                        "        if parent_step: payload['parent_step'] = parent_step\n"
                        "        r = httpx.post(f'{base}/executions/run', json=payload, timeout=30.0)\n"
                        "        r.raise_for_status()\n"
                        "        data = r.json(); eid = data.get('id') or data.get('execution_id')\n"
                        "        for _ in range(300):\n"
                        "            s = httpx.get(f'{base}/executions/{eid}', timeout=30.0)\n"
                        "            if s.status_code == 200:\n"
                        "                js = s.json(); st = str(js.get('status','')).lower()\n"
                        "                if st in ('completed','failed','error','canceled'):\n"
                        "                    ev = js.get('events', [])\n"
                        "                    # Look for the return step completion event\n"
                        "                    for e in ev:\n"
                        "                        if e.get('event_type')=='action_completed' and e.get('node_name')==return_step:\n"
                        "                            output = e.get('output_result') or e.get('result')\n"
                        "                            if isinstance(output, dict) and 'data' in output:\n"
                        "                                return output['data']\n"
                        "                            return output\n"
                        "                    # If no return step found, return status\n"
                        "                    return {'status': st, 'execution_id': eid}\n"
                        "            time.sleep(0.2)\n"
                        "        return {'status': 'timeout', 'execution_id': eid}\n"
                        "    except Exception as e:\n"
                        "        return {'status': 'error', 'error': str(e)}\n"
                    )
                    
                    # Base64 encode the code to avoid serialization issues
                    import base64
                    encoded_code = base64.b64encode(task_code.encode('utf-8')).decode('ascii')
                    
                    # Render per-item parameters at worker from context; pass the step's with-template as a mapping
                    step_with_tpl = next_step.get('with', {}) if isinstance(next_step.get('with'), dict) else {}
                    task_cfg = {
                        'type': 'python',
                        'name': step_nm,
                        'code_b64': encoded_code,  # Use base64 encoded code instead of raw code
                        'with': {
                            'playbook_id': sub_path,
                            'parameters': step_with_tpl,
                            'parent_execution_id': '{{ _meta.parent_execution_id }}',
                            'parent_event_id': '{{ _meta.parent_event_id }}',
                            'parent_step': step_nm,
                            'return_step': return_step,
                        }
                    }
                elif 'call' in next_step:
                    task_cfg = next_step['call']
                elif 'action' in next_step:
                    task_cfg = {"type": next_step.get('action'), **({k: v for k, v in next_step.items() if k not in {'action','loop','next'}})}
                else:
                    # Resolve workbook task by its task/name
                    tname = next_step.get('task') or next_step.get('name') or step_nm
                    base_task = locals().get('tasks_def_map', {}).get(str(tname), {})
                    if not isinstance(base_task, dict) or not base_task:
                        task_cfg = {'type': (next_step.get('type') or 'python'), 'name': tname, 'code': 'def main(**kwargs):\n    return {}'}
                    else:
                        sw = next_step.get('with', {}) if isinstance(next_step.get('with'), dict) else {}
                        bw = base_task.get('with', {}) if isinstance(base_task.get('with'), dict) else {}
                        mw = {**bw, **sw}
                        task_cfg = dict(base_task)
                        task_cfg['name'] = step_nm
                        if mw:
                            task_cfg['with'] = mw

                # Use a stable step index for node_id to avoid generating
                # new node_ids across reevaluations that would re-enqueue endlessly.
                try:
                    sidx = step_index.get(step_nm, idx)
                except Exception:
                    sidx = idx
                for i, it in enumerate(items_f):
                    iter_node_id = f"{execution_id}-step-{sidx+1}-iter-{i}"
                    
                    # Check if this iteration was already scheduled (using node_id to identify the specific iteration)
                    try:
                        async with get_async_db_connection() as conn:
                            async with conn.cursor() as cur:
                                await cur.execute("SELECT 1 FROM noetl.queue WHERE node_id=%s LIMIT 1", (iter_node_id,))
                                if await cur.fetchone():
                                    continue
                    except Exception:
                        pass
                    
                    # Generate unique child execution ID for each loop iteration
                    try:
                        child_execution_id = get_snowflake_id_str()
                    except Exception:
                        try:
                            child_execution_id = str(get_snowflake_id())
                        except Exception:
                            from uuid import uuid4
                            child_execution_id = str(uuid4())
                    iter_ctx = dict(workload) if isinstance(workload, dict) else {}
                    iter_ctx[iterator] = it
                    try:
                        rendered_work = render_template(jenv, iter_ctx, base_ctx, strict_keys=False)
                    except Exception:
                        rendered_work = iter_ctx
                    # Emit a loop_iteration event to create a real parent_event_id for child executions
                    loop_iter_event_id = None
                    try:
                        evt = await get_event_service().emit({
                            'execution_id': execution_id,
                            'event_type': 'loop_iteration',
                            'status': 'in_progress',
                            'node_id': iter_node_id,
                            'node_name': step_nm,
                            'node_type': 'iteration',
                            'context': {'workload': rendered_work, 'iterator': iterator, 'index': i, 'child_execution_id': child_execution_id}
                        })
                        loop_iter_event_id = evt.get('event_id')
                    except Exception:
                        logger.debug("INLINE LOOP: Failed to emit loop_iteration event", exc_info=True)
                    try:
                        if isinstance(rendered_work, dict):
                            rendered_work['_loop'] = {
                                'loop_id': f"{execution_id}:{step_nm}",
                                'loop_name': step_nm,
                                'iterator': iterator,
                                'current_index': i,
                                'current_item': it,
                                'items_count': len(items_f)
                            }
                            rendered_work['_meta'] = {
                                'parent_event_id': loop_iter_event_id,
                                'parent_execution_id': execution_id,
                                'parent_step': step_nm
                            }
                    except Exception:
                        pass
                    try:
                        async with get_async_db_connection() as conn:
                            async with conn.cursor() as cur:
                                await cur.execute(
                                    """
                                    INSERT INTO noetl.queue (execution_id, node_id, action, input_context, priority, max_attempts, available_at)
                                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                                    RETURNING id
                                    """,
                                    (child_execution_id, iter_node_id, json.dumps(encode_task_for_queue(task_cfg)), json.dumps(rendered_work), 0, 5)
                                )
                                await conn.commit()
                        scheduled_any = True
                    except Exception:
                        logger.debug("INLINE LOOP: Failed to enqueue per-item job", exc_info=True)
                if scheduled_any:
                    return
            except Exception:
                logger.debug("INLINE LOOP: scheduling error", exc_info=True)
            # Always return after handling a step with loop attribute to prevent falling through to control step detection
            return

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
                                VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                                RETURNING id
                                """,
                                (execution_id, iter_node_id, json.dumps(encode_task_for_queue(body_task_cfg)), json.dumps(rendered_work), 0, 5)
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

            # Emit completion for end_loop step with aggregated result
            end_result = agg_result or {'results': loop_results}
            try:
                await get_event_service().emit({
                    'execution_id': execution_id,
                    'event_type': 'action_completed',
                    'status': 'COMPLETED',
                    'node_id': f'{execution_id}-step-{idx+1}',
                    'node_name': end_step_name,
                    'node_type': 'task',
                    'result': end_result,
                    'context': {'workload': workload},
                })
            except Exception:
                logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed to emit end_loop aggregation", exc_info=True)

            # Promote end_loop result into context for subsequent transitions
            try:
                if isinstance(results_ctx, dict):
                    results_ctx[end_step_name] = end_result
                # Also promote flattened keys (e.g., alerts) for convenience
                if isinstance(end_result, dict):
                    for _k, _v in end_result.items():
                        if _k not in base_ctx:
                            base_ctx[_k] = _v
                base_ctx[end_step_name] = end_result
            except Exception:
                pass

            # Determine next step from the end_loop step's own 'next' transitions
            chosen_after_end: Optional[str] = None
            transition_vars = None
            nxt_list = next_step.get('next') or []
            if isinstance(nxt_list, list):
                for case in nxt_list:
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
                                    chosen_after_end = tgt.get('step') or tgt.get('name') or tgt.get('task')
                                    transition_vars = tgt.get('with')
                                else:
                                    chosen_after_end = str(tgt)
                                break
                    elif 'else' in case:
                        targets = case.get('else')
                        if isinstance(targets, list) and targets:
                            tgt = targets[0]
                            if isinstance(tgt, dict):
                                chosen_after_end = tgt.get('step') or tgt.get('name') or tgt.get('task')
                                transition_vars = tgt.get('with')
                            else:
                                chosen_after_end = str(tgt)
                            break

            if chosen_after_end and chosen_after_end in step_index:
                # Advance scheduler to the chosen next step
                last_step_name = end_step_name
                idx = step_index[chosen_after_end]
                next_step = steps[idx]
                logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Continuing after end_loop to '{chosen_after_end}' (idx={idx})")
                just_aggregated_end_loop = True
            else:
                # No explicit next; proceed by falling back to default progression
                last_step_name = end_step_name
                idx = (idx + 1) if (idx is not None) else idx
                if idx is None or idx >= len(steps):
                    logger.info("EVALUATE_BROKER_FOR_EXECUTION: No further steps after end_loop")
                    return
                next_step = steps[idx]
                just_aggregated_end_loop = True

        if (not just_aggregated_end_loop) and last_step_name and isinstance(prev_cfg := steps[step_index[last_step_name]], dict) and 'loop' in prev_cfg:
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
                                VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                                RETURNING id
                                """,
                                (execution_id, iter_node_id, json.dumps(encode_task_for_queue(body_task_cfg)), json.dumps(rendered_work), 0, 5)
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
            # Only emit an empty_loop completion if the resolved items list is actually empty.
            # Previously this fired unconditionally causing loops with items to appear skipped.
            try:
                loop_cfg = next_step.get('loop') or {}
                items_key = loop_cfg.get('in') or loop_cfg.get('items')
                items_list = []
                if items_key and isinstance(workload, dict):
                    # Accept either direct list or dict key lookup
                    candidate = workload.get(items_key)
                    if isinstance(candidate, list):
                        items_list = candidate
                if not items_list:
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
                    return
                # If items exist, allow normal loop processing path to continue (no return here)
            except Exception:
                logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Failed loop empty check", exc_info=True)

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
                            task_cfg['with'] = merged_with
            else:
                task_cfg = next_step
        else:
            return

        logger.info(f"EVALUATE_BROKER_FOR_EXECUTION: Task config prepared: {task_cfg}")

        try:
            try:
                pre_ctx = dict(base_ctx)
                pre_ctx['env'] = dict(os.environ)
                try:
                    pre_ctx['job'] = {'uuid': get_snowflake_id_str()}
                except Exception:
                    try:
                        pre_ctx['job'] = {'uuid': str(get_snowflake_id())}
                    except Exception:
                        from uuid import uuid4
                        pre_ctx['job'] = {'uuid': str(uuid4())}
                rendered_workload = render_template(jenv, workload, pre_ctx, strict_keys=False)
            except Exception:
                rendered_workload = workload
            # Ensure _meta with parent linkage defaults
            try:
                if isinstance(rendered_workload, dict):
                    meta = rendered_workload.get('_meta') or {}
                    _ese = locals().get('exec_start_eid')
                    if _ese and 'parent_event_id' not in meta:
                        meta['parent_event_id'] = _ese
                    
                    # If this execution has parent metadata (indicating it's a child execution),
                    # pass that parent metadata through to the queue jobs it creates
                    if isinstance(metadata, dict):
                        parent_execution_id = metadata.get('parent_execution_id')
                        parent_step = metadata.get('parent_step')
                        if parent_execution_id and parent_step:
                            meta['parent_execution_id'] = parent_execution_id
                            meta['parent_step'] = parent_step
                        elif 'parent_execution_id' not in meta:
                            meta['parent_execution_id'] = execution_id
                    elif 'parent_execution_id' not in meta:
                        meta['parent_execution_id'] = execution_id
                    
                    rendered_workload['_meta'] = meta
            except Exception:
                pass
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
                                VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                                RETURNING id
                                """,
                                (
                                    execution_id,
                                    node_id,
                                    json.dumps(encode_task_for_queue(task_cfg)),
                                    json.dumps(rendered_workload),
                                    0,
                                    5
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
        logger.exception("EVALUATE_BROKER_FOR_EXECUTION: Unexpected error")


async def check_and_process_completed_child_executions(parent_execution_id: str):
    """
    Proactively check for completed child executions and process their results.
    This handles the case where child executions complete but don't send events to the server.
    """
    try:
        logger.info(f"PROACTIVE_COMPLETION_CHECK: Checking for completed child executions of parent {parent_execution_id}")
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Find all child executions spawned by this parent
                await cur.execute(
                    """
                    SELECT DISTINCT 
                        (input_context::json)->>'child_execution_id' as child_exec_id,
                        node_name as parent_step,
                        node_id as iter_node_id
                    FROM noetl.event_log 
                    WHERE execution_id = %s 
                      AND event_type = 'loop_iteration'
                      AND input_context::text LIKE '%%child_execution_id%%'
                    """,
                    (parent_execution_id,)
                )
                child_executions = await cur.fetchall()
                
                if not child_executions:
                    logger.debug(f"PROACTIVE_COMPLETION_CHECK: No child executions found for parent {parent_execution_id}")
                    return
                
                for child_exec_id, parent_step, iter_node_id in child_executions:
                    if not child_exec_id:
                        continue
                    
                    logger.info(f"PROACTIVE_COMPLETION_CHECK: Checking child execution {child_exec_id} for parent step {parent_step}")
                    
                    # Check if this child execution has completed
                    await cur.execute(
                        """
                        SELECT 1 FROM noetl.event_log 
                        WHERE execution_id = %s 
                          AND event_type = 'execution_start'
                        """,
                        (child_exec_id,)
                    )
                    child_exists = await cur.fetchone() is not None
                    
                    if not child_exists:
                        logger.debug(f"PROACTIVE_COMPLETION_CHECK: Child execution {child_exec_id} not found in event log yet")
                        continue
                    
                    # Check if we've already processed this child completion
                    await cur.execute(
                        """
                        SELECT 1 FROM noetl.event_log 
                        WHERE execution_id = %s 
                          AND event_type = 'action_completed'
                          AND node_name = %s
                          AND node_id LIKE %s
                        """,
                        (parent_execution_id, parent_step, f'%-iter-{child_exec_id}')
                    )
                    already_processed = await cur.fetchone() is not None
                    
                    if already_processed:
                        logger.debug(f"PROACTIVE_COMPLETION_CHECK: Child execution {child_exec_id} already processed")
                        continue
                    
                    # Check if child execution has meaningful results
                    child_result = None
                    for step_name in ['evaluate_weather_step', 'evaluate_weather', 'alert_step', 'log_step']:
                        await cur.execute(
                            """
                            SELECT output_result FROM noetl.event_log
                            WHERE execution_id = %s
                              AND node_name = %s
                              AND event_type = 'action_completed'
                              AND lower(status) IN ('completed','success')
                              AND output_result IS NOT NULL
                              AND output_result != '{}'
                              AND NOT (output_result::text LIKE '%"skipped": true%')
                              AND NOT (output_result::text LIKE '%"reason": "control_step"%')
                            ORDER BY timestamp DESC
                            LIMIT 1
                            """,
                            (child_exec_id, step_name)
                        )
                        result_row = await cur.fetchone()
                        if result_row:
                            result_data = result_row[0] if isinstance(result_row, tuple) else result_row.get('output_result')
                            try:
                                import json
                                child_result = json.loads(result_data) if isinstance(result_data, str) else result_data
                                # Extract data if wrapped
                                if isinstance(child_result, dict) and 'data' in child_result:
                                    child_result = child_result['data']
                                logger.info(f"PROACTIVE_COMPLETION_CHECK: Found meaningful result from step {step_name} in child {child_exec_id}: {child_result}")
                                break
                            except Exception as e:
                                logger.debug(f"PROACTIVE_COMPLETION_CHECK: Error parsing result from {step_name}: {e}")
                                continue

                    # Fallback: accept any non-empty action_completed result from the child
                    if child_result is None:
                        await cur.execute(
                            """
                            SELECT output_result FROM noetl.event_log
                            WHERE execution_id = %s
                              AND event_type = 'action_completed'
                              AND lower(status) IN ('completed','success')
                              AND output_result IS NOT NULL
                              AND output_result != '{}'
                              AND NOT (output_result::text LIKE '%"skipped": true%')
                              AND NOT (output_result::text LIKE '%"reason": "control_step"%')
                            ORDER BY timestamp DESC
                            LIMIT 1
                            """,
                            (child_exec_id,)
                        )
                        row_any = await cur.fetchone()
                        if row_any:
                            try:
                                import json
                                any_out = row_any[0] if isinstance(row_any, tuple) else row_any.get('output_result')
                                child_result = json.loads(any_out) if isinstance(any_out, str) else any_out
                                if isinstance(child_result, dict) and 'data' in child_result:
                                    child_result = child_result['data']
                                logger.info(f"PROACTIVE_COMPLETION_CHECK: Fallback accepted child {child_exec_id} result: {child_result}")
                            except Exception:
                                pass
                    
                    if child_result:
                        # Emit action_completed event for the parent loop to aggregate
                        try:
                            event_service = get_event_service()
                            await event_service.emit({
                                'execution_id': parent_execution_id,
                                'event_type': 'action_completed',
                                'status': 'COMPLETED',
                                'node_id': iter_node_id or f'{parent_execution_id}-step-X-iter-{child_exec_id}',
                                'node_name': parent_step,
                                'node_type': 'task',
                                'result': child_result,
                                'context': {
                                    'child_execution_id': child_exec_id,
                                    'parent_step': parent_step,
                                    'return_step': None
                                }
                            })
                            logger.info(f"PROACTIVE_COMPLETION_CHECK: Emitted action_completed for parent {parent_execution_id} step {parent_step} from child {child_exec_id} with result: {child_result}")
                        except Exception as e:
                            logger.error(f"PROACTIVE_COMPLETION_CHECK: Error emitting action_completed event: {e}")
                    else:
                        logger.debug(f"PROACTIVE_COMPLETION_CHECK: No meaningful result found for child execution {child_exec_id}")
                        
    except Exception as e:
        logger.error(f"PROACTIVE_COMPLETION_CHECK: Error checking completed child executions: {e}")


async def check_and_process_completed_loops(parent_execution_id: str):
    """
    Comprehensive loop completion handler that works for any action type:
    1. Creates end_loop events to track all child executions for each loop
    2. Detects when all children complete and aggregates their results
    3. Emits final loop result events with aggregated data
    """
    try:
        logger.info(f"LOOP_COMPLETION_CHECK: Processing loop completion for execution {parent_execution_id}")
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Step 1: Find all loops that need processing (loops without end_loop events OR with TRACKING end_loop events)
                await cur.execute(
                    """
                    SELECT DISTINCT 
                        node_name as loop_step_name,
                        COUNT(*) as total_iterations
                    FROM noetl.event_log 
                    WHERE execution_id = %s 
                      AND event_type = 'loop_iteration'
                      AND (
                          node_name NOT IN (
                              SELECT DISTINCT node_name 
                              FROM noetl.event_log 
                              WHERE execution_id = %s 
                                AND event_type = 'end_loop'
                          )
                          OR node_name IN (
                              SELECT DISTINCT node_name 
                              FROM noetl.event_log 
                              WHERE execution_id = %s 
                                AND event_type = 'end_loop' 
                                AND status = 'TRACKING'
                          )
                      )
                    GROUP BY node_name
                    """,
                    (parent_execution_id, parent_execution_id, parent_execution_id)
                )
                active_loops = await cur.fetchall()
                
                for loop_step_name, total_iterations in active_loops:
                    logger.info(f"LOOP_COMPLETION_CHECK: Processing loop {loop_step_name} with {total_iterations} iterations")
                    
                    # Initialize event service for this loop processing
                    event_service = get_event_service()
                    
                    # Get all child execution IDs for this loop from both loop_iteration and action_completed events
                    await cur.execute(
                        """
                        SELECT * FROM (
                            -- Get child executions from loop_iteration events
                            SELECT 
                                (input_context::json)->>'child_execution_id' as child_exec_id,
                                node_id as iter_node_id,
                                event_id as iter_event_id,
                                COALESCE((input_context::json)->>'index', '0') as iteration_index,
                                'loop_iteration' as source_event
                            FROM noetl.event_log 
                            WHERE execution_id = %s 
                              AND event_type = 'loop_iteration'
                              AND node_name = %s
                              AND input_context::text LIKE '%%child_execution_id%%'
                            
                            UNION ALL
                            
                            -- Get child executions from action_completed events (these contain the actual playbook results)
                            SELECT 
                                (input_context::json)->>'child_execution_id' as child_exec_id,
                                node_id as iter_node_id,
                                event_id as iter_event_id,
                                '0' as iteration_index,
                                'action_completed' as source_event
                            FROM noetl.event_log 
                            WHERE execution_id = %s 
                              AND event_type = 'action_completed'
                              AND node_name = %s
                              AND input_context::text LIKE '%%child_execution_id%%'
                        ) AS combined_results
                        ORDER BY source_event, CAST(iteration_index AS INTEGER)
                        """,
                        (parent_execution_id, loop_step_name, parent_execution_id, loop_step_name)
                    )
                    child_executions = await cur.fetchall()
                    
                    if not child_executions:
                        logger.debug(f"LOOP_COMPLETION_CHECK: No child executions found for loop {loop_step_name}")
                        continue
                    
                    # Step 2: Check if we need to create an end_loop tracking event
                    await cur.execute(
                        """
                        SELECT 1 FROM noetl.event_log 
                        WHERE execution_id = %s 
                          AND event_type = 'end_loop'
                          AND node_name = %s
                        """,
                        (parent_execution_id, loop_step_name)
                    )
                    end_loop_exists = await cur.fetchone() is not None
                    
                    if not end_loop_exists:
                        # Create end_loop tracking event - prioritize action_completed events as they contain real results
                        child_exec_data = []
                        seen_child_ids = set()
                        
                        for child_exec_id, iter_node_id, iter_event_id, iteration_index, source_event in child_executions:
                            if child_exec_id and child_exec_id not in seen_child_ids:
                                child_exec_data.append({
                                    'child_execution_id': child_exec_id,
                                    'iter_node_id': iter_node_id,
                                    'iter_event_id': iter_event_id,
                                    'iteration_index': int(iteration_index) if iteration_index else 0,
                                    'source_event': source_event,
                                    'completed': False
                                })
                                seen_child_ids.add(child_exec_id)
                        
                        await event_service.emit({
                            'execution_id': parent_execution_id,
                            'event_type': 'end_loop',
                            'node_name': loop_step_name,
                            'node_type': 'loop_tracker',
                            'status': 'TRACKING',
                            'context': {
                                'loop_step_name': loop_step_name,
                                'total_iterations': len(child_exec_data),
                                'child_executions': child_exec_data,
                                'completed_count': 0,
                                'aggregated_results': []
                            }
                        })
                        logger.info(f"LOOP_COMPLETION_CHECK: Created end_loop tracking event for {loop_step_name} with {len(child_exec_data)} children")
                        continue
                    
                    # Step 3: Check completion status and aggregate results
                    await cur.execute(
                        """
                        SELECT input_context FROM noetl.event_log 
                        WHERE execution_id = %s 
                          AND event_type = 'end_loop'
                          AND node_name = %s
                        ORDER BY timestamp DESC
                        LIMIT 1
                        """,
                        (parent_execution_id, loop_step_name)
                    )
                    end_loop_row = await cur.fetchone()
                    if not end_loop_row:
                        continue
                    
                    try:
                        import json
                        end_loop_context = json.loads(end_loop_row[0]) if isinstance(end_loop_row[0], str) else end_loop_row[0]
                        child_executions_data = end_loop_context.get('child_executions', [])
                        completed_count = end_loop_context.get('completed_count', 0)
                        aggregated_results = end_loop_context.get('aggregated_results', [])
                    except Exception:
                        logger.error(f"LOOP_COMPLETION_CHECK: Error parsing end_loop context for {loop_step_name}")
                        continue
                    
                    # Check each child execution for completion and meaningful results
                    updated_children = []
                    new_completed_count = 0
                    new_aggregated_results = list(aggregated_results)
                    
                    for child_data in child_executions_data:
                        child_exec_id = child_data.get('child_execution_id')
                        was_completed = child_data.get('completed', False)
                        
                        if was_completed:
                            new_completed_count += 1
                            updated_children.append(child_data)
                            continue
                        
                        if not child_exec_id:
                            updated_children.append(child_data)
                            continue
                        
                        # Check if this child execution has completed and get its return value
                        child_result = None
                        logger.info(f"LOOP_COMPLETION_CHECK: Checking child execution {child_exec_id} for completion")
                        
                        # First check for execution_complete event which should have the final return value
                        await cur.execute(
                            """
                            SELECT output_result FROM noetl.event_log
                            WHERE execution_id = %s
                              AND event_type = 'execution_complete'
                              AND lower(status) IN ('completed','success')
                              AND output_result IS NOT NULL
                              AND output_result != '{}'
                            ORDER BY timestamp DESC
                            LIMIT 1
                            """,
                            (child_exec_id,)
                        )
                        exec_complete_row = await cur.fetchone()
                        
                        if exec_complete_row:
                            result_data = exec_complete_row[0] if isinstance(exec_complete_row, tuple) else exec_complete_row.get('output_result')
                            try:
                                child_result = json.loads(result_data) if isinstance(result_data, str) else result_data
                                logger.info(f"LOOP_COMPLETION_CHECK: Found execution_complete result for child {child_exec_id}: {child_result}")
                            except Exception:
                                logger.debug(f"LOOP_COMPLETION_CHECK: Failed to parse execution_complete result for child {child_exec_id}")
                        else:
                            # Fallback: Look for any meaningful step result from any completed action
                            await cur.execute(
                                """
                                SELECT node_name, output_result FROM noetl.event_log
                                WHERE execution_id = %s
                                  AND event_type = 'action_completed'
                                  AND lower(status) IN ('completed','success')
                                  AND output_result IS NOT NULL
                                  AND output_result != '{}'
                                  AND NOT (output_result::text LIKE '%%"skipped": true%%')
                                  AND NOT (output_result::text LIKE '%%"reason": "control_step"%%')
                                ORDER BY timestamp DESC
                                """,
                                (child_exec_id,)
                            )
                            step_results = await cur.fetchall()
                            
                            for step_name, step_output in step_results:
                                try:
                                    step_result = json.loads(step_output) if isinstance(step_output, str) else step_output
                                    # Extract data if wrapped
                                    if isinstance(step_result, dict) and 'data' in step_result:
                                        step_result = step_result['data']
                                    if step_result:  # Any non-empty result
                                        child_result = step_result
                                        logger.info(f"LOOP_COMPLETION_CHECK: Found step result from {step_name} in child {child_exec_id}: {child_result}")
                                        break
                                except Exception:
                                    logger.debug(f"LOOP_COMPLETION_CHECK: Failed to parse result from {step_name} in child {child_exec_id}")
                                    continue
                        
                        if child_result:
                            # Mark as completed and add to aggregated results
                            child_data['completed'] = True
                            child_data['result'] = child_result
                            new_completed_count += 1
                            new_aggregated_results.append({
                                'iteration_index': child_data.get('iteration_index', 0),
                                'child_execution_id': child_exec_id,
                                'result': child_result
                            })
                            logger.info(f"LOOP_COMPLETION_CHECK: Child {child_exec_id} completed with result: {child_result}")
                        else:
                            # Fallback: accept any non-empty action_completed result from the child
                            await cur.execute(
                                """
                                SELECT output_result FROM noetl.event_log
                                WHERE execution_id = %s
                                  AND event_type = 'action_completed'
                                  AND lower(status) IN ('completed','success')
                                  AND output_result IS NOT NULL
                                  AND output_result != '{}'
                                  AND NOT (output_result::text LIKE '%"skipped": true%')
                                  AND NOT (output_result::text LIKE '%"reason": "control_step"%')
                                ORDER BY timestamp DESC
                                LIMIT 1
                                """,
                                (child_exec_id,)
                            )
                            row_any = await cur.fetchone()
                            if row_any:
                                try:
                                    import json
                                    any_out = row_any[0] if isinstance(row_any, tuple) else row_any.get('output_result')
                                    any_res = json.loads(any_out) if isinstance(any_out, str) else any_out
                                    if isinstance(any_res, dict) and 'data' in any_res:
                                        any_res = any_res['data']
                                    child_data['completed'] = True
                                    child_data['result'] = any_res
                                    new_completed_count += 1
                                    new_aggregated_results.append({
                                        'iteration_index': child_data.get('iteration_index', 0),
                                        'child_execution_id': child_exec_id,
                                        'result': any_res
                                    })
                                    logger.info(f"LOOP_COMPLETION_CHECK: Fallback accepted child {child_exec_id} result: {any_res}")
                                except Exception:
                                    pass
                        
                        updated_children.append(child_data)
                    
                    # Step 4: Update end_loop tracking event
                    if new_completed_count != completed_count:
                        event_service = get_event_service()
                        await event_service.emit({
                            'execution_id': parent_execution_id,
                            'event_type': 'end_loop',
                            'node_name': loop_step_name,
                            'node_type': 'loop_tracker',
                            'status': 'COMPLETED' if new_completed_count == len(child_executions_data) else 'TRACKING',
                            'context': {
                                'loop_step_name': loop_step_name,
                                'total_iterations': len(child_executions_data),
                                'child_executions': updated_children,
                                'completed_count': new_completed_count,
                                'aggregated_results': new_aggregated_results
                            }
                        })
                        logger.info(f"LOOP_COMPLETION_CHECK: Updated end_loop tracking for {loop_step_name}: {new_completed_count}/{len(child_executions_data)} completed")
                    
                    # Step 5: If all children completed, emit final loop result event (only once!)
                    if new_completed_count == len(child_executions_data):
                        # Check if we already emitted the final action_completed event for this specific loop completion
                        # to prevent infinite recursion, but allow legitimate workflow transition events
                        await cur.execute(
                            """
                            SELECT COUNT(*) as final_completion_count FROM noetl.event_log
                            WHERE execution_id = %s
                              AND event_type = 'action_completed'
                              AND node_name = %s
                              AND lower(status) = 'completed'
                              AND input_context::text LIKE '%loop_completed%'
                              AND input_context::text LIKE '%true%'
                            """,
                            (parent_execution_id, loop_step_name)
                        )
                        final_completion_row = await cur.fetchone()
                        final_completion_count = final_completion_row[0] if final_completion_row else 0
                        
                        if final_completion_count > 0:
                            logger.info(f"LOOP_COMPLETION_CHECK: Loop {loop_step_name} already has {final_completion_count} final completion events - skipping to prevent infinite recursion")
                            continue
                        
                        # Sort results by iteration index
                        sorted_results = sorted(new_aggregated_results, key=lambda x: x.get('iteration_index', 0))
                        final_results = [r['result'] for r in sorted_results]
                        
                        logger.info(f"LOOP_COMPLETION_CHECK: All children completed for {loop_step_name}: {new_completed_count}/{len(child_executions_data)} total children")
                        
                        # Create final loop result event with aggregated data
                        await event_service.emit({
                            'execution_id': parent_execution_id,
                            'event_type': 'action_completed',
                            'node_name': loop_step_name,
                            'node_type': 'loop',
                            'status': 'COMPLETED',
                            'result': final_results,
                            'context': {
                                'loop_completed': True,
                                'total_iterations': len(final_results),
                                'aggregated_results': final_results
                            }
                        })
                        logger.info(f"LOOP_COMPLETION_CHECK: Loop {loop_step_name} completed! Final aggregated results: {final_results}")
                        
    except Exception as e:
        logger.error(f"LOOP_COMPLETION_CHECK: Error processing loop completion: {e}")
        logger.debug("EVALUATE_BROKER_FOR_EXECUTION: Unhandled exception", exc_info=True)
        return
