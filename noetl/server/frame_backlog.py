"""Frame backlog provider for runtime metrics and autoscaling signals."""

from __future__ import annotations

from typing import Any

from noetl.core.common import get_async_db_connection


async def collect_frame_backlog_snapshot() -> list[dict[str, Any]]:
    """Return worker-claimable frame backlog grouped by stage kind and status.

    This is the NoETL runtime boundary used by metrics and autoscaling. The
    current adapter reads the projection store; callers should not depend on
    the storage engine or query shape.
    """
    async with get_async_db_connection(optional=True) as conn:
        if conn is None:
            return []
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT s.kind AS stage_kind, f.status, COUNT(*)::int AS count
                FROM noetl.frame f
                JOIN noetl.stage s ON s.stage_id = f.stage_id
                WHERE f.status IN ('PENDING','CLAIMED','RUNNING')
                GROUP BY s.kind, f.status
                ORDER BY s.kind, f.status
                """
            )
            return [
                {
                    "stage_kind": row[0],
                    "status": row[1],
                    "count": row[2],
                }
                for row in await cur.fetchall()
            ]


__all__ = ["collect_frame_backlog_snapshot"]
