"""
PostgreSQL SQL execution with resilient pooling and bounded direct concurrency.

This module keeps database pressure predictable in distributed runs by:
- Preferring pooled connections when requested by caller
- Bounding direct connection concurrency with a process-local semaphore
- Retrying transient connection saturation failures with backoff
- Logging SQL metadata (operation/length) instead of raw SQL/payload content
"""

import asyncio
import os
import random
import time as time_module
from decimal import Decimal
from datetime import date, datetime, time
from typing import Dict, List

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


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


def _sql_summary(command: str) -> str:
    trimmed = (command or "").strip()
    if not trimmed:
        return "UNKNOWN len=0"
    operation = trimmed.split(None, 1)[0].upper()
    return f"{operation} len={len(trimmed)}"


def _is_retryable_connection_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    retry_markers = (
        "remaining connection slots are reserved",
        "too many clients",
        "server login has been failing",
        "connection is lost",
        "connection refused",
        "timeout expired",
        "could not connect",
    )
    return any(marker in msg for marker in retry_markers)


_DIRECT_CONN_LIMIT = max(1, _env_int("NOETL_POSTGRES_MAX_DIRECT_CONNECTIONS", 4))
_CONNECT_ATTEMPTS = max(1, _env_int("NOETL_POSTGRES_CONNECT_ATTEMPTS", 3))
_RETRY_BASE_DELAY_SECONDS = max(
    0.05, _env_float("NOETL_POSTGRES_CONNECT_RETRY_BASE_SECONDS", 0.2)
)
_direct_conn_semaphore = asyncio.Semaphore(_DIRECT_CONN_LIMIT)


