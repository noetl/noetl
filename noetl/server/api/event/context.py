"""
Context rendering endpoints for template processing.
"""

from typing import Dict, Any
import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.core.common import get_async_db_connection, get_snowflake_id_str, get_snowflake_id
from noetl.server.api.catalog import get_catalog_service
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/context/render", response_class=JSONResponse)
async def render_context(request: Request):
    """
    Render a Jinja2 template/object against the server-side execution context.
    Body:
      { execution_id: str, template: any, extra_context?: dict, strict?: bool }
    Context composed from DB:
      - work: workload (from earliest event context.workload, if present)
      - results: map of node_name -> result for all prior events in execution
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
        from noetl.server.api.event.event_log import EventLog
        dao = EventLog()
        first_ctx = await dao.get_earliest_context(execution_id)
        if first_ctx:
            try:
                ctx_first = json.loads(first_ctx) if isinstance(first_ctx, str) else first_ctx
                workload = ctx_first.get("workload", {}) if isinstance(ctx_first, dict) else {}
            except Exception:
                workload = {}
        node_results = await dao.get_all_node_results(execution_id)
        # get_all_node_results returns a dict mapping node_name -> result
        if isinstance(node_results, dict):
            for node_name, out in node_results.items():
                if not node_name or out is None:
                    continue
                try:
                    results[node_name] = json.loads(out) if isinstance(out, str) else out
                except Exception:
                    results[node_name] = out
        else:
            # Fallback in case of unexpected return type (e.g., list of tuples)
            try:
                for row in node_results or []:
                    try:
                        node_name, out = row
                    except Exception:
                        # Try dict-style access
                        try:
                            node_name = row.get('node_name')
                            out = row.get('result')
                        except Exception:
                            continue
                    if not node_name or out is None:
                        continue
                    try:
                        results[node_name] = json.loads(out) if isinstance(out, str) else out
                    except Exception:
                        results[node_name] = out
            except Exception:
                pass

        # Fetch playbook to get step aliases
        playbook_path = None
        playbook_version = None
        steps = []
        # The event table doesn't have playbook_path/version columns; derive from
        # the earliest event's input_context/metadata like evaluate_broker_for_execution
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT context, metadata FROM event
                    WHERE execution_id = %s
                    ORDER BY timestamp ASC
                    LIMIT 1
                    """,
                    (execution_id,)
                )
                row = await cur.fetchone()
                if row:
                    try:
                        context = json.loads(row["context"]) if row.get("context") else {}
                    except Exception:
                        context = row.get("context") or {}
                    try:
                        metadata = json.loads(row["metadata"]) if row.get("metadata") else {}
                    except Exception:
                        metadata = row.get("metadata") or {}
                    playbook_path = (context.get('path') or
                                     (metadata.get('playbook_path') if isinstance(metadata, dict) else None) or
                                     (metadata.get('resource_path') if isinstance(metadata, dict) else None))
                    playbook_version = (context.get('version') or
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
        from noetl.core.dsl.render import render_template
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
                    # Render task in strict mode so unresolved variables remain unchanged
                    # Worker-side rendering will resolve remaining placeholders later.
                    task_rendered = render_template(env, task_tpl, base_ctx, rules=None, strict_keys=True)
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
