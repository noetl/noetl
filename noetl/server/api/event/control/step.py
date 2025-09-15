from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import json
from jinja2 import Environment, StrictUndefined, BaseLoader
from noetl.core.logger import setup_logger
from ..event_log import EventLog
from ..processing import evaluate_broker_for_execution

logger = setup_logger(__name__, include_location=True)


async def handle_step_event(event: Dict[str, Any], et: str) -> None:
    try:
        execution_id = event.get('execution_id')
        step_name = event.get('node_name')
        if not execution_id or not step_name:
            return

        # If this is a step_started for a workbook step, resolve workbook to concrete action and update queue
        if et == 'step_started':
            by_name, pb_path, pb_ver = await _load_playbook_and_index(str(execution_id))
            if by_name:
                cur_step = by_name.get(step_name)
                st_type = str((cur_step or {}).get('type') or '').lower()
                if st_type == 'workbook':
                    try:
                        from .workbook import resolve_workbook_and_update_queue
                        trig = str(event.get('trigger_event_id') or event.get('event_id') or '') or None
                        await resolve_workbook_and_update_queue(str(execution_id), step_name, trig)
                    except Exception:
                        logger.debug("STEP_CONTROL: Workbook resolve/update failed", exc_info=True)
            # Still allow standard broker evaluation to keep state consistent
            trig = str(event.get('trigger_event_id') or event.get('event_id') or '') or None
            await evaluate_broker_for_execution(str(execution_id), trigger_event_id=trig)
            return

        # Build evaluation context: workload + prior results
        base_ctx = await _build_base_ctx(str(execution_id))

        # Load playbook and transitions
        by_name, pb_path, pb_ver = await _load_playbook_and_index(str(execution_id))
        if not by_name:
            logger.debug("STEP_CONTROL: No playbook index available; skipping")
            return
        cur_step = by_name.get(step_name)
        if not isinstance(cur_step, dict):
            logger.debug("STEP_CONTROL: Current step not found in by_name index; skipping")
            return

        # Choose next transition using 'when' evaluation
        next_choice = _choose_next(cur_step, base_ctx)
        if not next_choice:
            logger.info(f"STEP_CONTROL: No next transition chosen for step {step_name}")
            # If this is the terminal 'end' step, emit execution_complete using declared result/save mapping
            try:
                if str(step_name).strip().lower() == 'end':
                    from noetl.server.api.event import get_event_service
                    es = get_event_service()
                    # Compute final result from 'result' mapping or fallback to save.data
                    final_result = None
                    try:
                        # 1) Prefer explicit 'result' mapping
                        res_map = cur_step.get('result') if isinstance(cur_step, dict) else None
                        if isinstance(res_map, (dict, list, str)):
                            from noetl.core.dsl.render import render_template
                            jenv = Environment(loader=BaseLoader(), undefined=StrictUndefined)
                            final_result = render_template(jenv, res_map, base_ctx, rules=None, strict_keys=False)
                    except Exception:
                        final_result = None
                    # 2) Fallback: if save.data exists (common pattern), render it and use as final result
                    if final_result is None:
                        try:
                            save_block = cur_step.get('save') if isinstance(cur_step, dict) else None
                            if isinstance(save_block, dict):
                                data_map = save_block.get('data')
                                if data_map is not None:
                                    from noetl.core.dsl.render import render_template
                                    jenv = Environment(loader=BaseLoader(), undefined=StrictUndefined)
                                    final_result = render_template(jenv, data_map, base_ctx, rules=None, strict_keys=False)
                        except Exception:
                            final_result = None
                    # 3) Last resort: pull the latest action_completed result for this step from event_log
                    if final_result is None:
                        try:
                            from noetl.core.common import get_async_db_connection
                            async with get_async_db_connection() as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                        """
                                        SELECT result FROM noetl.event_log
                                        WHERE execution_id = %s
                                          AND node_name = %s
                                          AND event_type = 'action_completed'
                                        ORDER BY timestamp DESC
                                        LIMIT 1
                                        """,
                                        (execution_id, step_name)
                                    )
                                    row = await cur.fetchone()
                                    if row and row[0]:
                                        try:
                                            final_result = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                                        except Exception:
                                            final_result = row[0]
                        except Exception:
                            final_result = None

                    await es.emit({
                        'execution_id': execution_id,
                        'event_type': 'execution_complete',
                        'status': 'COMPLETED',
                        'node_name': step_name,
                        'node_type': 'playbook',
                        'result': final_result if final_result is not None else {},
                        'context': {'reason': 'end_step'}
                    })
            except Exception:
                logger.debug("STEP_CONTROL: Failed to emit execution_complete for end step", exc_info=True)
            return
        next_step_name, next_with = next_choice

        # Enqueue the chosen next step or finalize if non-actionable
        try:
            from ..processing.loop_completion import _enqueue_next_step
            trig = str(event.get('trigger_event_id') or event.get('event_id') or '') or None
            # Open a DB cursor for enqueue
            from noetl.core.common import get_async_db_connection
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cur:
                    await _enqueue_next_step(conn, cur, str(execution_id), next_step_name, next_with or {}, by_name, trig)
        except Exception:
            logger.debug("STEP_CONTROL: Failed to enqueue next step from controller", exc_info=True)
    except Exception:
        logger.debug("STEP_CONTROL: Failed handling step event", exc_info=True)


