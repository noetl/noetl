"""
Context building utilities.

Loads playbook, workload, and execution results for evaluation.
"""

import json
import yaml
from typing import Dict, Any, Tuple, Optional
from noetl.core.logger import setup_logger
from ..event_log import EventLog

logger = setup_logger(__name__, include_location=True)


async def load_playbook_context(
    cur, execution_id: str
) -> Tuple[Optional[Dict], Optional[str], Optional[str], Dict]:
    """
    Load playbook and workload context for an execution.
    
    Returns: (playbook, pb_path, pb_ver, workload_ctx)
    """
    
    # Load workload
    await cur.execute(
        "SELECT data FROM noetl.workload WHERE execution_id = %s",
        (execution_id,)
    )
    wrow = await cur.fetchone()
    workload_ctx = {}
    if wrow and wrow[0]:
        try:
            workload_ctx = json.loads(wrow[0]) if isinstance(wrow[0], str) else (wrow[0] or {})
        except Exception:
            workload_ctx = {}
    
    # Get playbook path/version
    pb_path = (workload_ctx or {}).get('path') or (workload_ctx or {}).get('resource_path')
    pb_ver = (workload_ctx or {}).get('version')
    
    if not pb_path:
        # Try execution_start event
        await cur.execute(
            """
            SELECT context FROM noetl.event
            WHERE execution_id = %s AND event_type IN ('execution_start','execution_started')
            ORDER BY created_at DESC LIMIT 1
            """,
            (execution_id,)
        )
        er = await cur.fetchone()
        if er and er[0]:
            try:
                c = json.loads(er[0]) if isinstance(er[0], str) else (er[0] or {})
                pb_path = c.get('path')
                pb_ver = pb_ver or c.get('version')
            except Exception:
                pass
    
    if not pb_path:
        return None, None, None, workload_ctx
    
    # Fetch playbook from catalog
    from noetl.server.api.catalog import get_catalog_service
    catalog = get_catalog_service()
    
    if not pb_ver:
        try:
            pb_ver = await catalog.get_latest_version(pb_path)
        except Exception:
            pb_ver = '0.1.0'
    
    entry = await catalog.fetch_entry(pb_path, pb_ver)
    if not entry or not entry.get('content'):
        return None, pb_path, pb_ver, workload_ctx
    
    try:
        playbook = yaml.safe_load(entry['content']) or {}
    except Exception:
        playbook = {}
    
    # If workload is empty or missing the nested 'workload' key, load from catalog
    if not workload_ctx or not workload_ctx.get('workload'):
        logger.debug(f"Workload empty or missing nested 'workload' key, loading from catalog playbook")
        catalog_workload = playbook.get('workload', {})
        if catalog_workload:
            # Build the expected structure: {"path": "...", "version": "...", "workload": {...}}
            workload_ctx = {
                'path': pb_path,
                'version': pb_ver,
                'workload': catalog_workload
            }
            logger.info(f"Loaded workload from catalog: {list(catalog_workload.keys()) if isinstance(catalog_workload, dict) else type(catalog_workload)}")
    
    return playbook, pb_path, pb_ver, workload_ctx


async def build_evaluation_context(execution_id: str) -> Dict[str, Any]:
    """
    Build complete evaluation context with workload and all step results.
    
    Used for evaluating transition conditions.
    """
    dao = EventLog()
    
    # Get workload
    workload = {}
    first_ctx = await dao.get_earliest_context(execution_id)
    if first_ctx:
        try:
            ctx_first = json.loads(first_ctx) if isinstance(first_ctx, str) else first_ctx
            workload = ctx_first.get('workload', {}) if isinstance(ctx_first, dict) else {}
        except Exception:
            workload = {}
    
    # Get all step results
    results = {}
    node_results_map = await dao.get_all_node_results(execution_id)
    if isinstance(node_results_map, dict):
        for k, v in node_results_map.items():
            try:
                val = json.loads(v) if isinstance(v, str) else v
            except Exception:
                val = v
            
            # Flatten action envelope if present
            try:
                if isinstance(val, dict) and isinstance(val.get('data'), (dict, list)):
                    if 'status' in val or 'id' in val:
                        val = val.get('data')
            except Exception:
                pass
            
            results[str(k)] = val
    
    # Build context
    ctx = {
        'workload': workload,
        'work': workload,
        'context': workload,
        'execution_id': execution_id,
    }
    ctx.update(results)
    
    return ctx
