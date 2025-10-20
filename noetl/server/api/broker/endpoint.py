"""
Broker API endpoints and helper utilities for broker operations.
Renamed from routes.py to endpoint.py to better reflect purpose and avoid defining endpoints in __init__.
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request
from noetl.core.logger import setup_logger

# Orchestration functions live in the event service module
from noetl.server.api.event.service import (
    evaluate_execution,
)
from noetl.server.api.event.service.iterators import (
    check_iterator_completions,
)

from noetl.core.common import get_async_db_connection
from noetl.database import sqlcmd

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/broker/evaluate/{execution_id}")
async def trigger_broker_evaluation(execution_id: str):
    """Manually trigger orchestration evaluation for an execution, including iterator completion checks."""
    try:
        await evaluate_execution(execution_id)
        return {"status": "success", "message": f"Orchestration evaluation triggered for execution {execution_id}"}
    except Exception as e:
        logger.error(f"Failed to trigger orchestration evaluation for {execution_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger orchestration evaluation: {str(e)}")


@router.post("/iterator/complete/{execution_id}")
async def trigger_iterator_completion(execution_id: str):
    """Manually trigger iterator completion check for an execution."""
    try:
        await check_iterator_completions(execution_id)
        return {"status": "success", "message": f"Iterator completion check triggered for execution {execution_id}"}
    except Exception as e:
        logger.error(f"Failed to trigger iterator completion for {execution_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger iterator completion: {str(e)}")


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

@router.post("/workflow/config")
async def persist_workflow_config(request: Request):
    """
    Persist workflow steps, transitions, and workbook metadata for an execution.
    This endpoint is called by Broker._send_workflow_config during kickoff.
    Body example:
      {
        "steps": [...],
        "config": { "execution_id": "...", "playbook_path": "..." }
      }
    """
    try:
        body = await request.json()
        steps: List[Dict[str, Any]] = body.get("steps") or []
        cfg: Dict[str, Any] = body.get("config") or {}
        execution_id: Optional[str] = cfg.get("execution_id") or cfg.get("workflow_id") or cfg.get("id")
        playbook_path: Optional[str] = cfg.get("playbook_path") or cfg.get("path")
        if not execution_id:
            # Nothing to persist against
            return {"status": "ignored", "reason": "missing execution_id"}

        # Best-effort persistence; tolerate schema differences and duplicate inserts
        import json as _json
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Insert transitions derived from steps[].next
                for st in steps:
                    try:
                        from_step = st.get("step") or st.get("name")
                        next_list = st.get("next") or []
                        for nx in next_list:
                            try:
                                if isinstance(nx, dict):
                                    to_step = nx.get("step") or nx.get("name")
                                    condition = nx.get("when") or nx.get("condition")
                                    with_params = nx.get("with") or {}
                                else:
                                    to_step = str(nx)
                                    condition = None
                                    with_params = {}
                                if from_step and to_step:
                                    # Ensure condition is not None since it's part of the primary key
                                    condition_value = condition or ""
                                    try:
                                        await cur.execute(
                                            sqlcmd.TRANSITION_INSERT_POSTGRES,
                                            (
                                                execution_id,
                                                from_step,
                                                to_step,
                                                condition_value,
                                                _json.dumps(with_params) if with_params is not None else None,
                                            ),
                                        )
                                    except Exception:
                                        # Try duckdb template as fallback
                                        try:
                                            await cur.execute(
                                                sqlcmd.TRANSITION_INSERT_DUCKDB,
                                                (
                                                    execution_id,
                                                    from_step,
                                                    to_step,
                                                    condition_value,
                                                    _json.dumps(with_params) if with_params is not None else None,
                                                ),
                                            )
                                        except Exception:
                                            logger.debug("WORKFLOW_CONFIG: Failed to insert transition", exc_info=True)
                            except Exception:
                                logger.debug("WORKFLOW_CONFIG: Error processing next transition", exc_info=True)
                    except Exception:
                        logger.debug("WORKFLOW_CONFIG: Error processing step transitions", exc_info=True)

                # Insert workflow step metadata (best-effort; schema is 6 columns in templates)
                # Warn on multiple 'start'/'end' steps
                try:
                    _starts = sum(1 for s in steps if str((s.get('step') or s.get('name') or '')).strip().lower() == 'start')
                    _ends = sum(1 for s in steps if str((s.get('step') or s.get('name') or '')).strip().lower() == 'end')
                    if _starts > 1:
                        logger.warning(f"WORKFLOW_CONFIG: Multiple 'start' steps detected for execution {execution_id}; expected exactly one")
                    if _ends > 1:
                        logger.warning(f"WORKFLOW_CONFIG: Multiple 'end' steps detected for execution {execution_id}; expected exactly one")
                except Exception:
                    pass
                for st in steps:
                    try:
                        step_name = st.get("step") or st.get("name") or ""
                        # Derive special types for control steps 'start' and 'end'
                        if str(step_name).strip().lower() in {"start","end"}:
                            step_type = str(step_name).strip().lower()
                        else:
                            step_type = st.get("type") or st.get("kind") or st.get("task_type") or ""
                        desc = st.get("desc") or st.get("description") or ""
                        raw = _json.dumps(st)
                        # Use step_name as step_id since it should be unique within the workflow
                        step_id = step_name or f"step_{len(steps)}"
                        vals6 = (
                            execution_id,
                            step_id,
                            step_name,
                            step_type,
                            desc,
                            raw,
                        )
                        try:
                            await cur.execute(sqlcmd.WORKFLOW_INSERT_POSTGRES, vals6)
                        except Exception:
                            try:
                                await cur.execute(sqlcmd.WORKFLOW_INSERT_DUCKDB, vals6)
                            except Exception:
                                logger.debug("WORKFLOW_CONFIG: Failed to insert workflow row", exc_info=True)
                    except Exception:
                        logger.debug("WORKFLOW_CONFIG: Error inserting workflow row", exc_info=True)

                # Insert workbook metadata for workbook-type steps (5 columns in templates)
                for st in steps:
                    try:
                        st_type = (st.get("type") or "").lower()
                        if st_type != "workbook":
                            continue
                        step_name = st.get("step") or st.get("name") or ""
                        task_name = st.get("task") or st.get("name") or ""
                        desc = st.get("desc") or st.get("description") or ""
                        raw = _json.dumps(st)
                        vals5 = (
                            execution_id,
                            playbook_path or "",
                            step_name,
                            task_name,
                            raw,
                        )
                        try:
                            await cur.execute(sqlcmd.WORKBOOK_INSERT_POSTGRES, vals5)
                        except Exception:
                            try:
                                await cur.execute(sqlcmd.WORKBOOK_INSERT_DUCKDB, vals5)
                            except Exception:
                                logger.debug("WORKFLOW_CONFIG: Failed to insert workbook row", exc_info=True)
                    except Exception:
                        logger.debug("WORKFLOW_CONFIG: Error inserting workbook row", exc_info=True)

                try:
                    await conn.commit()
                except Exception:
                    pass
        return {"status": "ok", "persisted": True}
    except Exception as e:
        logger.error(f"WORKFLOW_CONFIG: Failed to persist workflow config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

__all__ = [
    'router',
    'encode_task_for_queue',
]
