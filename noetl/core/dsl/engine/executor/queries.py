from __future__ import annotations

from .common import *
from .state import ExecutionState
from .store import PlaybookRepo, StateStore

class QueryMixin:
    async def _count_step_events(
        self,
        execution_id: str,
        node_name: str,
        event_type: str,
    ) -> int:
        """Count persisted events for a node/event pair (best-effort fallback path)."""
        try:
            node_names = list(_node_name_candidates(node_name))
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT COUNT(*) AS cnt
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND node_name = ANY(%s)
                          AND event_type = %s
                        """,
                        (int(execution_id), node_names, event_type),
                    )
                    row = await cur.fetchone()
                    return int((row or {}).get("cnt", 0) or 0)
        except Exception as exc:
            logger.warning(
                "[TASK_SEQ-LOOP] Failed to count %s events for %s/%s: %s",
                event_type,
                execution_id,
                node_name,
                exc,
            )
            return -1

    async def _count_persisted_command_events(
        self,
        execution_id: str,
        event_type: str,
        command_id: str,
    ) -> int:
        """Count persisted events by command_id for actionable idempotency guards."""
        try:
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT COUNT(*) AS cnt
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND event_type = %s
                          AND meta ? 'command_id'
                          AND meta->>'command_id' = %s
                        """,
                        (int(execution_id), event_type, str(command_id)),
                    )
                    row = await cur.fetchone()
                    return int((row or {}).get("cnt", 0) or 0)
        except Exception as exc:
            logger.warning(
                "[EVENT-DEDUPE] Failed to count persisted %s events for %s command_id=%s: %s",
                event_type,
                execution_id,
                command_id,
                exc,
            )
            return -1

    async def _is_first_persisted_command_event(
        self,
        execution_id: str,
        event_type: str,
        command_id: str,
        persisted_event_id: int,
    ) -> bool:
        """Return True when the provided persisted event_id is the earliest duplicate candidate."""
        try:
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT MIN(event_id) AS first_event_id
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND event_type = %s
                          AND meta ? 'command_id'
                          AND meta->>'command_id' = %s
                        """,
                        (int(execution_id), event_type, str(command_id)),
                    )
                    row = await cur.fetchone()
                    first_event_id = int((row or {}).get("first_event_id", 0) or 0)
                    return first_event_id > 0 and first_event_id == int(persisted_event_id)
        except Exception as exc:
            logger.warning(
                "[EVENT-DEDUPE] Failed to resolve first persisted %s event for %s command_id=%s event_id=%s: %s",
                event_type,
                execution_id,
                command_id,
                persisted_event_id,
                exc,
            )
            return False

    async def _count_loop_terminal_iterations(
        self,
        execution_id: str,
        node_name: str,
        loop_event_id: Optional[str],
    ) -> int:
        """Count distinct terminal loop iterations for a specific epoch."""
        if not loop_event_id:
            return -1

        node_names = list(_node_name_candidates(node_name))
        try:
            async with db_pool.get_bg_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT COUNT(DISTINCT idx.loop_iteration_index) AS cnt
                        FROM (
                            SELECT NULLIF(meta->>'loop_iteration_index', '')::int AS loop_iteration_index
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type = 'call.done'
                              AND COALESCE(meta->>'loop_event_id', meta->>'__loop_epoch_id', result->'context'->>'loop_event_id') = %s
                        ) idx
                        WHERE idx.loop_iteration_index IS NOT NULL
                        """,
                        (int(execution_id), node_names, str(loop_event_id)),
                    )
                    row = await cur.fetchone()
                    return int((row or {}).get("cnt", 0) or 0)
        except Exception as exc:
            logger.warning(
                "[LOOP-COUNTER-RECONCILE] Failed to count epoch terminals for %s/%s epoch=%s: %s",
                execution_id,
                node_name,
                loop_event_id,
                exc,
            )
            return -1

    async def _count_supervised_loop_terminal_iterations(
        self,
        execution_id: str,
        step_name: str,
        loop_event_id: Optional[str],
    ) -> int:
        """Count observed terminal loop items from supervisor state for an epoch."""
        if not loop_event_id:
            return -1

        try:
            nats_cache = await get_nats_cache()
            if hasattr(nats_cache, "count_observed_loop_iteration_terminals"):
                return await nats_cache.count_observed_loop_iteration_terminals(
                    str(execution_id),
                    step_name,
                    event_id=str(loop_event_id),
                )
        except Exception as exc:
            logger.warning(
                "[LOOP-SUPERVISOR-RECONCILE] Failed to count supervised terminals for %s/%s epoch=%s: %s",
                execution_id,
                step_name,
                loop_event_id,
                exc,
            )

        return -1

    async def _find_supervised_missing_loop_iteration_indices(
        self,
        execution_id: str,
        step_name: str,
        loop_event_id: Optional[str] = None,
        limit: int = 10,
        min_age_seconds: float = _TASKSEQ_LOOP_MISSING_MIN_AGE_SECONDS,
    ) -> Optional[list[int]]:
        """Find missing loop items from supervisor state instead of event replay."""
        if limit <= 0:
            return []

        try:
            nats_cache = await get_nats_cache()
            if hasattr(nats_cache, "find_supervisor_missing_loop_iteration_indices"):
                return await nats_cache.find_supervisor_missing_loop_iteration_indices(
                    str(execution_id),
                    step_name,
                    event_id=str(loop_event_id) if loop_event_id else None,
                    limit=int(limit),
                    min_age_seconds=float(min_age_seconds or 0.0),
                )
        except Exception as exc:
            logger.warning(
                "[LOOP-SUPERVISOR-RECONCILE] Failed to find missing supervised items for %s/%s epoch=%s: %s",
                execution_id,
                step_name,
                loop_event_id,
                exc,
            )

        return None

    async def _find_supervised_orphaned_loop_iteration_indices(
        self,
        execution_id: str,
        step_name: str,
        loop_event_id: Optional[str] = None,
        limit: int = 10,
    ) -> Optional[list[int]]:
        """Find orphaned loop items from supervisor state instead of event replay."""
        if limit <= 0:
            return []

        try:
            nats_cache = await get_nats_cache()
            if hasattr(nats_cache, "find_supervisor_orphaned_loop_iteration_indices"):
                return await nats_cache.find_supervisor_orphaned_loop_iteration_indices(
                    str(execution_id),
                    step_name,
                    event_id=str(loop_event_id) if loop_event_id else None,
                    limit=int(limit),
                )
        except Exception as exc:
            logger.warning(
                "[LOOP-SUPERVISOR-RECONCILE] Failed to find orphaned supervised items for %s/%s epoch=%s: %s",
                execution_id,
                step_name,
                loop_event_id,
                exc,
            )

        return None

    async def _find_missing_loop_iteration_indices(
        self,
        execution_id: str,
        node_name: str,
        loop_event_id: Optional[str] = None,
        limit: int = 10,
        min_age_seconds: float = _TASKSEQ_LOOP_MISSING_MIN_AGE_SECONDS,
    ) -> list[int]:
        """
        Find loop iteration indexes that were issued but never started and have no terminal event.

        Guards against false positives from healthy in-flight commands by only
        considering unstarted commands older than the minimum age threshold.
        """
        if limit <= 0:
            return []

        try:
            loop_filter = ""
            node_names = list(_node_name_candidates(node_name))
            issued_params: list[Any] = [int(execution_id), node_names]
            if loop_event_id:
                loop_filter = "AND meta->>'loop_event_id' = %s"
                issued_params.append(str(loop_event_id))

            min_age = max(0.0, float(min_age_seconds or 0.0))
            params: list[Any] = [
                *issued_params,
                int(execution_id),
                node_names,
                int(execution_id),
                node_names,
                min_age,
                int(limit),
            ]

            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        f"""
                        WITH issued AS (
                            SELECT
                                meta->>'command_id' AS command_id,
                                NULLIF(meta->>'loop_iteration_index', '')::int AS loop_iteration_index,
                                created_at AS issued_at
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type = 'command.issued'
                              {loop_filter}
                        ),
                        started AS (
                            SELECT
                                meta->>'command_id' AS command_id,
                                MAX(created_at) AS started_at
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type = 'command.started'
                              AND meta->>'command_id' IS NOT NULL
                              AND meta->>'command_id' IN (
                                    SELECT command_id FROM issued WHERE command_id IS NOT NULL
                                  )
                            GROUP BY meta->>'command_id'
                        ),
                        terminal AS (
                            SELECT DISTINCT
                                meta->>'command_id' AS command_id
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type IN ('command.completed', 'command.failed', 'command.cancelled', 'call.done')
                              AND meta->>'command_id' IS NOT NULL
                              AND meta->>'command_id' IN (
                                    SELECT command_id FROM issued WHERE command_id IS NOT NULL
                                  )
                        )
                        SELECT i.loop_iteration_index
                        FROM issued i
                        LEFT JOIN started s ON s.command_id = i.command_id
                        LEFT JOIN terminal t ON t.command_id = i.command_id
                        WHERE i.loop_iteration_index IS NOT NULL
                          AND t.command_id IS NULL
                          AND i.issued_at <= (NOW() - (%s * INTERVAL '1 second'))
                          AND s.command_id IS NULL
                        ORDER BY i.loop_iteration_index
                        LIMIT %s
                        """,
                        tuple(params),
                    )
                    rows = await cur.fetchall()

            return [
                int(row.get("loop_iteration_index"))
                for row in rows or []
                if row.get("loop_iteration_index") is not None
            ]
        except Exception as exc:
            logger.warning(
                "[TASK_SEQ-LOOP] Failed to detect missing loop iterations for %s/%s: %s",
                execution_id,
                node_name,
                exc,
            )
            return []

    async def _find_orphaned_loop_iteration_indices(
        self,
        execution_id: str,
        node_name: str,
        loop_event_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[int]:
        """Find issued loop indexes that never started and have no terminal event."""
        if limit <= 0:
            return []

        try:
            loop_filter = ""
            node_names = list(_node_name_candidates(node_name))
            issued_params: list[Any] = [int(execution_id), node_names]
            if loop_event_id:
                loop_filter = "AND meta->>'loop_event_id' = %s"
                issued_params.append(str(loop_event_id))

            params: list[Any] = [
                *issued_params,
                int(execution_id),
                node_names,
                int(execution_id),
                node_names,
                int(limit),
            ]

            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        f"""
                        WITH issued AS (
                            SELECT
                                meta->>'command_id' AS command_id,
                                NULLIF(meta->>'loop_iteration_index', '')::int AS loop_iteration_index
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type = 'command.issued'
                              {loop_filter}
                        ),
                        started AS (
                            SELECT DISTINCT
                                meta->>'command_id' AS command_id
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type = 'command.started'
                              AND meta->>'command_id' IS NOT NULL
                              AND meta->>'command_id' IN (
                                    SELECT command_id FROM issued WHERE command_id IS NOT NULL
                                  )
                        ),
                        terminal AS (
                            SELECT DISTINCT
                                meta->>'command_id' AS command_id
                            FROM noetl.event
                            WHERE execution_id = %s
                              AND node_name = ANY(%s)
                              AND event_type IN ('command.completed', 'command.failed', 'command.cancelled', 'call.done')
                              AND meta->>'command_id' IS NOT NULL
                              AND meta->>'command_id' IN (
                                    SELECT command_id FROM issued WHERE command_id IS NOT NULL
                                  )
                        )
                        SELECT i.loop_iteration_index
                        FROM issued i
                        LEFT JOIN started s ON s.command_id = i.command_id
                        LEFT JOIN terminal t ON t.command_id = i.command_id
                        WHERE i.loop_iteration_index IS NOT NULL
                          AND s.command_id IS NULL
                          AND t.command_id IS NULL
                        ORDER BY i.loop_iteration_index
                        LIMIT %s
                        """,
                        tuple(params),
                    )
                    rows = await cur.fetchall()

            return [
                int(row.get("loop_iteration_index"))
                for row in rows or []
                if row.get("loop_iteration_index") is not None
            ]
        except Exception as exc:
            logger.warning(
                "[TASK_SEQ-LOOP] Failed to detect orphaned loop iterations for %s/%s: %s",
                execution_id,
                node_name,
                exc,
            )
            return []
