"""
Event log storage DAO.
"""

from __future__ import annotations

from typing import Any
from noetl.core.common import get_async_db_connection


class EventLogDAO:
    async def get_statuses(self, execution_id: Any) -> list[str]:
        statuses: list[str] = []
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT status FROM event_log WHERE execution_id = %s",
                    (execution_id,),
                )
                rows = await cur.fetchall() or []
                for r in rows:
                    try:
                        statuses.append(str(r[0]) if not isinstance(r, dict) else str(r.get("status")))
                    except Exception:
                        pass
        return statuses

    async def get_earliest_context(self, execution_id: Any) -> Any | None:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT context FROM event_log
                    WHERE execution_id = %s
                    ORDER BY timestamp ASC
                    LIMIT 1
                    """,
                    (execution_id,),
                )
                row = await cur.fetchone()
                if not row:
                    return None
                return row[0] if not isinstance(row, dict) else row.get("context")

    async def get_all_node_results(self, execution_id: Any) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT node_name, result
                    FROM event_log
                    WHERE execution_id = %s
                    ORDER BY timestamp
                    """,
                    (execution_id,),
                )
                rows = await cur.fetchall() or []
                for r in rows:
                    if isinstance(r, dict):
                        out.append((r.get("node_name"), r.get("result")))
                    else:
                        out.append((r[0], r[1] if len(r) > 1 else None))
        return out

    async def count_loop_iterations(self, execution_id: Any, step_name: str) -> int:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT COUNT(*) FROM noetl.event_log
                    WHERE execution_id = %s
                      AND event_type = 'loop_iteration'
                      AND node_name = %s
                    """,
                    (execution_id, step_name),
                )
                row = await cur.fetchone()
                return int(row[0]) if row else 0

    async def count_completed_iterations_with_child(self, execution_id: Any, step_name: str) -> int:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT COUNT(*) FROM noetl.event_log
                    WHERE execution_id = %s
                      AND event_type = 'action_completed'
                      AND node_name = %s
                      AND context LIKE '%%child_execution_id%%'
                    """,
                    (execution_id, step_name),
                )
                row = await cur.fetchone()
                return int(row[0]) if row else 0

    async def fetch_action_completed_results_for_loop(self, execution_id: Any, step_name: str) -> list[Any]:
        results: list[Any] = []
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT result FROM noetl.event_log
                    WHERE execution_id = %s
                      AND event_type = 'action_completed'
                      AND node_name = %s
                      AND context LIKE '%%child_execution_id%%'
                    ORDER BY timestamp
                    """,
                    (execution_id, step_name),
                )
                rows = await cur.fetchall() or []
                for r in rows:
                    val = r[0] if not isinstance(r, dict) else r.get("result")
                    results.append(val)
        return results

    async def list_child_executions_for_parent(self, parent_execution_id: Any) -> list[tuple[str, str | None, str | None]]:
        out: list[tuple[str, str | None, str | None]] = []
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT DISTINCT 
                        (context::json)->>'child_execution_id' as child_exec_id,
                        node_name as parent_step,
                        node_id as iter_node_id
                    FROM noetl.event_log 
                    WHERE execution_id = %s 
                      AND event_type = 'loop_iteration'
                      AND context::text LIKE '%%child_execution_id%%'
                    """,
                    (parent_execution_id,),
                )
                for row in (await cur.fetchall() or []):
                    if isinstance(row, dict):
                        out.append((row.get("child_exec_id"), row.get("parent_step"), row.get("iter_node_id")))
                    else:
                        out.append((row[0], row[1] if len(row) > 1 else None, row[2] if len(row) > 2 else None))
        return out

    async def has_execution_start(self, execution_id: Any) -> bool:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT 1 FROM noetl.event_log 
                    WHERE execution_id = %s 
                      AND event_type = 'execution_start'
                    LIMIT 1
                    """,
                    (execution_id,),
                )
                return (await cur.fetchone()) is not None

    async def parent_has_action_completed_for_child(self, parent_execution_id: Any, child_exec_id: Any) -> bool:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT 1 FROM noetl.event_log 
                    WHERE execution_id = %s 
                      AND event_type = 'action_completed'
                      AND context::text LIKE %s
                    LIMIT 1
                    """,
                    (parent_execution_id, f'%"child_execution_id": "{child_exec_id}"%'),
                )
                return (await cur.fetchone()) is not None

    async def fetch_latest_meaningful_result_for_execution(self, execution_id: Any) -> Any | None:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Try action_completed first
                await cur.execute(
                    """
                    SELECT result FROM noetl.event_log
                    WHERE execution_id = %s 
                      AND event_type IN ('result','action_completed')
                      AND result IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (execution_id,),
                )
                row = await cur.fetchone()
                if row:
                    return row[0] if not isinstance(row, dict) else row.get("result")
        return None
    async def insert_event(
        self,
        execution_id: Any,
        event_id: Any,
        parent_event_id: Any,
        parent_execution_id: Any,
        event_type: Any,
        node_id: Any,
        node_name: Any,
        node_type: Any,
        status: Any,
        duration: Any,
        context_json: Any,
        result_json: Any,
        metadata_json: Any,
        error_text: Any,
        trace_component_json: Any,
        loop_id: Any,
        loop_name: Any,
        iterator_json: Any,
        current_index: Any,
        current_item_json: Any,
    ) -> None:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO event_log (
                        execution_id, event_id, parent_event_id, parent_execution_id, timestamp, event_type,
                        node_id, node_name, node_type, status, duration,
                        context, result, metadata, error, trace_component,
                        loop_id, loop_name, iterator, current_index, current_item
                    ) VALUES (
                        %s, %s, %s, %s, CURRENT_TIMESTAMP, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s,
                        %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (execution_id, event_id) DO NOTHING
                    """,
                    (
                        execution_id,
                        event_id,
                        parent_event_id,
                        parent_execution_id,
                        event_type,
                        node_id,
                        node_name,
                        node_type,
                        status,
                        duration,
                        context_json,
                        result_json,
                        metadata_json,
                        error_text,
                        trace_component_json,
                        loop_id,
                        loop_name,
                        iterator_json,
                        current_index,
                        current_item_json,
                    ),
                )
                try:
                    await conn.commit()
                except Exception:
                    pass
