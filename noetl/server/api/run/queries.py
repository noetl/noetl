"""
Query builder and data access layer for orchestrator operations.

Provides centralized SQL query construction and execution
following the pattern from catalog/service.py.
"""
from typing import Dict, Any, List, Optional, Tuple
from psycopg.rows import dict_row
from noetl.core.db.pool import get_pool_connection


class OrchestratorQueries:
    """SQL query builder and executor for orchestration operations."""
    
    # ==================== Query Builder ====================
    
    @staticmethod
    def _build_event_check_query(
        execution_id: int,
        event_type: Optional[str] = None,
        event_types: Optional[List[str]] = None,
        status_filter: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Build query to check for events with various conditions.
        
        Args:
            execution_id: Execution ID to check
            event_type: Single event type to match
            event_types: Multiple event types to match (OR condition)
            status_filter: Status pattern to match (uses LIKE with %%)
        """
        params = {"execution_id": execution_id}
        clauses = ["execution_id = %(execution_id)s"]
        
        if event_type:
            clauses.append("event_type = %(event_type)s")
            params["event_type"] = event_type
        elif event_types:
            placeholders = [f"%(event_type_{i})s" for i in range(len(event_types))]
            clauses.append(f"event_type IN ({', '.join(placeholders)})")
            for i, et in enumerate(event_types):
                params[f"event_type_{i}"] = et
        
        if status_filter:
            clauses.append("(LOWER(status) LIKE %(status_pattern)s OR event_type = 'error')")
            params["status_pattern"] = f"%{status_filter.lower()}%"
        
        query = f"SELECT 1 FROM noetl.event WHERE {' AND '.join(clauses)} LIMIT 1"
        return query, params
    
    # ==================== Public Query Executors ====================
    
    @staticmethod
    async def has_execution_failed(execution_id: int) -> bool:
        """
        Check if execution has permanently failed (not recoverable by retry).
        
        Returns True only if there's a failure event AND no successful action_completed
        event after the failure. This allows retries to succeed and continue the workflow.
        """
        query = """
            WITH failure_time AS (
                SELECT MAX(created_at) as last_failure
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('playbook.failed', 'workflow.failed')
            ),
            success_after_failure AS (
                SELECT COUNT(*) as success_count
                FROM noetl.event e, failure_time f
                WHERE e.execution_id = %(execution_id)s
                  AND e.event_type = 'action_completed'
                  AND e.created_at > f.last_failure
            )
            SELECT 
                CASE 
                    WHEN (SELECT last_failure FROM failure_time) IS NULL THEN FALSE
                    WHEN (SELECT success_count FROM success_after_failure) > 0 THEN FALSE
                    ELSE TRUE
                END as has_failed
        """
        params = {"execution_id": execution_id}
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
                return row["has_failed"] if row else False
    
    @staticmethod
    async def has_workflow_initialized(execution_id: int) -> bool:
        """Check if workflow has been initialized."""
        query, params = OrchestratorQueries._build_event_check_query(
            execution_id=execution_id,
            event_type="workflow_initialized"
        )
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, params)
                return await cur.fetchone() is not None
    
    @staticmethod
    async def has_pending_queue_jobs(execution_id: int) -> bool:
        """Queue subsystem removed; always report no pending queue jobs."""
        return False
    
    @staticmethod
    async def count_completed_steps(execution_id: int) -> int:
        """Count number of completed steps."""
        query = """
            SELECT COUNT(DISTINCT node_name) as count
            FROM noetl.event
            WHERE execution_id = %(execution_id)s
              AND event_type = 'step_completed'
        """
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, {"execution_id": execution_id})
                result = await cur.fetchone()
                return result['count'] if result else 0
    
    @staticmethod
    async def get_completed_steps_without_step_completed(execution_id: int) -> List[str]:
        """
        Get steps with action_completed (v1) or command.completed (v2) but no step_completed event.
        
        This includes:
        1. Normal successful steps without step_completed
        2. Retried steps that succeeded after initial failure (have action_completed after step_failed)
        """
        query = """
            SELECT DISTINCT node_name
            FROM noetl.event
            WHERE execution_id = %(execution_id)s
              AND event_type IN ('action_completed', 'command.completed')
              AND node_name NOT IN (
                  SELECT node_name FROM noetl.event
                  WHERE execution_id = %(execution_id)s AND event_type = 'step_completed'
              )
        """
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, {"execution_id": execution_id})
                rows = await cur.fetchall()
                return [row["node_name"] for row in rows]
    
    @staticmethod
    async def get_execution_metadata(execution_id: int) -> Optional[Dict[str, Any]]:
        """Get execution metadata from playbook_started event."""
        query = """
            SELECT meta FROM noetl.event
            WHERE execution_id = %(execution_id)s
              AND event_type = 'playbook_started'
            ORDER BY created_at LIMIT 1
        """
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, {"execution_id": execution_id})
                row = await cur.fetchone()
                return row["meta"] if row else None
    
    @staticmethod
    async def get_transitions(execution_id: int) -> List[Dict[str, Any]]:
        """Get all workflow transitions for execution."""
        query = """
            SELECT from_step, to_step, condition, with_params
            FROM noetl.transition
            WHERE execution_id = %(execution_id)s
        """
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, {"execution_id": execution_id})
                return await cur.fetchall()
    
    @staticmethod
    async def get_step_results(execution_id: int) -> List[Dict[str, Any]]:
        """Get all step results for evaluation context."""
        query = """
            SELECT node_name, result
            FROM noetl.event
            WHERE execution_id = %(execution_id)s
              AND event_type IN ('action_completed', 'step_result')
              AND result IS NOT NULL
            ORDER BY created_at
        """
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, {"execution_id": execution_id})
                return await cur.fetchall()
    
    @staticmethod
    async def get_action_completed_meta(execution_id: int, node_name: str) -> Optional[Dict[str, Any]]:
        """Get meta from action_completed (v1) or command.completed (v2) event for parent_event_id extraction."""
        query = """
            SELECT meta
            FROM noetl.event
            WHERE execution_id = %(execution_id)s
              AND node_name = %(node_name)s
              AND event_type IN ('action_completed', 'command.completed')
            ORDER BY created_at DESC
            LIMIT 1
        """
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, {"execution_id": execution_id, "node_name": node_name})
                row = await cur.fetchone()
                return row["meta"] if row else None
