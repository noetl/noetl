from __future__ import annotations

from typing import Any, Dict, Optional
import json
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def handle_workbook_event(event: Dict[str, Any], et: str) -> None:
    """Handle workbook-related events by resolving the referenced workbook action
    and updating the queued job to execute the concrete action directly.
    """
    try:
        execution_id = event.get('execution_id')
        step_name = event.get('node_name')
        if not execution_id or not step_name:
            return
        trig = str(event.get('trigger_event_id') or event.get('event_id') or '') or None
        await resolve_workbook_and_update_queue(str(execution_id), str(step_name), trig)
    except Exception:
        logger.debug("WORKBOOK_CONTROL: Failed handling workbook event", exc_info=True)


async def resolve_workbook_and_update_queue(execution_id: str, step_name: str, trigger_event_id: Optional[str]) -> None:
    """Resolve a workbook step into a concrete action and update/insert the queue job.

    - Loads playbook for the execution
    - Locates the workbook action referenced by the step's 'task'
    - Builds a concrete task config (http/python/etc.), merges 'with'
    - Updates the existing queue row's action for node_id f"{execution_id}:{step_name}", or inserts if missing
    - Adds _meta.parent_event_id to the job context for lineage
    """
    from noetl.core.common import get_async_db_connection
    from noetl.api.routers.broker.endpoint import encode_task_for_queue
    from noetl.api.routers.catalog import get_catalog_service
    import yaml as _yaml

    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Load playbook path/version
                await cur.execute(
                    """
                    SELECT context, meta FROM noetl.event
                    WHERE execution_id = %s AND event_type IN ('execution_start','execution_started')
                    ORDER BY timestamp ASC LIMIT 1
                    """,
                    (execution_id,)
                )
                row = await cur.fetchone()
                if not row:
                    return
                try:
                    ctx = json.loads(row[0]) if row[0] else {}
                except Exception:
                    ctx = row[0] or {}
                try:
                    meta = json.loads(row[1]) if row[1] else {}
                except Exception:
                    meta = row[1] or {}
                pb_path = (ctx.get('path') or (meta.get('path') if isinstance(meta, dict) else None))
                pb_ver = (ctx.get('version') or (meta.get('version') if isinstance(meta, dict) else None) or 'latest')
                if not pb_path:
                    return

                # Fetch playbook content
                catalog = get_catalog_service()
                entry = await catalog.fetch_entry(pb_path, pb_ver)
                if not entry or not entry.get('content'):
                    return
                pb = _yaml.safe_load(entry['content']) or {}
                steps = pb.get('workflow') or pb.get('steps') or []
                by_name: Dict[str, Dict[str, Any]] = {}
                for s in steps:
                    try:
                        nm = s.get('step') or s.get('name')
                        if nm:
                            by_name[str(nm)] = s
                    except Exception:
                        continue
                step_def = by_name.get(step_name)
                if not isinstance(step_def, dict):
                    return
                st_type = str(step_def.get('type') or '').lower()
                if st_type != 'workbook':
                    return
                task_ref = step_def.get('task') or step_def.get('name')
                if not task_ref:
                    return
                # Locate workbook action
                wb_actions = pb.get('workbook') or []
                target_action: Optional[Dict[str, Any]] = None
                for a in wb_actions:
                    try:
                        if a.get('name') == task_ref:
                            target_action = a
                            break
                    except Exception:
                        continue
                if not isinstance(target_action, dict):
                    return
                # Merge 'with' and 'data' values
                merged_with = {}
                try:
                    if isinstance(target_action.get('with'), dict):
                        merged_with.update(target_action.get('with'))
                    if isinstance(step_def.get('with'), dict):
                        merged_with.update(step_def.get('with'))
                    if isinstance(step_def.get('data'), dict):
                        merged_with.update(step_def.get('data'))
                except Exception:
                    pass
                # Construct action config
                action_cfg: Dict[str, Any] = {
                    'type': target_action.get('type'),
                    'name': task_ref,
                }
                for fld in ('code','command','commands','sql','url','endpoint','method','headers','params','data','payload','timeout'):
                    if target_action.get(fld) is not None:
                        action_cfg[fld] = target_action.get(fld)
                if merged_with:
                    action_cfg['with'] = merged_with
                encoded = encode_task_for_queue(action_cfg)

                # Build job context (augment with lineage)
                job_ctx = {
                    'workload': (ctx.get('workload') if isinstance(ctx, dict) else {}) or {},
                    'step_name': step_name,
                    'path': pb_path,
                    'version': pb_ver or 'latest'
                }
                if merged_with:
                    try:
                        job_ctx.update(merged_with)
                    except Exception:
                        pass
                if trigger_event_id:
                    try:
                        job_ctx['_meta'] = {'parent_event_id': str(trigger_event_id)}
                    except Exception:
                        pass

                node_id = f"{execution_id}:{step_name}"
                # Try update existing queue row for this step
                await cur.execute(
                    """
                    SELECT id FROM noetl.queue
                    WHERE execution_id = %s AND node_id = %s AND status IN ('queued','leased')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (execution_id, node_id)
                )
                qrow = await cur.fetchone()
                if qrow and (isinstance(qrow, tuple) or isinstance(qrow, list)):
                    qid = qrow[0]
                    await cur.execute(
                        "UPDATE noetl.queue SET action = %s, context = %s::jsonb WHERE id = %s",
                        (json.dumps(encoded), json.dumps(job_ctx), qid)
                    )
                else:
                    # Insert a new queue row if missing
                    await cur.execute(
                        """
                        INSERT INTO noetl.queue (execution_id, node_id, action, context, priority, max_attempts, available_at)
                        VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                        RETURNING id
                        """,
                        (execution_id, node_id, json.dumps(encoded), json.dumps(job_ctx), 5, 3)
                    )
                try:
                    await conn.commit()
                except Exception:
                    pass
                logger.info(f"WORKBOOK_CONTROL: Resolved workbook step '{step_name}' to concrete action and updated queue for execution {execution_id}")
    except Exception:
        logger.debug("WORKBOOK_CONTROL: Failed resolving workbook and updating queue", exc_info=True)
