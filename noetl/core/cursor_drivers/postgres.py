"""Postgres cursor driver.

Uses ``UPDATE ... FROM (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING`` patterns to atomically claim one work row per call.  The
caller supplies the full claim statement (flexible enough to support
re-queueing, retry counters, partitioning columns, etc.).

Connection pools are shared per (credential, process) via a module-level
registry so N cursor_worker commands running in the same worker pod
don't each open an independent pool (which blew past Postgres's
max_connections cap when N was ~500 across 5 cursor loops × 100 slots).
Each pool still sizes up with max_in_flight concurrency, but once only
— not once per worker slot.
"""
from __future__ import annotations

import asyncio
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


# Shared pool registry keyed by (dsn-string, target-loop-id).  Keying on
# the connection DSN means all cursor workers pointing at the same auth
# target land on one pool in this process.  Each pod has its own process
# (= its own registry), so the pool cap is replicated per pod, not per
# worker slot.
_shared_pools: dict[tuple[str, int], AsyncConnectionPool] = {}
_shared_pools_lock = asyncio.Lock()


async def _get_shared_pool(conn_string: str, max_size: int) -> AsyncConnectionPool:
    """Return (or lazily create) a shared pool for this DSN in this loop.

    The event-loop id is part of the key so tests / ad-hoc scripts that
    create a fresh loop get a fresh pool instead of inheriting one bound
    to a closed loop.
    """
    loop = asyncio.get_running_loop()
    key = (conn_string, id(loop))
    async with _shared_pools_lock:
        pool = _shared_pools.get(key)
        if pool is None:
            pool = AsyncConnectionPool(
                conn_string,
                min_size=1,
                max_size=max(2, max_size),
                open=False,
                name="noetl-cursor-shared",
            )
            await pool.open(wait=True, timeout=30.0)
            _shared_pools[key] = pool
        else:
            # Grow the pool if a later caller needs more concurrency.
            current_max = pool.max_size
            if max_size > current_max:
                pool.max_size = max_size
        return pool


@dataclass
class _Handle:
    pool: AsyncConnectionPool
    claim_sql: str
    options: dict[str, Any]


class PostgresCursorDriver:
    """Postgres implementation of the :class:`CursorDriver` protocol."""

    kind = "postgres"

    async def open(self, auth: Any, spec: dict[str, Any]) -> _Handle:
        """Attach to the shared pool for this credential in this process.

        ``auth`` is the credential record (dict) resolved by the caller
        via ``fetch_credential_by_key``.  Multiple cursor workers against
        the same credential share one pool; the pool's ``max_size`` is
        bumped up to the caller's concurrency hint (``options.pool_size``,
        defaulting to a conservative 8) rather than multiplied by the
        number of workers.
        """
        conn_string = _build_conn_string(auth)
        options = dict(spec.get("options") or {})
        pool_size = int(options.get("pool_size") or 8)
        pool = await _get_shared_pool(conn_string, pool_size)
        return _Handle(
            pool=pool,
            claim_sql=spec["claim"],
            options=options,
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
        # Pool is shared across workers; do NOT close it here.  The pool
        # lives for the lifetime of the worker process and is torn down
        # only on process exit.
        return


# Register at import time; importing the package picks this up.
register_driver("postgres", PostgresCursorDriver())
