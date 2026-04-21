"""Postgres cursor driver.

Uses ``UPDATE ... FROM (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING`` patterns to atomically claim one work row per call.  The
caller supplies the full claim statement (flexible enough to support
re-queueing, retry counters, partitioning columns, etc.).

Connection is pooled per-handle via psycopg_pool.AsyncConnectionPool to
keep worker-side claim latency stable across a long-running worker slot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

from noetl.core.logger import setup_logger

from . import register_driver

logger = setup_logger(__name__, include_location=True)


def _build_conn_string(credential: dict[str, Any]) -> str:
    """Build a psycopg connection string from a noetl credential record.

    Matches the existing tools/postgres/auth.py shape so operators don't
    have to learn a new credential schema for cursor loops.
    """
    host = credential.get("db_host") or credential.get("host")
    port = credential.get("db_port") or credential.get("port") or 5432
    user = credential.get("db_user") or credential.get("user")
    password = credential.get("db_password") or credential.get("password")
    dbname = credential.get("db_name") or credential.get("database") or credential.get("dbname")
    missing = [
        k for k, v in (
            ("host", host), ("user", user),
            ("password", password), ("database", dbname),
        )
        if not v
    ]
    if missing:
        raise ValueError(
            f"postgres cursor driver: credential missing {missing!r} "
            "(expected db_host/db_user/db_password/db_name)"
        )
    return (
        f"dbname={dbname} user={user} password={password} "
        f"host={host} port={port} connect_timeout=10"
    )


@dataclass
class _Handle:
    pool: AsyncConnectionPool
    claim_sql: str
    options: dict[str, Any]


class PostgresCursorDriver:
    """Postgres implementation of the :class:`CursorDriver` protocol."""

    kind = "postgres"

    async def open(self, auth: Any, spec: dict[str, Any]) -> _Handle:
        """Open a per-worker connection pool.

        ``auth`` is the credential record (dict) resolved by the caller
        via ``fetch_credential_by_key``.  The pool is scoped to the handle
        — one pool per cursor-worker command — and closed in ``close``.
        The pool has ``min_size=1, max_size=2`` since each worker only
        runs one claim at a time.
        """
        conn_string = _build_conn_string(auth)
        pool = AsyncConnectionPool(
            conn_string,
            min_size=1,
            max_size=2,
            open=False,
            name=f"cursor-{spec.get('kind', 'postgres')}",
        )
        await pool.open(wait=True, timeout=30.0)
        return _Handle(
            pool=pool,
            claim_sql=spec["claim"],
            options=dict(spec.get("options") or {}),
        )

    async def claim(
        self,
        handle: _Handle,
        context: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Execute the claim statement and return one row or None."""
        async with handle.pool.connection() as conn:
            # Autocommit per claim so the row lock is released immediately
            # once the claim-and-return round-trip finishes; the worker
            # then runs the iteration body in a separate transaction.
            await conn.set_autocommit(True)
            async with conn.cursor(row_factory=dict_row) as cur:
                # The claim SQL is rendered by the caller with worker /
                # execution context substituted in (e.g. execution_id,
                # facility_mapping_id, worker_slot_id).  Pass no params;
                # any templating belongs upstream.
                await cur.execute(handle.claim_sql)
                row = await cur.fetchone()
                return dict(row) if row else None

    async def close(self, handle: _Handle) -> None:
        try:
            await handle.pool.close()
        except Exception as exc:
            logger.warning("cursor_drivers.postgres: pool close error: %s", exc)


# Register at import time; importing the package picks this up.
register_driver("postgres", PostgresCursorDriver())
