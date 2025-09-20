"""
Server-side BrokerService for post-persist analysis and loop aggregation triggers.

Moved from legacy noetl/broker.py to keep all server orchestration under noetl.api.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import asyncio as _asyncio
from noetl.core.logger import setup_logger


logger = setup_logger(__name__, include_location=True)


class BrokerService:
    def __init__(self) -> None:
        pass

    async def analyze_execution(self, execution_id: str | int) -> None:
        try:
            # Import from the canonical server API package to avoid aliasing issues
            from noetl.api.routers.event import evaluate_broker_for_execution
            await evaluate_broker_for_execution(str(execution_id))
        except Exception:
            logger.debug("BROKER_SERVICE: analyze_execution failed", exc_info=True)

    def on_event_persisted(self, event_data: Dict[str, Any]) -> None:
        try:
            execution_id = event_data.get("execution_id")
            if not execution_id:
                return
            # If we received a loop_completed marker, enqueue a result aggregation job for this step
            try:
                evt_type = str(event_data.get('event_type') or '').lower()
                if evt_type == 'loop_completed':
                    step_name = event_data.get('node_name') or event_data.get('step_name')
                    ctx = event_data.get('context') or event_data.get('input_context') or {}
                    if step_name:
                        from noetl.core.common import get_pgdb_connection
                        import json as _json
                        with get_pgdb_connection() as _conn:
                            with _conn.cursor() as _cur:
                                # Avoid duplicates: check if a queued/leased/done result_aggregation job exists for this step
                                _cur.execute(
                                    """
                                    SELECT COUNT(*) FROM noetl.queue
                                    WHERE execution_id = %s
                                      AND (action->>'type') = 'result_aggregation'
                                      AND (context::jsonb ->> 'step_name') = %s
                                      AND status IN ('queued','leased','done')
                                    """,
                                    (execution_id, step_name)
                                )
                                _row = _cur.fetchone()
                                # Also ensure no final aggregated action_completed exists already
                                _cur.execute(
                                    """
                                    SELECT COUNT(*) FROM noetl.event
                                    WHERE execution_id = %s
                                      AND event_type = 'action_completed'
                                      AND node_name = %s
                                      AND context::text LIKE '%%loop_completed%%'
                                      AND context::text LIKE '%%true%%'
                                    """,
                                    (execution_id, step_name)
                                )
                                _logrow = _cur.fetchone()
                                if (not _row or int(_row[0]) == 0) and (not _logrow or int(_logrow[0]) == 0):
                                    action = {"type": "result_aggregation"}
                                    ic = {"step_name": step_name, "loop_step_name": step_name, "total_iterations": (ctx.get('total_iterations') if isinstance(ctx, dict) else None)}
                                    _cur.execute(
                                        """
                                        INSERT INTO noetl.queue (execution_id, node_id, action, context, priority, max_attempts, available_at)
                                        VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                                        ON CONFLICT (execution_id, node_id) DO NOTHING
                                        RETURNING id
                                        """,
                                        (execution_id, f"{execution_id}-result-agg-{step_name}", _json.dumps(action), _json.dumps(ic), 5, 3)
                                    )
                                    _conn.commit()
                                    logger.info(f"BROKER_SERVICE: Enqueued result_aggregation job for {execution_id}/{step_name}")
            except Exception:
                logger.debug("BROKER_SERVICE: failed to enqueue result aggregation job", exc_info=True)
            # If execution already completed, skip further analysis
            try:
                from noetl.core.common import get_pgdb_connection as _get_conn
                with _get_conn() as __conn:
                    with __conn.cursor() as __cur:
                        __cur.execute(
                            """
                            SELECT 1 FROM noetl.event
                            WHERE execution_id = %s AND event_type = 'execution_completed'
                            LIMIT 1
                            """,
                            (execution_id,)
                        )
                        if __cur.fetchone():
                            return
            except Exception:
                pass
            # Always schedule an analysis, non-blocking
            try:
                loop = _asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.analyze_execution(str(execution_id)))
                else:
                    loop.run_until_complete(self.analyze_execution(str(execution_id)))
            except RuntimeError:
                try:
                    _asyncio.run(self.analyze_execution(str(execution_id)))
                except Exception:
                    logger.debug("BROKER_SERVICE: asyncio.run failed", exc_info=True)
        except Exception:
            logger.debug("BROKER_SERVICE: on_event_persisted guard failure", exc_info=True)


__broker_singleton: Optional[BrokerService] = None


def get_broker_service() -> BrokerService:
    global __broker_singleton
    if __broker_singleton is None:
        __broker_singleton = BrokerService()
    return __broker_singleton
