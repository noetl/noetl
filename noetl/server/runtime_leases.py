from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from psycopg.rows import dict_row
from psycopg.types.json import Json

from noetl.core.common import get_snowflake_id
from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

_RUNTIME_LEASE_KIND = "server_control"


def load_control_lease_seconds() -> float:
    return max(
        5.0,
        float(os.getenv("NOETL_SERVER_CONTROL_LEASE_SECONDS", "30")),
    )


@dataclass
class RuntimeLeaseState:
    acquired: bool
    owner_instance: Optional[str] = None


class RuntimeLease:
    """
    Runtime-table-backed lease for singleton server loops.

    Multiple API instances may be live at once. Each instance heartbeats its own
    `server_api` runtime row, and singleton control loops coordinate through a
    dedicated `server_control` row keyed by task name.
    """

    def __init__(
        self,
        *,
        task_name: str,
        instance_name: str,
        server_url: str,
        hostname: str,
        logical_name: str,
        lease_seconds: float,
    ) -> None:
        self.task_name = str(task_name)
        self.instance_name = str(instance_name)
        self.server_url = str(server_url)
        self.hostname = str(hostname)
        self.logical_name = str(logical_name)
        self.lease_seconds = max(5.0, float(lease_seconds))
        self.lease_name = f"{self.logical_name}:{self.task_name}"

    async def try_acquire_or_renew(self) -> RuntimeLeaseState:
        runtime_payload = {
            "type": "server_control",
            "task": self.task_name,
            "owner_instance": self.instance_name,
            "logical_name": self.logical_name,
            "hostname": self.hostname,
            "lease_seconds": self.lease_seconds,
        }

        async with get_pool_connection(timeout=3.0) as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.runtime (
                        runtime_id,
                        name,
                        kind,
                        uri,
                        status,
                        labels,
                        capacity,
                        runtime,
                        heartbeat,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        'ready',
                        %s,
                        NULL,
                        %s,
                        now(),
                        now(),
                        now()
                    )
                    ON CONFLICT (kind, name)
                    DO UPDATE SET
                        uri = EXCLUDED.uri,
                        status = EXCLUDED.status,
                        labels = EXCLUDED.labels,
                        runtime = EXCLUDED.runtime,
                        heartbeat = now(),
                        updated_at = now()
                    WHERE
                        (
                            noetl.runtime.heartbeat < (
                                now() - make_interval(secs => %s)
                            )
                            OR noetl.runtime.runtime->>'owner_instance' = EXCLUDED.runtime->>'owner_instance'
                        )
                    RETURNING runtime
                    """,
                    (
                        get_snowflake_id(),
                        self.lease_name,
                        _RUNTIME_LEASE_KIND,
                        self.server_url,
                        Json(
                            [
                                f"task:{self.task_name}",
                                f"logical:{self.logical_name}",
                            ]
                        ),
                        Json(runtime_payload),
                        self.lease_seconds,
                    ),
                )
                row = await cur.fetchone()
                await conn.commit()

                if row:
                    runtime_data = row.get("runtime") or {}
                    return RuntimeLeaseState(
                        acquired=True,
                        owner_instance=runtime_data.get("owner_instance") or self.instance_name,
                    )

        owner = await self.get_owner_instance()
        return RuntimeLeaseState(acquired=False, owner_instance=owner)

    async def get_owner_instance(self) -> Optional[str]:
        async with get_pool_connection(timeout=3.0) as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT runtime
                    FROM noetl.runtime
                    WHERE kind = %s AND name = %s
                    LIMIT 1
                    """,
                    (_RUNTIME_LEASE_KIND, self.lease_name),
                )
                row = await cur.fetchone()
                runtime_data = (row or {}).get("runtime") or {}
                return runtime_data.get("owner_instance")

    async def release(self) -> None:
        try:
            async with get_pool_connection(timeout=3.0) as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        UPDATE noetl.runtime
                        SET status = 'offline', updated_at = now()
                        WHERE kind = %s
                          AND name = %s
                          AND runtime->>'owner_instance' = %s
                        """,
                        (_RUNTIME_LEASE_KIND, self.lease_name, self.instance_name),
                    )
                    await conn.commit()
        except Exception as exc:
            logger.warning(
                "[LEASE] Failed to release task=%s owner=%s error=%s",
                self.task_name,
                self.instance_name,
                exc,
            )
