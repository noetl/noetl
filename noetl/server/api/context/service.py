"""
Context rendering service - handles template rendering logic.
"""

import json
from typing import Any, Dict, Optional, Tuple

from psycopg.rows import dict_row

from noetl.core.common import (
    get_async_db_connection,
    get_snowflake_id,
    get_snowflake_id_str,
    get_val,
)
from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger
from noetl.server.api.broker.service import EventService
from noetl.server.api.catalog import get_catalog_service
from noetl.server.api.catalog.service import CatalogService

logger = setup_logger(__name__, include_location=True)


async def fetch_execution_context(execution_id: int) -> Dict[str, Any]:
    """
    Fetch execution context from database.

    Args:
        execution_id: Execution ID as integer (not string path)

    Returns:
        Dictionary with:
        - workload: Workload configuration
        - results: Map of step_name -> result for completed steps
        - playbook_path: Path to playbook
        - playbook_version: Version of playbook
        - steps: Workflow steps definition
    """
    # Validate execution_id is an integer
    if not isinstance(execution_id, int):
        raise TypeError(
            f"execution_id must be an integer, got {type(execution_id).__name__}: {execution_id}"
        )

    logger.debug(f"Fetching execution context for {execution_id}")

    workload_data = await EventService.get_workload(execution_id)
    resource_template = await CatalogService.fetch_resource_template(
        resource_path=workload_data.path, version=workload_data.version
    )
    # if not workload:
    #     workload = await EventService.get_context_workload(execution_id)

    # Fetch results from all completed steps
    results: Dict[str, Any] = await EventService.get_all_node_results(execution_id)

    # Fetch playbook metadata and steps
    # async with get_pool_connection() as conn:
    #     async with conn.cursor() as cur:
    #         await cur.execute(
    #             """
    #             SELECT context, meta FROM event
    #             WHERE execution_id = %(execution_id)s
    #             ORDER BY created_at ASC
    #             LIMIT 1
    #                 """,
    #                 {"execution_id": execution_id}
    #         )
    #         row = await cur.fetchone()
    #         if row:
    #             try:
    #                 context = json.loads(row["context"]) if row.get("context") else {}
    #             except Exception:
    #                 context = row.get("context") or {}
    #             try:
    #                 metadata = json.loads(row.get("meta")) if row.get("meta") else {}
    #             except Exception:
    #                 metadata = row.get("meta") or {}

    #             playbook_path = (
    #                 context.get('path') or
    #                 (metadata.get('playbook_path') if isinstance(metadata, dict) else None) or
    #                 (metadata.get('path') if isinstance(metadata, dict) else None)
    #             )
    #             playbook_version = (
    #                 context.get('version') or
    #                 (metadata.get('version') if isinstance(metadata, dict) else None)
    #             )

    # Fetch playbook workflow steps if path available
    # if playbook_path:
    #     try:
    #         catalog = get_catalog_service()
    #         entry = await catalog.fetch_entry(workload_data.path, workload_data.version)
    #         if entry:
    #             import yaml
    #             pb = yaml.safe_load(entry.get('content'))
    #             workflow = pb.get('workflow')
    #     except Exception as e:
    #         logger.exception(f"Failed to fetch playbook steps: {e}")

    return {
        "workload": workload_data.workload,
        "results": results,
        "playbook_path": workload_data.path,
        "playbook_version": workload_data.version,
        "steps": resource_template.get("workflow", []),
    }