async def _execute_with_pooled_connection(
    connection_string: str,
    commands: List[str],
    conn_id: str,
    host: str,
    port: str,
    database: str,
    pool_name: str,
    pool_params: dict,
) -> Dict[str, Dict]:
    from .pool import get_plugin_connection

    for attempt in range(1, _CONNECT_ATTEMPTS + 1):
        try:
            async with get_plugin_connection(
                connection_string, pool_name=pool_name, **pool_params
            ) as conn:
                conn_pid = conn.info.backend_pid if conn and conn.info else "unknown"
                logger.debug("[CONN-%s] Using pooled connection pid=%s", conn_id, conn_pid)
                return await execute_sql_statements_async(conn, commands)
        except Exception as exc:
            should_retry = (
                attempt < _CONNECT_ATTEMPTS and _is_retryable_connection_error(exc)
            )
            if should_retry:
                delay = _RETRY_BASE_DELAY_SECONDS * attempt + random.uniform(0, 0.15)
                logger.warning(
                    "[CONN-%s] Pooled attempt %s/%s failed for %s:%s/%s; retrying in %.2fs (%s)",
                    conn_id,
                    attempt,
                    _CONNECT_ATTEMPTS,
                    host,
                    port,
                    database,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                continue
            logger.exception(
                "[CONN-%s] Failed pooled SQL execution on %s:%s/%s: %s",
                conn_id,
                host,
                port,
                database,
                exc,
            )
            raise

    raise RuntimeError("unreachable")


async def _execute_with_direct_connection(
    connection_string: str,
    commands: List[str],
    conn_id: str,
    host: str,
    port: str,
    database: str,
) -> Dict[str, Dict]:
    for attempt in range(1, _CONNECT_ATTEMPTS + 1):
        conn = None
        try:
            conn = await AsyncConnection.connect(connection_string, row_factory=dict_row)
            conn_pid = conn.info.backend_pid if conn and conn.info else "unknown"
            logger.debug("[CONN-%s] Using direct connection pid=%s", conn_id, conn_pid)
            return await execute_sql_statements_async(conn, commands)
        except Exception as exc:
            should_retry = (
                attempt < _CONNECT_ATTEMPTS and _is_retryable_connection_error(exc)
            )
            if should_retry:
                delay = _RETRY_BASE_DELAY_SECONDS * attempt + random.uniform(0, 0.15)
                logger.warning(
                    "[CONN-%s] Direct attempt %s/%s failed for %s:%s/%s; retrying in %.2fs (%s)",
                    conn_id,
                    attempt,
                    _CONNECT_ATTEMPTS,
                    host,
                    port,
                    database,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                continue
            logger.exception(
                "[CONN-%s] Failed direct SQL execution on %s:%s/%s: %s",
                conn_id,
                host,
                port,
                database,
                exc,
            )
            raise
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass

    raise RuntimeError("unreachable")


async def execute_sql_with_connection(
    connection_string: str,
    commands: List[str],
    host: str = "unknown",
    port: str = "unknown",
    database: str = "unknown",
    pool: bool = False,
    pool_name: str = None,
    pool_params: dict = None,
) -> Dict[str, Dict]:
    """
    Execute SQL statements using pooled or direct connections.
    """
    conn_id = f"{host}:{port}/{database}-{int(time_module.time() * 1000)}"
    pool_params = pool_params or {}

    if pool:
        effective_pool_name = pool_name or f"pg_{database}"
        logger.info(
            "[CONN-%s] pooled mode pool=%s target=%s:%s/%s commands=%s",
            conn_id,
            effective_pool_name,
            host,
            port,
            database,
            len(commands),
        )
        return await _execute_with_pooled_connection(
            connection_string=connection_string,
            commands=commands,
            conn_id=conn_id,
            host=host,
            port=port,
            database=database,
            pool_name=effective_pool_name,
            pool_params=pool_params,
        )

    logger.info(
        "[CONN-%s] direct mode target=%s:%s/%s commands=%s concurrency_limit=%s",
        conn_id,
        host,
        port,
        database,
        len(commands),
        _DIRECT_CONN_LIMIT,
    )
    async with _direct_conn_semaphore:
        return await _execute_with_direct_connection(
            connection_string=connection_string,
            commands=commands,
            conn_id=conn_id,
            host=host,
            port=port,
            database=database,
        )


async def execute_sql_statements_async(
    conn: AsyncConnection,
    commands: List[str],
) -> Dict[str, Dict]:
    """
    Execute multiple SQL statements asynchronously and collect results.
    """
    conn_pid = conn.info.backend_pid if conn and conn.info else "unknown"
    logger.debug("[PID-%s] Executing %s SQL statements", conn_pid, len(commands))
    results = {}

    for i, cmd in enumerate(commands):
        cmd_summary = _sql_summary(cmd)
        logger.debug(
            "[PID-%s] SQL command %s/%s %s", conn_pid, i + 1, len(commands), cmd_summary
        )
        normalized = cmd.strip().upper()
        is_call = normalized.startswith("CALL")
        is_autocommit_ddl = (
            normalized.startswith("CREATE DATABASE")
            or normalized.startswith("DROP DATABASE")
            or normalized.startswith("ALTER DATABASE")
        )
        original_autocommit = conn.autocommit

        try:
            if is_call or is_autocommit_ddl:
                await conn.set_autocommit(True)
                async with conn.cursor() as cursor:
                    await cursor.execute(cmd)
                    has_results = cursor.description is not None

                    if has_results:
                        result_data = await _fetch_result_rows_async(cursor)
                        column_names = [desc[0] for desc in cursor.description]
                        results[f"command_{i}"] = {
                            "status": "success",
                            "rows": result_data,
                            "row_count": len(result_data),
                            "columns": column_names,
                        }
                    else:
                        results[f"command_{i}"] = {
                            "status": "success",
                            "message": "Procedure executed successfully.",
                        }
            else:
                async with conn.transaction():
                    async with conn.cursor() as cursor:
                        await cursor.execute(cmd)
                        has_results = cursor.description is not None

                        if has_results:
                            result_data = await _fetch_result_rows_async(cursor)
                            column_names = [desc[0] for desc in cursor.description]
                            results[f"command_{i}"] = {
                                "status": "success",
                                "rows": result_data,
                                "row_count": len(result_data),
                                "columns": column_names,
                            }
                        else:
                            results[f"command_{i}"] = {
                                "status": "success",
                                "row_count": cursor.rowcount,
                                "message": f"Command executed. {cursor.rowcount} rows affected.",
                            }
        except Exception as cmd_error:
            logger.error(
                "[PID-%s] SQL command %s failed (%s): %s",
                conn_pid,
                i,
                cmd_summary,
                cmd_error,
            )
            results[f"command_{i}"] = {
                "status": "error",
                "message": str(cmd_error),
            }
        finally:
            try:
                if conn.autocommit != original_autocommit:
                    await conn.set_autocommit(original_autocommit)
            except Exception as restore_error:
                logger.debug(
                    "[PID-%s] Failed to restore autocommit for command %s: %s",
                    conn_pid,
                    i,
                    restore_error,
                )

    return results


async def _fetch_result_rows_async(cursor) -> List[Dict]:
    """
    Fetch and format result rows from async cursor.
    """
    rows = await cursor.fetchall()
    logger.debug("Fetched %s rows from cursor", len(rows))
    result_data = []

    for row in rows:
        row_dict = {}
        for col_name, value in row.items():
            if isinstance(value, dict) or (
                isinstance(value, str) and (value.startswith("{") or value.startswith("["))
            ):
                row_dict[col_name] = value
            elif isinstance(value, Decimal):
                row_dict[col_name] = float(value)
            elif isinstance(value, (datetime, date, time)):
                row_dict[col_name] = value.isoformat()
            else:
                row_dict[col_name] = value

        result_data.append(row_dict)

    return result_data