async def _build_base_ctx(execution_id: str) -> Dict[str, Any]:
    workload = {}
    results: Dict[str, Any] = {}
    try:
        dao = EventLog()
        first_ctx = await dao.get_earliest_context(execution_id)
        if first_ctx:
            try:
                c = json.loads(first_ctx) if isinstance(first_ctx, str) else first_ctx
                workload = c.get('workload', {}) if isinstance(c, dict) else {}
            except Exception:
                workload = {}
        node_results = await dao.get_all_node_results(execution_id)
        if isinstance(node_results, dict):
            for k, v in node_results.items():
                try:
                    results[str(k)] = json.loads(v) if isinstance(v, str) else v
                except Exception:
                    results[str(k)] = v
    except Exception:
        pass
    base_ctx = {'workload': workload, 'work': workload, 'context': workload}
    try:
        base_ctx.update(results)
    except Exception:
        pass
    return base_ctx


async def _load_playbook_and_index(execution_id: str) -> Tuple[Dict[str, Dict[str, Any]], Optional[str], Optional[str]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    pb_path = None
    pb_ver = None
    try:
        from noetl.core.common import get_async_db_connection
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT context, metadata FROM noetl.event_log
                    WHERE execution_id = %s AND event_type IN ('execution_start','execution_started')
                    ORDER BY timestamp ASC LIMIT 1
                    """,
                    (execution_id,)
                )
                row = await cur.fetchone()
                if row:
                    try:
                        ctx = json.loads(row[0]) if row[0] else {}
                    except Exception:
                        ctx = row[0] or {}
                    try:
                        meta = json.loads(row[1]) if row[1] else {}
                    except Exception:
                        meta = row[1] or {}
                    pb_path = (ctx.get('path') or (meta.get('playbook_path') if isinstance(meta, dict) else None) or (meta.get('resource_path') if isinstance(meta, dict) else None))
                    pb_ver = (ctx.get('version') or (meta.get('resource_version') if isinstance(meta, dict) else None))
        if pb_path:
            from noetl.server.api.catalog import get_catalog_service
            catalog = get_catalog_service()
            if not pb_ver:
                try:
                    pb_ver = await catalog.get_latest_version(pb_path)
                except Exception:
                    pb_ver = '0.1.0'
            entry = await catalog.fetch_entry(pb_path, pb_ver)
            if entry and entry.get('content'):
                import yaml as _yaml
                pb = _yaml.safe_load(entry['content']) or {}
                steps = pb.get('workflow') or pb.get('steps') or []
                for s in steps:
                    try:
                        nm = s.get('step') or s.get('name')
                        if nm:
                            by_name[str(nm)] = s
                    except Exception:
                        continue
    except Exception:
        logger.debug("STEP_CONTROL: Failed to load playbook/index", exc_info=True)
    return by_name, pb_path, pb_ver


def _truthy(val: Any) -> bool:
    try:
        if isinstance(val, bool):
            return val
        if val is None:
            return False
        if isinstance(val, (int, float)):
            return val != 0
        s = str(val).strip().lower()
        if s in {'true', 'yes', 'y', 'on'}:
            return True
        if s in {'false', 'no', 'n', 'off', '', 'none', 'null'}:
            return False
        # Non-empty strings considered truthy
        return True
    except Exception:
        return False


def _choose_next(step_def: Dict[str, Any], base_ctx: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    nxt = step_def.get('next') or []
    if not isinstance(nxt, list):
        nxt = [nxt]
    if not nxt:
        return None

    from noetl.core.dsl.render import render_template
    jenv = Environment(loader=BaseLoader(), undefined=StrictUndefined)

    # 1) Prefer the first item with a truthy 'when' condition
    for item in nxt:
        if isinstance(item, dict) and 'when' in item:
            try:
                cond = item.get('when')
                val = render_template(jenv, cond, base_ctx, rules=None, strict_keys=False) if isinstance(cond, (str, dict, list)) else cond
                if _truthy(val):
                    step_nm = item.get('step') or item.get('name')
                    return (step_nm, item.get('with') or {}) if step_nm else None
            except Exception:
                continue

    # 2) If no 'when' matched, choose the first item without a condition
    for item in nxt:
        if isinstance(item, dict):
            if 'when' not in item:
                nm = item.get('step') or item.get('name')
                if nm:
                    return nm, item.get('with') or {}
        else:
            # string step reference
            return str(item), {}

    return None
