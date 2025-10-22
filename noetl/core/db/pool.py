# db/pool.py
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row, DictRow
import asyncio
from typing import Optional

_pool: Optional[AsyncConnectionPool] = None
_lock = asyncio.Lock()


async def init_pool(conninfo: str):
    """
    Initialize the global AsyncConnectionPool with dict_row as default.
    Safe to call multiple times.
    """
    global _pool
    async with _lock:
        if _pool is None:
            _pool = AsyncConnectionPool(
                conninfo,
                min_size=2,
                max_size=10,
                timeout=10,
                kwargs={"row_factory": dict_row},
                name="noetl_server",
                open=False
            )
            await _pool.open(wait=True)


def get_pool() -> AsyncConnectionPool[AsyncConnection[DictRow]]:
    """Return AsyncConnectionPool with dict_row as default pool instance."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call init_pool() first.")
    return _pool


async def close_pool():
    """Close and reset the global connection pool."""
    global _pool
    async with _lock:
        if _pool is not None:
            await _pool.close()
            _pool = None


# async def insert_log(event: str):
#     """Insert a log entry into the logs table."""
#     async with get_pool().connection() as conn:
#         async with conn.transaction():
#             await conn.execute(
#                 "INSERT INTO logs (event) VALUES (%(event)s)",
#                 {"event": event},
#             )

# async def get_events_test():
#     """Get test events from the database."""
#     async with get_pool().connection() as conn:
#         resp = await conn.execute("""
#                 WITH latest_events AS (
#                     SELECT 
#                         execution_id,
#                         MAX(created_at) as latest_timestamp
#                     FROM noetl.event
#                     GROUP BY execution_id
#                 )
#                 SELECT 
#                     e.execution_id,
#                     e.catalog_id,
#                     e.event_type,
#                     e.status,
#                     e.created_at,
#                     e.meta,
#                     e.context,
#                     e.result,
#                     e.error,
#                     e.stack_trace,
#                     c.path,
#                     c.version
#                 FROM noetl.event e
#                 JOIN latest_events le ON e.execution_id = le.execution_id AND e.created_at = le.latest_timestamp
#                 JOIN noetl.catalog c on c.catalog_id = e.catalog_id
#                 ORDER BY e.created_at desc
#             """)
#         return await resp.fetchall()

# if __name__ == "__main__":
#     async def main():
#         await init_pool("dbname=demo_noetl user=demo password=demo host=localhost port=54321")
#         events = await get_events_test()
#         for event in events:
#             print(event)
#         await close_pool()

#     asyncio.run(main())