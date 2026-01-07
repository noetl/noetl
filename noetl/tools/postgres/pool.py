"""
PostgreSQL connection pool manager for plugin executions.

This module provides a simplified interface to the core pool manager
for postgres plugin executions. All actual pooling logic is in noetl.core.db.pool.
"""
import hashlib
import asyncio
import time
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row, DictRow
from contextlib import asynccontextmanager
from typing import Dict

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)
# Re-export for backward compatibility
__all__ = [
    'get_or_create_pool',
    'get_connection',
    'close_pool',
    'close_all_pools',
    'get_pool_stats',
]

# Per-credential pool registry for plugins
_plugin_pools: Dict[str, AsyncConnectionPool[AsyncConnection[DictRow]]] = {}
_plugin_locks: Dict[str, asyncio.Lock] = {}
_plugin_global_lock = asyncio.Lock()


# ============================================================================
# Per-Credential Pool Registry (for plugin executions)
# ============================================================================

async def get_or_create_plugin_pool(
        connection_string: str,
        pool_name: str = "postgres_plugin",
        min_size: int = 2,
        max_size: int = 20,
        timeout: float = 10.0,
        max_waiting: int = 50,
        max_lifetime: float = 300.0,  # 5 minutes
        max_idle: float = 120.0,  # 2 minutes
) -> AsyncConnectionPool[AsyncConnection[DictRow]]:
    """
    Get existing pool or create new one for the connection string.

    Connection pools are cached per unique connection string to avoid
    creating multiple pools for the same database credentials.
    Used by plugins to connect to user databases.

    Args:
        connection_string: PostgreSQL connection string
        pool_name: Name prefix for the pool (for logging/monitoring)
        min_size: Minimum number of connections to maintain
        max_size: Maximum number of connections allowed
        timeout: Timeout in seconds for getting a connection
        max_waiting: Maximum number of requests waiting for a connection
        max_lifetime: Maximum lifetime of a connection in seconds
        max_idle: Maximum idle time before connection is closed

    Returns:
        AsyncConnectionPool instance

    Raises:
        Exception: If pool creation fails
    """
    # Create a hash key from connection string (without exposing password)
    pool_key = _create_pool_key(connection_string)

    # Get or create lock for this pool
    async with _plugin_global_lock:
        if pool_key not in _plugin_locks:
            _plugin_locks[pool_key] = asyncio.Lock()

    # Get or create pool with lock
    async with _plugin_locks[pool_key]:
        if pool_key not in _plugin_pools:
            logger.info(
                f"Creating new Postgres plugin pool: {pool_name} (key: {pool_key[:12]}...) | "
                f"Config: min={min_size}, max={max_size}, timeout={timeout}s, max_waiting={max_waiting}"
            )

            try:
                pool = AsyncConnectionPool(
                    connection_string,
                    min_size=min_size,
                    max_size=max_size,
                    timeout=timeout,
                    max_waiting=max_waiting,
                    max_lifetime=max_lifetime,
                    max_idle=max_idle,
                    kwargs={"row_factory": dict_row},
                    name=f"{pool_name}_{pool_key[:8]}",
                    open=False
                )

                # Open the pool and wait for minimum connections
                await pool.open(wait=True, timeout=timeout)

                _plugin_pools[pool_key] = pool
                logger.info(f"Postgres plugin pool created successfully: {pool.name}")

            except Exception as e:
                logger.error(f"Failed to create Postgres plugin pool: {e}")
                raise
        else:
            logger.debug(f"Reusing existing pool {pool_name}")

        return _plugin_pools[pool_key]


@asynccontextmanager
async def get_plugin_connection(connection_string: str, pool_name: str = "postgres_plugin"):
    """
    Get a connection from the plugin pool as an async context manager.

    This is the primary interface for plugin code to get database connections.
    Connections are automatically returned to the pool when the context exits.

    Usage:
        async with get_plugin_connection(conn_string) as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                result = await cur.fetchone()

    Args:
        connection_string: PostgreSQL connection string
        pool_name: Name prefix for logging

    Yields:
        AsyncConnection instance

    Raises:
        Exception: If connection cannot be acquired
    """
    pool = await get_or_create_plugin_pool(connection_string, pool_name=pool_name)

    # Log connection acquisition
    logger.debug(f"Acquiring connection from {pool_name}")

    acquire_start = time.time()
    try:
        async with pool.connection() as conn:
            acquire_time = time.time() - acquire_start
            logger.debug(f"Connection acquired from {pool_name} in {acquire_time*1000:.1f}ms")
            
            yield conn
            release_start = time.time()
        release_time = time.time() - release_start
        logger.debug(f"Connection returned to {pool_name} (release took {release_time*1000:.1f}ms)")
    except Exception as e:
        acquire_time = time.time() - acquire_start
        logger.error(
            f"Failed to acquire/use connection from {pool_name} after {acquire_time:.2f}s: {e}"
        )
        raise


