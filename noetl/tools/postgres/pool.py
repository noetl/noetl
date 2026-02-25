"""
PostgreSQL connection pool manager for plugin executions.

This module provides a simplified interface to the core pool manager
for postgres plugin executions. All actual pooling logic is in noetl.core.db.pool.
"""
import hashlib
import asyncio
import os
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
    'close_execution_pools',
]

# Per-credential pool registry for plugins
_plugin_pools: Dict[str, AsyncConnectionPool[AsyncConnection[DictRow]]] = {}
_plugin_locks: Dict[str, asyncio.Lock] = {}
_plugin_global_lock = asyncio.Lock()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default


_DEFAULT_POOL_MIN_SIZE = max(1, _env_int("NOETL_POSTGRES_POOL_MIN_SIZE", 1))
_DEFAULT_POOL_MAX_SIZE = max(1, _env_int("NOETL_POSTGRES_POOL_MAX_SIZE", 12))
_DEFAULT_POOL_TIMEOUT = max(1.0, _env_float("NOETL_POSTGRES_POOL_TIMEOUT_SECONDS", 60.0))
_DEFAULT_POOL_MAX_WAITING = max(1, _env_int("NOETL_POSTGRES_POOL_MAX_WAITING", 100))
_DEFAULT_POOL_MAX_LIFETIME = max(60.0, _env_float("NOETL_POSTGRES_POOL_MAX_LIFETIME_SECONDS", 3600.0))
_DEFAULT_POOL_MAX_IDLE = max(30.0, _env_float("NOETL_POSTGRES_POOL_MAX_IDLE_SECONDS", 300.0))


# ============================================================================
# Per-Credential Pool Registry (for plugin executions)
# ============================================================================

async def get_or_create_plugin_pool(
        connection_string: str,
        pool_name: str = "postgres_plugin",
        min_size: int = _DEFAULT_POOL_MIN_SIZE,
        max_size: int = _DEFAULT_POOL_MAX_SIZE,
        timeout: float = _DEFAULT_POOL_TIMEOUT,
        max_waiting: int = _DEFAULT_POOL_MAX_WAITING,
        max_lifetime: float = _DEFAULT_POOL_MAX_LIFETIME,
        max_idle: float = _DEFAULT_POOL_MAX_IDLE,
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
    # Ensure timeout is never None (psycopg_pool requires numeric timeout)
    if timeout is None:
        timeout = _DEFAULT_POOL_TIMEOUT

    # Create a hash key from connection string + pool name
    # This allows different pools for same credentials with different names
    pool_key = _create_pool_key(connection_string + "||" + pool_name)

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
async def get_plugin_connection(connection_string: str, pool_name: str = "postgres_plugin", **pool_kwargs):
    """
    Get a connection from the plugin pool as an async context manager.
    
    This is the primary interface for plugin code to get database connections.
    Connections are automatically returned to the pool when the context exits.
    
    Args:
        connection_string: PostgreSQL connection string
        pool_name: Name prefix for the pool (for logging/monitoring)
        **pool_kwargs: Pool configuration parameters:
            - timeout: Timeout for acquiring connection (None=default 10s, -1=infinite wait)
            - min_size: Minimum connections (default from env, fallback 1)
            - max_size: Maximum connections (default from env, fallback 5)
            - max_waiting: Max requests waiting (default from env, fallback 100)
            - max_lifetime: Connection max lifetime in seconds (default 3600)
            - max_idle: Connection max idle time in seconds (default 300)
    
    Yields:
        AsyncConnection with dict_row factory
    
    Usage:
        async with get_plugin_connection(conn_string, timeout=300, max_size=50) as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                result = await cur.fetchone()
    
    Raises:
        Exception: If pool creation or connection acquisition fails
    """
    # Handle timeout parameter: None = default (10s), -1 = infinite, else = specified value
    if 'timeout' in pool_kwargs:
        timeout = pool_kwargs['timeout']
        pool_kwargs['timeout'] = 10.0 if timeout is None else (None if timeout == -1 else timeout)
    
    pool = await get_or_create_plugin_pool(connection_string, pool_name, **pool_kwargs)

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


async def close_execution_pools(execution_id: str) -> int:
    """
    Close all pools associated with a specific execution_id.
    
    This is called when a playbook execution completes to clean up
    execution-scoped pools (pools with name like exec_<execution_id>).
    
    Args:
        execution_id: The execution identifier
        
    Returns:
        Number of pools closed
        
    Example:
        >>> await close_execution_pools("534308556917440716")
        2  # Closed 2 pools for this execution
    """
    closed_count = 0
    pool_prefix = f"exec_{execution_id}"
    pools_to_close = []
    
    # Identify pools to close
    async with _plugin_global_lock:
        for pool_key, pool in list(_plugin_pools.items()):
            if pool.name and pool.name.startswith(pool_prefix):
                pools_to_close.append((pool_key, pool))
    
    # Close identified pools
    for pool_key, pool in pools_to_close:
        try:
            logger.info(f"Closing execution pool: {pool.name} (execution_id={execution_id})")
            await pool.close()
            
            async with _plugin_global_lock:
                if pool_key in _plugin_pools:
                    del _plugin_pools[pool_key]
                if pool_key in _plugin_locks:
                    del _plugin_locks[pool_key]
            
            closed_count += 1
        except Exception as e:
            logger.error(f"Failed to close execution pool {pool.name}: {e}")
    
    if closed_count > 0:
        logger.info(f"Closed {closed_count} execution pools for execution_id={execution_id}")
    
    return closed_count


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
