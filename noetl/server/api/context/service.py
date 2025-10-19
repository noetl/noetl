"""
Context rendering service - handles template rendering logic.
"""

import json
from typing import Dict, Any, Optional, Tuple
from psycopg.rows import dict_row

from noetl.core.common import get_async_db_connection, get_snowflake_id_str, get_snowflake_id
from noetl.core.logger import setup_logger
from noetl.server.api.catalog import get_catalog_service
from noetl.server.api.event.event_log import EventLog

logger = setup_logger(__name__, include_location=True)


async def fetch_execution_context(execution_id: str) -> Dict[str, Any]:
    """
    Fetch execution context from database.
    
    Returns:
        Dictionary with:
        - workload: Workload configuration
        - results: Map of step_name -> result for completed steps
        - playbook_path: Path to playbook
        - playbook_version: Version of playbook
        - steps: Workflow steps definition
    """
    logger.debug(f"Fetching execution context for {execution_id}")
    
    workload = {}
    results: Dict[str, Any] = {}
    playbook_path = None
    playbook_version = None
    steps = []
    
    # Fetch workload from noetl.workload table (primary source of truth)
    async with get_async_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT data FROM noetl.workload
                WHERE execution_id = %s
                """,
                (execution_id,)
            )
            row = await cur.fetchone()
            if row and row.get('data'):
                try:
                    workload_data = row['data'] if isinstance(row['data'], dict) else json.loads(row['data'])
                    # The workload table stores: {"path": "...", "version": "...", "workload": {...}}
                    # Extract the actual workload dict from the nested structure
                    workload = workload_data.get("workload", {}) if isinstance(workload_data, dict) else {}
                    logger.debug(f"Loaded workload from noetl.workload table: {list(workload.keys()) if isinstance(workload, dict) else type(workload)}")
                except Exception as e:
                    logger.warning(f"Failed to parse workload from noetl.workload table: {e}")
                    workload = {}
    
    # Fallback: try to fetch from earliest event context if workload table had no data
    if not workload:
        dao = EventLog()
        first_ctx = await dao.get_earliest_context(execution_id)
        if first_ctx:
            try:
                ctx_first = json.loads(first_ctx) if isinstance(first_ctx, str) else first_ctx
                workload = ctx_first.get("workload", {}) if isinstance(ctx_first, dict) else {}
                logger.debug(f"Fallback: loaded workload from event context: {list(workload.keys()) if isinstance(workload, dict) else type(workload)}")
            except Exception as e:
                logger.warning(f"Failed to parse earliest context: {e}")
                workload = {}
    
    # Fetch results from all completed steps
    node_results = await dao.get_all_node_results(execution_id)
    if isinstance(node_results, dict):
        for node_name, out in node_results.items():
            if not node_name or out is None:
                continue
            try:
                results[node_name] = json.loads(out) if isinstance(out, str) else out
            except Exception:
                results[node_name] = out
    else:
        # Fallback for list/tuple format
        try:
            for row in node_results or []:
                try:
                    node_name, out = row
                except Exception:
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
        except Exception as e:
            logger.warning(f"Failed to process node results: {e}")
    
    # Fetch playbook metadata and steps
    async with get_async_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT context, meta FROM event
                WHERE execution_id = %s
                ORDER BY created_at ASC
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
                    metadata = json.loads(row.get("meta")) if row.get("meta") else {}
                except Exception:
                    metadata = row.get("meta") or {}
                
                playbook_path = (
                    context.get('path') or
                    (metadata.get('playbook_path') if isinstance(metadata, dict) else None) or
                    (metadata.get('path') if isinstance(metadata, dict) else None)
                )
                playbook_version = (
                    context.get('version') or
                    (metadata.get('version') if isinstance(metadata, dict) else None)
                )
    
    # Fetch playbook workflow steps if path available
    if playbook_path:
        try:
            catalog = get_catalog_service()
            entry = await catalog.fetch_entry(playbook_path, playbook_version or '')
            if entry:
                import yaml
                pb = yaml.safe_load(entry.get('content') or '') or {}
                workflow = pb.get('workflow', [])
                steps = pb.get('steps') or pb.get('tasks') or workflow
        except Exception as e:
            logger.warning(f"Failed to fetch playbook steps: {e}")
    
    return {
        'workload': workload,
        'results': results,
        'playbook_path': playbook_path,
        'playbook_version': playbook_version,
        'steps': steps,
    }


def build_rendering_context(
    workload: Dict[str, Any],
    results: Dict[str, Any],
    steps: list,
    extra_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build context dictionary for template rendering.
    
    Args:
        workload: Workload configuration
        results: Step results map
        steps: Workflow steps for alias resolution
        extra_context: Additional context to merge
    
    Returns:
        Complete context dictionary ready for Jinja2 rendering
    """
    base_ctx: Dict[str, Any] = {
        "work": workload,
        "workload": workload,
        "results": results
    }
    
    # Allow direct references to prior step names
    if isinstance(results, dict):
        base_ctx.update(results)
        # Flatten common result wrappers (e.g., {'status': 'success', 'data': {...}})
        for k, v in list(results.items()):
            try:
                if isinstance(v, dict) and 'data' in v:
                    base_ctx[k] = v.get('data')
            except Exception:
                pass
    
    # Alias workbook task results under their workflow step names
    if isinstance(steps, list):
        for st in steps:
            if isinstance(st, dict) and (st.get('type') or '').lower() == 'workbook':
                step_nm = st.get('step') or st.get('name') or st.get('task')
                task_nm = st.get('task') or st.get('name') or step_nm
                if step_nm and task_nm and isinstance(results, dict) and task_nm in results and step_nm not in base_ctx:
                    val = results[task_nm]
                    # Flatten wrapper
                    if isinstance(val, dict) and 'data' in val:
                        base_ctx[step_nm] = val.get('data')
                    else:
                        base_ctx[step_nm] = val
    
    # Back-compat: expose workload fields at top level
    base_ctx["context"] = base_ctx["work"]
    if isinstance(workload, dict):
        try:
            base_ctx.update(workload)
        except Exception:
            pass
    
    # Merge extra context
    if isinstance(extra_context, dict):
        try:
            base_ctx.update(extra_context)
            # Ensure job.uuid exists
            job_obj = base_ctx.get("job")
            if isinstance(job_obj, dict) and "uuid" not in job_obj:
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
    
    # Ensure job exists
    if "job" not in base_ctx:
        try:
            base_ctx["job"] = {"uuid": get_snowflake_id_str()}
        except Exception:
            try:
                base_ctx["job"] = {"uuid": str(get_snowflake_id())}
            except Exception:
                from uuid import uuid4
                base_ctx["job"] = {"uuid": str(uuid4())}
    
    return base_ctx