async def close_plugin_pool(connection_string: str) -> None:
    """
    Close and remove a specific plugin connection pool.

    Args:
        connection_string: PostgreSQL connection string
    """
    pool_key = _create_pool_key(connection_string)

    async with _plugin_global_lock:
        pool = _plugin_pools.get(pool_key)
        if not pool:
            logger.warning(f"No plugin pool found for connection string: {connection_string}")
            return
        logger.info(f"Closing Postgres plugin pool: {pool.name}")
        try:
            await pool.close()
        except Exception as e:
            logger.exception(f"Error closing plugin pool: {e}")
        finally:
            del _plugin_pools[pool_key]


async def close_all_plugin_pools() -> None:
    """
    Close and remove all plugin connection pools.

    This should be called during application shutdown.
    """
    async with _plugin_global_lock:
        pool_keys = list(_plugin_pools.keys())

    for pool_key in pool_keys:
        try:
            async with _plugin_global_lock:
                if pool_key in _plugin_pools:
                    pool = _plugin_pools[pool_key]
                    logger.info(f"Closing PostgreSQL plugin pool: {pool.name}")
                    await pool.close()
                    del _plugin_pools[pool_key]
                    if pool_key in _plugin_locks:
                        del _plugin_locks[pool_key]
        except Exception as e:
            logger.error(f"Error closing plugin pool {pool_key}: {e}")


def _create_pool_key(connection_string: str) -> str:
    """
    Create a cache key from connection string.

    Uses hash to avoid storing passwords in keys while ensuring
    same credentials use same pool.

    Args:
        connection_string: PostgreSQL connection string

    Returns:
        Hash string as pool key
    """
    return hashlib.sha256(connection_string.encode()).hexdigest()


def get_plugin_pool_stats() -> Dict[str, Dict]:
    """
    Get statistics for all active plugin connection pools.

    Returns:
        Dictionary mapping pool keys to stats including:
        - name: Pool name
        - size: Current pool size
        - available: Available connections
        - waiting: Number of requests waiting
        - age_seconds: How long the pool has been active
        - last_health_check: Seconds since last health check
    """
    stats = {}
    for pool_key, pool in _plugin_pools.items():
        try:
            # Use built-in get_stats() method from psycopg_pool
            pool_stats = pool.get_stats()
            
            stats[pool_key[:12]] = {
                "name": pool.name,
                "size": pool_stats.get("pool_size", 0),
                "available": pool_stats.get("pool_available", 0),
                "waiting": pool_stats.get("requests_waiting", 0),
            }
        except Exception as e:
            logger.debug(f"Could not get stats for plugin pool {pool_key}: {e}")
            stats[pool_key[:12]] = {"error": str(e)}

    return stats


async def get_or_create_pool(
    connection_string: str,
    pool_name: str = "postgres_plugin",
    min_size: int = 1,
    max_size: int = 5,
    timeout: float = 30.0,
    max_waiting: int = 20,
    max_lifetime: float = 1800.0,
    max_idle: float = 300.0,
):
    """
    Get existing pool or create new one for the connection string.
    
    Wrapper for backward compatibility with legacy code.
    Delegates to get_or_create_plugin_pool.
    """
    return await get_or_create_plugin_pool(
        connection_string=connection_string,
        pool_name=pool_name,
        min_size=min_size,
        max_size=max_size,
        timeout=timeout,
        max_waiting=max_waiting,
        max_lifetime=max_lifetime,
        max_idle=max_idle,
    )


@asynccontextmanager
async def get_connection(connection_string: str, pool_name: str = "postgres_plugin"):
    """
    Get a connection from the pool as an async context manager.
    
    Wrapper for backward compatibility with legacy code.
    Delegates to get_plugin_connection.
    """
    async with get_plugin_connection(connection_string, pool_name=pool_name) as conn:
        yield conn


async def close_pool(connection_string: str) -> None:
    """
    Close and remove a specific connection pool.
    
    Wrapper for backward compatibility with legacy code.
    Delegates to close_plugin_pool.
    """
    await close_plugin_pool(connection_string)


async def close_all_pools() -> None:
    """
    Close and remove all connection pools.
    
    Wrapper for backward compatibility with legacy code.
    Called during worker shutdown to cleanup all plugin pools.
    Delegates to close_all_plugin_pools.
    """
    await close_all_plugin_pools()


def get_pool_stats() -> Dict[str, Dict]:
    """
    Get statistics for all active connection pools.
    
    Wrapper for backward compatibility with legacy code.
    Delegates to get_plugin_pool_stats.
    """
    return get_plugin_pool_stats()
