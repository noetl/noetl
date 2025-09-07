from __future__ import annotations
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.common import get_async_db_connection
from noetl.logger import setup_logger

logger = setup_logger(__name__, include_location=True)
router = APIRouter()

@router.get("/aggregate/loop/results", response_class=JSONResponse)
async def get_loop_iteration_results(execution_id: str, step_name: str) -> Dict[str, Any]:
    """
    Return the list of per-iteration results for a given execution and loop step.
    This endpoint sources data from event_log only (event-sourced server side),
    avoiding any worker-side DB access.

    Response:
      { status: 'ok', results: [...], count: N }
    """
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT output_result FROM noetl.event_log
                    WHERE execution_id = %s
                      AND node_name = %s
                      AND event_type IN ('result','action_completed')
                      AND node_id LIKE %s
                      AND lower(status) IN ('completed','success')
                      AND output_result IS NOT NULL AND output_result != '{}'
                      AND NOT (output_result::text LIKE '%%"skipped": true%%')
                      AND NOT (output_result::text LIKE '%%"reason": "control_step"%%')
                    ORDER BY timestamp
                    """,
                    (execution_id, step_name, f"{execution_id}-step-%-iter-%")
                )
                rows = await cur.fetchall()
        results: List[Any] = []
        for rr in rows or []:
            val = rr.get('output_result')
            try:
                import json
                parsed = json.loads(val) if isinstance(val, str) else val
            except Exception:
                parsed = val
            if isinstance(parsed, dict) and 'data' in parsed:
                parsed = parsed['data']
            if parsed is not None:
                results.append(parsed)
        return {"status": "ok", "results": results, "count": len(results)}
    except Exception as e:
        logger.exception(f"AGGREGATE.API: Failed to fetch loop results: {e}")
        raise HTTPException(status_code=500, detail=str(e))
