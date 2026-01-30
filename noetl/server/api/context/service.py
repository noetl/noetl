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
from noetl.worker.transient import TransientVars

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

    workload_from_context = await EventService.get_context_workload(execution_id)
    workload_data = workload_from_context or {}

    playbook_path = None
    playbook_version = None
    if isinstance(workload_data, dict):
        playbook_path = workload_data.get("path")
        playbook_version = workload_data.get("version")

    resource_template = {}
    if playbook_path:
        resource_template = await CatalogService.fetch_resource_template(
            resource_path=playbook_path, version=playbook_version
        )

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
        "workload": workload_data.get("workload", workload_data) if isinstance(workload_data, dict) else {},
        "results": results,
        "playbook_path": playbook_path,
        "playbook_version": playbook_version,
        "steps": resource_template.get("workflow", []) if isinstance(resource_template, dict) else [],
    }


async def build_rendering_context(
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

    # Add vars namespace from TransientVars if execution_id available
    execution_id = None
    if isinstance(extra_context, dict):
        execution_id = extra_context.get("execution_id")
    
    if execution_id:
        try:
            vars_data = await TransientVars.get_all_vars(execution_id)
            base_ctx["vars"] = vars_data
            logger.info(f"✓ Loaded {len(vars_data)} variables from transient for execution {execution_id}")
        except Exception as e:
            logger.warning(f"Failed to load transient for execution {execution_id}: {e}")
            base_ctx["vars"] = {}
    else:
        logger.info("No execution_id in extra_context, vars namespace will be empty")
        base_ctx["vars"] = {}

    # Allow direct references to prior step names
    if isinstance(results, dict):
        # Add results with wrapper objects that support both direct access and .data attribute
        for k, v in results.items():
            try:
                # If result has 'data' key, create a wrapper that supports both patterns
                if isinstance(v, dict) and "data" in v:
                    # Create a dict-like object that allows both step.data and step.field access
                    class ResultWrapper(dict):
                        """Wrapper that allows accessing both the full result dict and the data field.

                        Supports multiple access patterns:
                        - {{ step.data.field }}  - explicit data access
                        - {{ step.field }}       - direct field access (proxied to data)
                        - {{ step.status }}      - explicit status access
                        """

                        def __init__(self, result_dict):
                            super().__init__(result_dict)
                            self._data = result_dict.get("data") or {}
                            # Also expose other common fields
                            self._status = result_dict.get("status")
                            self._message = result_dict.get("message")
                            self._kind = result_dict.get("kind")

                        @property
                        def data(self):
                            return self._data

                        @property
                        def status(self):
                            return self._status

                        @property
                        def message(self):
                            return self._message

                        @property
                        def kind(self):
                            return self._kind

                        def __getattr__(self, name):
                            """Proxy attribute access to data field for flat access patterns."""
                            # Don't proxy special names or already-defined attributes
                            if name.startswith('_') or name in ('data', 'status', 'message', 'kind'):
                                raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
                            # Try to get from _data (the flattened result)
                            if isinstance(self._data, dict) and name in self._data:
                                return self._data[name]
                            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

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

    # Merge extra context FIRST (before workload) to establish protected system fields
    if isinstance(extra_context, dict):
        try:
            # DEBUG: Log execution_id from extra_context
            if "execution_id" in extra_context:
                logger.info(f"[CONTEXT] execution_id from extra_context: {extra_context['execution_id']} (type: {type(extra_context['execution_id']).__name__})")
            base_ctx.update(extra_context)
        except (TypeError, ValueError, KeyError) as e:
            logger.warning(f"Could not update context with extra_context: {e}")

    # Back-compat: expose workload fields at top level
    base_ctx["context"] = base_ctx["work"]
    if isinstance(workload, dict):
        try:
            # Protected fields that should not be overwritten by workload
            protected_fields = {"execution_id", "catalog_id", "job_id"}
            # Save protected values
            protected_values = {k: base_ctx.get(k) for k in protected_fields if k in base_ctx}
            # DEBUG: Log what we're protecting
            if protected_values:
                logger.info(f"[CONTEXT] Protecting fields: {list(protected_values.keys())} with values: {protected_values}")
            if "execution_id" in workload:
                logger.warning(f"[CONTEXT] workload contains execution_id={workload['execution_id']}, will be overridden by protected value")
            # Merge workload
            base_ctx.update(workload)
            # Restore protected values
            base_ctx.update(protected_values)
            # DEBUG: Verify execution_id after restore
            if "execution_id" in base_ctx:
                logger.info(f"[CONTEXT] After restore, execution_id={base_ctx['execution_id']} (type: {type(base_ctx['execution_id']).__name__})")
        except (TypeError, ValueError) as e:
            logger.warning(f"Could not update context with workload: {e}")

    # Ensure job.uuid exists (after all merges)
    if isinstance(extra_context, dict):
        try:
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
    
    Also promotes 'args' from the task object to make them available for template rendering.

    Args:
        template: Template object (may contain 'work' key and 'task' key with 'args')
        context: Base rendering context

    Returns:
        Updated context with template work and args merged
    """
    try:
        if isinstance(template, dict) and isinstance(template.get("work"), dict):
            incoming_work = template.get("work") or {}
            context["work"] = incoming_work
            context["context"] = incoming_work
            for k, v in incoming_work.items():
                if k not in context:
                    context[k] = v
        
        # Promote args from task to top-level context for template rendering
        # Args may contain templates that need to be rendered with the current context first
        if isinstance(template, dict):
            task_obj = template.get("task")
            if isinstance(task_obj, dict):
                args_obj = task_obj.get("args")
                if isinstance(args_obj, dict):
                    logger.debug(f"Promoting task args to context: {list(args_obj.keys())}")
                    # Render args templates BEFORE promoting to context
                    # This ensures templates like {{ fetch_github_repo.data.name }} are resolved
                    from jinja2 import Environment, BaseLoader, Undefined
                    env = Environment(loader=BaseLoader(), undefined=Undefined)
                    
                    for k, v in args_obj.items():
                        # Skip if already in context to avoid overriding
                        if k in context:
                            continue
                        # Render template strings
                        if isinstance(v, str) and "{{" in v:
                            try:
                                tmpl = env.from_string(v)
                                rendered_val = tmpl.render(**context)
                                context[k] = rendered_val
                                logger.debug(f"  Rendered arg {k}: '{v}' -> '{rendered_val}'")
                            except Exception as e:
                                logger.warning(f"Failed to render arg template '{k}': {e}")
                                context[k] = v
                        else:
                            context[k] = v
    except Exception as e:
        logger.warning(f"Failed to merge template work/args context: {e}")

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

    template_info = f"type={type(template)} | is_dict={isinstance(template, dict)}"
    if isinstance(template, str):
        template_info += f" | value={template[:200]}"
    elif isinstance(template, dict):
        template_info += f" | keys={list(template.keys())}"
    logger.info(f"RENDER_TEMPLATE_OBJECT: {template_info}")

    env = Environment(loader=BaseLoader(), undefined=StrictUndefined)

    # Handle dict templates specially
    if isinstance(template, dict):
        logger.info(
            f"RENDER_DEBUG: Template is dict with keys: {list(template.keys())}"
        )
        
        # Make a copy to avoid mutating the original
        template = dict(template)
        
        # Determine if this is an iterator step (OLD format) or has loop (NEW format)
        is_iterator = (template.get("tool") or "").lower() == "iterator"
        has_loop = "loop" in template
        
        # Also check for loop inside template['task'] (when wrapped by worker)
        task_dict = template.get('task') if isinstance(template.get('task'), dict) else None
        if task_dict and "loop" in task_dict:
            has_loop = True
        
        # Extract blocks that should not be rendered server-side:
        # 1. For iterator steps (OLD format): the nested 'task' block (contains {{ item }} templates)
        # 2. For loop steps (NEW format): the 'loop' block (contains {{ item }} templates)
        # 3. For all steps: the 'sink' block (contains {{ result }} templates)
        task_block = None
        loop_block = None
        sink_block = None
        
        task_dict_keys = list(task_dict.keys()) if task_dict else None
        logger.critical(f"RENDER_DEBUG: Before extraction | template_keys={list(template.keys())} | has_loop={has_loop} | task_dict_exists={task_dict is not None} | task_dict_keys={task_dict_keys}")
        if task_dict:
            # Extract sink from inside the task dict
            if 'sink' in task_dict:
                sink_block = task_dict.pop('sink')
                logger.critical(f"RENDER_DEBUG: Extracted sink from template['task']: {sink_block}")
        
        if is_iterator and "task" in template:
            task_block = template.pop("task")
            logger.debug(f"RENDER_DEBUG: Extracted iterator task block to preserve unrendered")
        
        # Extract loop from task dict OR top level
        if has_loop:
            if task_dict and "loop" in task_dict:
                loop_block = task_dict.pop("loop")
                loop_source = "template['task']"
            elif "loop" in template:
                loop_block = template.pop("loop")
                loop_source = "top level"
            else:
                loop_source = None
            if loop_source:
                logger.critical(f"RENDER_DEBUG: Extracted loop block from {loop_source}")
        
        # Also check for top-level sink (legacy support)
        if "sink" in template:
            top_level_sink = template.pop("sink")
            if sink_block is None:
                sink_block = top_level_sink
            logger.critical(f"RENDER_DEBUG: Extracted top-level sink (preserve unrendered) | sink={top_level_sink}")
        
        # NEW: For loop steps, preserve fields that may reference loop variables
        # These fields should only be rendered worker-side after loop context is available
        preserved_fields = {}
        if has_loop:
            logger.critical(f"RENDER_DEBUG: Loop detected, preserving loop-sensitive fields")
            # Fields that commonly reference loop variables ({{ patient_id }}, {{ item }}, etc.)
            loop_sensitive_fields = ['url', 'endpoint', 'data', 'params', 'payload', 'code', 'command', 'commands', 'query', 'sql']
            # Check both task dict and top-level template
            for field in loop_sensitive_fields:
                if task_dict and field in task_dict:
                    preserved_fields[field] = task_dict.pop(field)
                    logger.critical(f"RENDER_DEBUG: Preserved loop-sensitive field '{field}' from template['task']")
                elif field in template:
                    preserved_fields[field] = template.pop(field)
                    logger.critical(f"RENDER_DEBUG: Preserved loop-sensitive field '{field}' from top-level template")
        
        # Render the template (everything except extracted blocks and preserved fields)
        try:
            # DEBUG: Log what we're about to render
            logger.critical(f"RENDER_DEBUG: About to render template={template}")
            for k, v in context.items():
                if k in ['success', 'validate_token']:
                    logger.critical(f"RENDER_DEBUG: context[{k}]={type(v).__name__} | v={v}")

            out = render_template(
                env, template, context, rules=None, strict_keys=False
            )
            logger.critical(f"RENDER_DEBUG: After render_template, out={out}")
            if not isinstance(out, dict):
                out = {"rendered": out}
        except Exception as e:
            logger.warning(f"Failed to render template: {e}")
            out = dict(template)
        
        # Restore preserved fields (unrendered) to the correct location
        # If they came from task_dict, restore to out['task']
        # Otherwise restore to top level
        for field, value in preserved_fields.items():
            if task_dict is not None and isinstance(out.get('task'), dict):
                out['task'][field] = value
                logger.critical(f"RENDER_DEBUG: Restored preserved field '{field}' unrendered to out['task']")
            else:
                out[field] = value
                logger.critical(f"RENDER_DEBUG: Restored preserved field '{field}' unrendered to top level")
        
        # Restore the unrendered blocks
        if task_block is not None:
            out['task'] = task_block
            logger.debug("RENDER_DEBUG: Restored unrendered iterator task block")
        
        if loop_block is not None:
            # Restore loop block to the same location it was extracted from
            if task_dict is not None and isinstance(out.get('task'), dict):
                out['task']['loop'] = loop_block
                restore_location = "out['task']"
            else:
                out['loop'] = loop_block
                restore_location = "top level"
            logger.critical(f"RENDER_DEBUG: Restored loop block to {restore_location}")
        
        if sink_block is not None:
            # Restore sink into the task dict where it came from
            if isinstance(out.get('task'), dict):
                out['task']['sink'] = sink_block
                restore_location = "out['task']"
            else:
                # Fallback: restore to top level if task dict not found
                out['sink'] = sink_block
                restore_location = "top level"
            logger.critical(f"RENDER_DEBUG: Restored unrendered sink to {restore_location} | sink={sink_block}")
        
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
    render_ctx = await build_rendering_context(
        workload=exec_ctx["workload"],
        results=exec_ctx["results"],
        steps=exec_ctx["steps"],
        extra_context=extra_context,
    )

    # Merge template work context if present
    render_ctx = merge_template_work_context(template, render_ctx)

    # DEBUG: Log context for key step results
    for key in ['success', 'validate_token', 'upsert_user', 'create_session']:
        if key in render_ctx:
            val = render_ctx[key]
            logger.critical(f"RENDER_CONTEXT_DEBUG: {key}={type(val).__name__} | keys={list(val.keys()) if hasattr(val, 'keys') else 'N/A'}")
            if hasattr(val, '_data'):
                logger.critical(f"RENDER_CONTEXT_DEBUG: {key}._data={val._data}")

    # Render template
    rendered = render_template_object(template, render_ctx, strict)

    logger.debug(f"Successfully rendered template for execution {execution_id}")

    return rendered, list(render_ctx.keys())