def build_rendering_context(
    workload: Dict[str, Any],
    results: Dict[str, Any],
    steps: list,
    extra_context: Optional[Dict[str, Any]] = None,
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
        "results": results,
    }

    # Allow direct references to prior step names
    if isinstance(results, dict):
        # Add results with wrapper objects that support both direct access and .data attribute
        for k, v in results.items():
            try:
                # If result has 'data' key, create a wrapper that supports both patterns
                if isinstance(v, dict) and "data" in v:
                    # Create a dict-like object that allows both step.data and step.field access
                    class ResultWrapper(dict):
                        """Wrapper that allows accessing both the full result dict and the data field."""

                        def __init__(self, result_dict):
                            super().__init__(result_dict)
                            self.data = result_dict.get("data")
                            # Also expose other common fields
                            self.status = result_dict.get("status")
                            self.message = result_dict.get("message")

                    base_ctx[k] = ResultWrapper(v)
                else:
                    # For results without 'data' key, use as-is
                    base_ctx[k] = v
            except (TypeError, AttributeError, KeyError) as e:
                logger.debug(f"Could not wrap result for key '{k}': {e}")
                base_ctx[k] = v

    # Alias workbook task results under their workflow step names
    if isinstance(steps, list):
        for st in steps:
            if isinstance(st, dict):
                tool = st.get("tool")
                tool_lower = tool.strip().lower() if isinstance(tool, str) else ""
                if tool_lower != "workbook":
                    continue
                step_nm = st.get("step") or st.get("name") or st.get("task")
                task_nm = st.get("task") or st.get("name") or step_nm
                if (
                    step_nm
                    and task_nm
                    and isinstance(results, dict)
                    and task_nm in results
                    and step_nm not in base_ctx
                ):
                    val = results[task_nm]
                    # Flatten wrapper
                    if isinstance(val, dict) and "data" in val:
                        base_ctx[step_nm] = val.get("data")
                    else:
                        base_ctx[step_nm] = val

    # Back-compat: expose workload fields at top level
    base_ctx["context"] = base_ctx["work"]
    if isinstance(workload, dict):
        try:
            base_ctx.update(workload)
        except (TypeError, ValueError) as e:
            logger.warning(f"Could not update context with workload: {e}")

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
                    except (RuntimeError, OSError) as e:
                        logger.debug(f"Could not get snowflake ID string: {e}")
                        try:
                            job_obj["uuid"] = str(get_snowflake_id())
                        except (RuntimeError, OSError) as e2:
                            logger.debug(f"Could not get snowflake ID: {e2}")
                            from uuid import uuid4

                            job_obj["uuid"] = str(uuid4())
        except (TypeError, ValueError, KeyError) as e:
            logger.warning(f"Could not merge extra context: {e}")

    # Ensure job exists
    if "job" not in base_ctx:
        try:
            base_ctx["job"] = {"uuid": get_snowflake_id_str()}
        except (RuntimeError, OSError) as e:
            logger.debug(f"Could not get snowflake ID string for job: {e}")
            try:
                base_ctx["job"] = {"uuid": str(get_snowflake_id())}
            except (RuntimeError, OSError) as e2:
                logger.debug(f"Could not get snowflake ID for job: {e2}")
                from uuid import uuid4

                base_ctx["job"] = {"uuid": str(uuid4())}

    return base_ctx


def merge_template_work_context(
    template: Any, context: Dict[str, Any]
) -> Dict[str, Any]:
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