def merge_template_work_context(template: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge work object from template into rendering context.
    
    If template contains a 'work' object, promotes those values to top-level
    context for easier access during rendering.
    
    Args:
        template: Template object (may contain 'work' key)
        context: Base rendering context
    
    Returns:
        Updated context with template work merged
    """
    try:
        if isinstance(template, dict) and isinstance(template.get("work"), dict):
            incoming_work = template.get("work") or {}
            context["work"] = incoming_work
            context["context"] = incoming_work
            for k, v in incoming_work.items():
                if k not in context:
                    context[k] = v
    except Exception as e:
        logger.warning(f"Failed to merge template work context: {e}")
    
    return context


def render_template_object(template: Any, context: Dict[str, Any], strict: bool = True) -> Any:
    """
    Render a template object using Jinja2.
    
    Args:
        template: Template to render (can be dict, list, str, etc.)
        context: Rendering context
        strict: Whether to use strict undefined handling
    
    Returns:
        Rendered template result
    """
    from jinja2 import Environment, StrictUndefined, BaseLoader
    from noetl.core.dsl.render import render_template
    
    print(f"!!! RENDER_TEMPLATE_OBJECT CALLED: template type={type(template)}")
    logger.info(f"RENDER_TEMPLATE_OBJECT: template type={type(template)}, isinstance dict={isinstance(template, dict)}")
    if isinstance(template, str):
        logger.info(f"RENDER_TEMPLATE_OBJECT: template is string, value={template[:200]}")
    
    env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
    
    # Handle dict templates with work/task keys specially
    if isinstance(template, dict):
        logger.info(f"RENDER_DEBUG: Template is dict with keys: {list(template.keys())}")
        out: Dict[str, Any] = {}
        
        # Render 'work' with relaxed error handling
        if 'work' in template:
            try:
                out['work'] = render_template(env, template.get('work'), context, rules=None, strict_keys=False)
            except Exception as e:
                logger.warning(f"Failed to render work section: {e}")
                out['work'] = template.get('work')
        
        # Render 'task' with strict mode
        if 'task' in template:
            task_tpl = template.get('task')
            logger.info(f"RENDER_TASK_DEBUG: About to render task template: {task_tpl}")
            logger.info(f"RENDER_TASK_DEBUG: Context keys available: {list(context.keys())}")
            logger.info(f"RENDER_TASK_DEBUG: Workload in context: {'workload' in context}")
            if 'workload' in context:
                logger.info(f"RENDER_TASK_DEBUG: Workload value: {context['workload']}")
            try:
                # Strict rendering keeps unresolved variables for worker-side rendering
                task_rendered = render_template(env, task_tpl, context, rules=None, strict_keys=True)
                logger.info(f"RENDER_TASK_DEBUG: Task rendered successfully: {task_rendered}")
            except Exception as e:
                logger.warning(f"Failed to render task section: {e}")
                logger.warning(f"RENDER_TASK_DEBUG: Exception type: {type(e).__name__}")
                task_rendered = task_tpl
            
            # Parse JSON strings for convenience
            if isinstance(task_rendered, str):
                try:
                    import json
                    out['task'] = json.loads(task_rendered)
                except Exception:
                    out['task'] = task_rendered
            else:
                out['task'] = task_rendered
        
        # Pass through other keys unchanged
        for k, v in template.items():
            if k not in out:
                out[k] = v
        
        return out
    else:
        # Render single value
        try:
            return render_template(env, template, context, rules=None, strict_keys=False)
        except Exception as e:
            logger.warning(f"Failed to render template: {e}")
            return template


async def render_context(
    execution_id: str,
    template: Any,
    extra_context: Optional[Dict[str, Any]] = None,
    strict: bool = True
) -> Tuple[Any, list]:
    """
    Main service function to render a template against execution context.
    
    Args:
        execution_id: Execution ID to fetch context for
        template: Template to render
        extra_context: Additional context to merge
        strict: Whether to use strict undefined handling
    
    Returns:
        Tuple of (rendered_result, context_keys)
    """
    logger.info(f"Rendering template for execution {execution_id}")
    
    # Fetch execution context
    exec_ctx = await fetch_execution_context(execution_id)
    
    # Build rendering context
    render_ctx = build_rendering_context(
        workload=exec_ctx['workload'],
        results=exec_ctx['results'],
        steps=exec_ctx['steps'],
        extra_context=extra_context
    )
    
    # Merge template work context if present
    render_ctx = merge_template_work_context(template, render_ctx)
    
    # Render template
    rendered = render_template_object(template, render_ctx, strict)
    
    logger.debug(f"Successfully rendered template for execution {execution_id}")
    
    return rendered, list(render_ctx.keys())
