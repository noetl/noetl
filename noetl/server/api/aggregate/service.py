"""
NoETL Aggregate API Service - Business logic for aggregate operations.

Handles:
- Loop iteration result aggregation from event log
- Event-sourced data retrieval
- Result filtering and deduplication
"""

from typing import Any, Dict, List, Set
import json
from psycopg.rows import dict_row
from noetl.core.common import get_async_db_connection
from noetl.core.logger import setup_logger
from .schema import LoopIterationResultsResponse

logger = setup_logger(__name__, include_location=True)


class AggregateService:
    """Service for aggregating execution results from event log."""
    
    @staticmethod
    async def get_loop_iteration_results(
        execution_id: str,
        step_name: str
    ) -> LoopIterationResultsResponse:
        """
        Get the list of per-iteration results for a given execution and loop step.
        
        This method sources data from event log only (event-sourced server side),
        avoiding any worker-side DB access. Uses generic loop metadata fields
        for robust filtering instead of content-specific logic.
        
        Args:
            execution_id: The execution ID
            step_name: The loop step name
            
        Returns:
            LoopIterationResultsResponse with iteration results
        """
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
                    FROM noetl.event
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
                    ORDER BY current_index, created_at
                    """,
                    (execution_id, step_name)
                )
                metadata_rows = await cur.fetchall()
                
                # If we found results using metadata, use them
                if metadata_rows:
                    logger.info(
                        f"AGGREGATE: Found {len(metadata_rows)} results using loop metadata "
                        f"for {execution_id}:{step_name}"
                    )
                    results = AggregateService._parse_results(metadata_rows)
                    return LoopIterationResultsResponse(
                        status="ok",
                        results=results,
                        count=len(results),
                        method="loop_metadata"
                    )
                
                # Fallback to legacy content-based filtering if metadata approach fails
                logger.warning(
                    f"AGGREGATE: No results found using loop metadata, "
                    f"falling back to legacy filtering for {execution_id}:{step_name}"
                )
                await cur.execute(
                    """
                    SELECT result FROM noetl.event
                    WHERE execution_id = %s
                      AND node_name = %s
                      AND event_type IN ('result','action_completed')
                      AND node_id LIKE %s
                      AND lower(status) IN ('completed','success')
                      AND result IS NOT NULL AND result != '{}' 
                      AND NOT (result::text LIKE '%%"skipped": true%%')
                      AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                    ORDER BY created_at
                    """,
                    (execution_id, step_name, f"{execution_id}-step-%-iter-%")
                )
                rows = await cur.fetchall()
        
        # Parse and filter results using legacy logic
        results = AggregateService._parse_results(rows or [])
        final_evaluation_results = AggregateService._filter_final_evaluation_results(results)
        
        return LoopIterationResultsResponse(
            status="ok",
            results=final_evaluation_results,
            count=len(final_evaluation_results),
            method="legacy_content_filter",
            debug={
                "total_raw": len(results),
                "filtered": len(final_evaluation_results)
            }
        )
    
    @staticmethod
    def _parse_results(rows: List[Dict[str, Any]]) -> List[Any]:
        """
        Parse result field from database rows.
        
        Args:
            rows: List of database rows containing 'result' field
            
        Returns:
            List of parsed results
        """
        results: List[Any] = []
        for row in rows:
            val = row.get('result')
            try:
                parsed = json.loads(val) if isinstance(val, str) else val
            except Exception:
                parsed = val
            
            # Extract data field if present
            if isinstance(parsed, dict) and 'data' in parsed:
                parsed = parsed['data']
            
            if parsed is not None:
                results.append(parsed)
        
        return results
    
    @staticmethod
    def _filter_final_evaluation_results(results: List[Any]) -> List[Any]:
        """
        Filter for final evaluation results with specific structure.
        
        This legacy filtering logic looks for results with city, max_temp, and alert
        fields, deduplicating by city name. This is backward compatibility logic
        for specific use cases.
        
        Args:
            results: List of parsed results
            
        Returns:
            List of filtered results
        """
        final_evaluation_results: List[Any] = []
        seen_cities: Set[str] = set()
        
        # First pass: strict filtering (exactly 3 fields, valid temperature)
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
        
        # Second pass: broader match if no results found (backward compatibility)
        if not final_evaluation_results:
            seen_cities = set()
            for result in results:
                if (isinstance(result, dict) and 
                    'city' in result and 'max_temp' in result and 'alert' in result):
                    
                    city_name = result.get('city')
                    if city_name and city_name not in seen_cities:
                        seen_cities.add(city_name)
                        final_evaluation_results.append(result)
        
        return final_evaluation_results
