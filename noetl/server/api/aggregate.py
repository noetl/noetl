from __future__ import annotations
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.core.common import get_async_db_connection
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)
router = APIRouter()

@router.get("/aggregate/loop/results", response_class=JSONResponse)
async def get_loop_iteration_results(execution_id: str, step_name: str) -> Dict[str, Any]:
    """
    Return the list of per-iteration results for a given execution and loop step.
    This endpoint sources data from event_log only (event-sourced server side),
    avoiding any worker-side DB access.
    
    Uses generic loop metadata fields for robust filtering instead of content-specific logic.

    Response:
      { status: 'ok', results: [...], count: N }
    """
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # First, try to get results using proper loop metadata fields
                await cur.execute(
                    """
                    SELECT DISTINCT
                        result,
                        current_index,
                        loop_id,
                        node_id,
                        timestamp
                    FROM noetl.event_log
                    WHERE execution_id = %s
                      AND loop_name = %s
                      AND event_type IN ('result','action_completed')
                      AND lower(status) IN ('completed','success')
                      AND result IS NOT NULL 
                      AND result != '{}' 
                      AND loop_id IS NOT NULL
                      AND current_index IS NOT NULL
                      AND NOT (result::text LIKE '%%"skipped": true%%')
                      AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                    ORDER BY current_index, timestamp
                    """,
                    (execution_id, step_name)
                )
                metadata_rows = await cur.fetchall()
                
                # If we found results using metadata, use them
                if metadata_rows:
                    logger.info(f"AGGREGATE: Found {len(metadata_rows)} results using loop metadata for {execution_id}:{step_name}")
                    results = []
                    for rr in metadata_rows:
                        val = rr.get('result')
                        try:
                            import json
                            parsed = json.loads(val) if isinstance(val, str) else val
                        except Exception:
                            parsed = val
                        if isinstance(parsed, dict) and 'data' in parsed:
                            parsed = parsed['data']
                        if parsed is not None:
                            results.append(parsed)
                    
                    return {"status": "ok", "results": results, "count": len(results), "method": "loop_metadata"}
                
                # Fallback to legacy content-based filtering if metadata approach fails
                logger.warning(f"AGGREGATE: No results found using loop metadata, falling back to legacy filtering for {execution_id}:{step_name}")
                await cur.execute(
                    """
                    SELECT result FROM noetl.event_log
                    WHERE execution_id = %s
                      AND node_name = %s
                      AND event_type IN ('result','action_completed')
                      AND node_id LIKE %s
                      AND lower(status) IN ('completed','success')
                      AND result IS NOT NULL AND result != '{}' 
                      AND NOT (result::text LIKE '%%"skipped": true%%')
                      AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                    ORDER BY timestamp
                    """,
                    (execution_id, step_name, f"{execution_id}-step-%-iter-%")
                )
                rows = await cur.fetchall()
        results: List[Any] = []
        final_evaluation_results: List[Any] = []
        
        for rr in rows or []:
            val = rr.get('result')
            try:
                import json
                parsed = json.loads(val) if isinstance(val, str) else val
            except Exception:
                parsed = val
            if isinstance(parsed, dict) and 'data' in parsed:
                parsed = parsed['data']
            if parsed is not None:
                results.append(parsed)
        
        # Filter for final evaluation results: objects that have exactly city, max_temp, alert
        # and max_temp > 0 (to exclude invalid/incomplete evaluations)
        seen_cities = set()
        for result in results:
            if (isinstance(result, dict) and 
                'city' in result and 'max_temp' in result and 'alert' in result and
                len(result) == 3 and  # Only these 3 fields
                isinstance(result.get('max_temp'), (int, float)) and
                result.get('max_temp', 0) > 0):  # Valid temperature
                
                city_name = result.get('city')
                if city_name and city_name not in seen_cities:
                    seen_cities.add(city_name)
                    final_evaluation_results.append(result)
        
        # If no final results found, try a broader match (for backward compatibility)
        if not final_evaluation_results:
            seen_cities = set()
            for result in results:
                if (isinstance(result, dict) and 
                    'city' in result and 'max_temp' in result and 'alert' in result):
                    
                    city_name = result.get('city')
                    if city_name and city_name not in seen_cities:
                        seen_cities.add(city_name)
                        final_evaluation_results.append(result)
        
        return {"status": "ok", "results": final_evaluation_results, "count": len(final_evaluation_results), "method": "legacy_content_filter", "debug": {"total_raw": len(results), "filtered": len(final_evaluation_results)}}
    except Exception as e:
        logger.exception(f"AGGREGATE.API: Failed to fetch loop results: {e}")
        raise HTTPException(status_code=500, detail=str(e))