def render_template_object(
    template: Any, context: Dict[str, Any], strict: bool = True
) -> Any:
    """
    Render a template object using Jinja2.

    Args:
        template: Template to render (can be dict, list, str, etc.)
        context: Rendering context
        strict: Whether to use strict undefined handling

    Returns:
        Rendered template result
    """
    from jinja2 import BaseLoader, Environment, StrictUndefined

    from noetl.core.dsl.render import render_template

    print(f"!!! RENDER_TEMPLATE_OBJECT CALLED: template type={type(template)}")
    logger.info(
        f"RENDER_TEMPLATE_OBJECT: template type={type(template)}, isinstance dict={isinstance(template, dict)}"
    )
    if isinstance(template, str):
        logger.info(
            f"RENDER_TEMPLATE_OBJECT: template is string, value={template[:200]}"
        )

    env = Environment(loader=BaseLoader(), undefined=StrictUndefined)

    # Handle dict templates with work/task keys specially
    if isinstance(template, dict):
        logger.info(
            f"RENDER_DEBUG: Template is dict with keys: {list(template.keys())}"
        )
        out: Dict[str, Any] = {}

        # Render 'work' with relaxed error handling
        if "work" in template:
            try:
                out["work"] = render_template(
                    env, template.get("work"), context, rules=None, strict_keys=False
                )
            except Exception as e:
                logger.warning(f"Failed to render work section: {e}")
                out["work"] = template.get("work")

        # Render 'task' with strict mode
        if "task" in template:
            task_tpl = template.get("task")
            logger.debug(f"RENDER_TASK_DEBUG: Preparing to render task template")
            logger.debug(
                f"RENDER_TASK_DEBUG: Context keys available: {list(context.keys())}"
            )
            logger.debug(
                f"RENDER_TASK_DEBUG: Workload in context: {'workload' in context}"
            )
            try:
                # Extract and preserve 'save' block for worker-side rendering
                # The save block may reference 'result' which doesn't exist until after execution
                task_tpl_copy = (
                    dict(task_tpl) if isinstance(task_tpl, dict) else task_tpl
                )
                sink_block = None
                if isinstance(task_tpl_copy, dict) and "save" in task_tpl_copy:
                    sink_block = task_tpl_copy.pop("save")
                    logger.debug(
                        f"RENDER_TASK_DEBUG: Extracted save block: {sink_block}"
                    )
                    logger.debug(
                        f"RENDER_TASK_DEBUG: Remaining keys in task_tpl_copy: {list(task_tpl_copy.keys())}"
                    )

                # Strict rendering keeps unresolved variables for worker-side rendering
                task_rendered = render_template(
                    env, task_tpl_copy, context, rules=None, strict_keys=False
                )

                # Re-attach the save block after rendering (unrendered for worker-side processing)
                if sink_block is not None and isinstance(task_rendered, dict):
                    task_rendered['sink'] = sink_block
                    logger.debug(
                        "RENDER_TASK_DEBUG: Re-attached save block to rendered task"
                    )

                logger.info(
                    f"RENDER_TASK_DEBUG: Task rendered successfully: {task_rendered}"
                )
            except Exception as e:
                logger.warning(f"Failed to render task section: {e}")
                logger.warning(f"RENDER_TASK_DEBUG: Exception type: {type(e).__name__}")
                task_rendered = task_tpl

            # Parse JSON strings for convenience
            if isinstance(task_rendered, str):
                try:
                    import json

                    out["task"] = json.loads(task_rendered)
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    logger.debug(f"Could not parse task as JSON: {e}")
                    out["task"] = task_rendered
            else:
                out["task"] = task_rendered

        # Pass through other keys unchanged
        for k, v in template.items():
            if k not in out:
                out[k] = v

        return out
    else:
        # Render single value
        try:
            return render_template(
                env, template, context, rules=None, strict_keys=False
            )
        except Exception as e:
            logger.warning(f"Failed to render template: {e}")
            return template


async def render_context(
    execution_id: int,
    template: Any,
    extra_context: Optional[Dict[str, Any]] = None,
    strict: bool = True,
) -> Tuple[Any, list]:
    """
    Main service function to render a template against execution context.

    Args:
        execution_id: Execution ID as integer (not string path)
        template: Template to render
        extra_context: Additional context to merge
        strict: Whether to use strict undefined handling

    Returns:
        Tuple of (rendered_result, context_keys)
    """
    # Validate execution_id is an integer
    if not isinstance(execution_id, int):
        raise TypeError(
            f"execution_id must be an integer, got {type(execution_id).__name__}: {execution_id}"
        )

    logger.info(f"Rendering template for execution {execution_id}")

    # Fetch execution context
    exec_ctx = await fetch_execution_context(execution_id)

    # Ensure execution_id is in extra_context
    if extra_context is None:
        extra_context = {}
    if "execution_id" not in extra_context:
        extra_context["execution_id"] = execution_id

    # Build rendering context
    render_ctx = build_rendering_context(
        workload=exec_ctx["workload"],
        results=exec_ctx["results"],
        steps=exec_ctx["steps"],
        extra_context=extra_context,
    )

    # Merge template work context if present
    render_ctx = merge_template_work_context(template, render_ctx)

    # Render template
    rendered = render_template_object(template, render_ctx, strict)

    logger.debug(f"Successfully rendered template for execution {execution_id}")

    return rendered, list(render_ctx.keys())
