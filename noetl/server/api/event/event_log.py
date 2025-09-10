from __future__ import annotations

from typing import Any
from noetl.core.common import get_async_db_connection


class EventLog:
    async def get_statuses(self, execution_id: Any):
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT status FROM noetl.event_log
                    WHERE execution_id = %s
                    ORDER BY timestamp
                    """,
                    (execution_id,),
                )
                rows = await cur.fetchall()
                return [r[0] for r in rows]

    async def get_earliest_context(self, execution_id: Any):
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT context FROM noetl.event_log
                    WHERE execution_id = %s
                    ORDER BY timestamp ASC
                    LIMIT 1
                    """,
                    (execution_id,),
                )
                row = await cur.fetchone()
                return row[0] if row else None

    async def get_all_node_results(self, execution_id: Any):
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT node_name, result FROM noetl.event_log
                    WHERE execution_id = %s AND result IS NOT NULL AND result != '{}' AND result != 'null'
                    ORDER BY timestamp ASC
                    """,
                    (execution_id,),
                )
                rows = await cur.fetchall()
                out = {}
                for node_name, result in rows:
                    out[node_name] = result
                return out

    async def count_loop_iterations(self, execution_id: Any, step_name: str):
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT COUNT(*) FROM noetl.event_log
                    WHERE execution_id = %s
                      AND event_type = 'result'
                      AND node_name = %s
                      AND context::text LIKE '%"loop_completed": true%'
                    """,
                    (execution_id, step_name),
                )
                row = await cur.fetchone()
                return int(row[0]) if row else 0

    async def count_completed_iterations_with_child(self, execution_id: Any, step_name: str):
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT COUNT(*) FROM noetl.event_log
                    WHERE execution_id = %s
                      AND event_type = 'action_completed'
                      AND node_name = %s
                      AND context::text LIKE '%"distributed": true%'
                      AND context::text LIKE '%"child_execution_id":%'
                    """,
                    (execution_id, step_name),
                )
                row = await cur.fetchone()
                return int(row[0]) if row else 0

    async def fetch_action_completed_results_for_loop(self, execution_id: Any, step_name: str):
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT result FROM noetl.event_log
                    WHERE execution_id = %s
                      AND event_type = 'action_completed'
                      AND node_name = %s
                      AND result IS NOT NULL AND result != '{}' AND result != 'null'
                    ORDER BY timestamp ASC
                    """,
                    (execution_id, step_name),
                )
                rows = await cur.fetchall()
                return [r[0] for r in rows]

    async def list_child_executions_for_parent(self, parent_execution_id: Any):
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT DISTINCT execution_id
                    FROM noetl.event_log
                    WHERE metadata LIKE %s
                    """,
                    (f'%"parent_execution_id": "{parent_execution_id}"%',),
                )
                rows = await cur.fetchall()
                return [r[0] for r in rows]

    async def has_execution_start(self, execution_id: Any):
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT 1 FROM noetl.event_log
                    WHERE execution_id = %s AND event_type IN ('execution_start','execution_started')
                    LIMIT 1
                    """,
                    (execution_id,),
                )
                row = await cur.fetchone()
                return bool(row)

    async def parent_has_action_completed_for_child(self, parent_execution_id: Any, child_exec_id: Any):
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
                row = await cur.fetchone()
                return bool(row)

    async def fetch_latest_meaningful_result_for_execution(self, execution_id: Any):
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT result FROM noetl.event_log
                    WHERE execution_id = %s
                      AND result IS NOT NULL AND result != '{}' AND result != 'null'
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (execution_id,),
                )
                row = await cur.fetchone()
                return row[0] if row else None

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
    ):
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.event_log (
                        execution_id, event_id, parent_event_id, parent_execution_id, event_type,
                        node_id, node_name, node_type, status, duration, context, result,
                        metadata, error, trace_component, loop_id, loop_name, iterator,
                        current_index, current_item
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s
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
