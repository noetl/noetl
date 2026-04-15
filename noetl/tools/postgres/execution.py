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
import re
import json
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


def _is_midstream_connection_drop_error(exc: Exception) -> bool:
    """Detect abrupt connection loss while reading command results."""
    msg = str(exc).lower()
    retry_markers = (
        "server closed the connection unexpectedly",
        "terminating connection due to administrator command",
        "connection is closed",
        "connection already closed",
        "consuming input failed",
        "connection reset by peer",
        "broken pipe",
        "ssl syscall error",
        "eof detected",
    )
    return any(marker in msg for marker in retry_markers)


def _strip_leading_sql_comments(command: str) -> str:
    text = (command or "").lstrip()
    while text:
        if text.startswith("/*"):
            end = text.find("*/")
            if end < 0:
                return text
            text = text[end + 2 :].lstrip()
            continue
        if text.startswith("--"):
            newline = text.find("\n")
            if newline < 0:
                return ""
            text = text[newline + 1 :].lstrip()
            continue
        break
    return text


def _sql_verb(command: str) -> str:
    stripped = _strip_leading_sql_comments(command)
    if not stripped:
        return ""
    match = re.match(r"([A-Za-z]+)", stripped)
    return match.group(1).upper() if match else ""


def _is_retry_safe_read_statement(command: str) -> bool:
    """Allow mid-stream reconnect retry only for read-only statements."""
    verb = _sql_verb(command)
    if verb not in {"SELECT", "SHOW", "EXPLAIN", "VALUES", "DESCRIBE", "DESC"}:
        return False
    # Conservative guard: avoid replaying locking reads.
    return "FOR UPDATE" not in (command or "").upper()


_DIRECT_CONN_LIMIT = max(1, _env_int("NOETL_POSTGRES_MAX_DIRECT_CONNECTIONS", 4))
_CONNECT_ATTEMPTS = max(1, _env_int("NOETL_POSTGRES_CONNECT_ATTEMPTS", 3))
_RETRY_BASE_DELAY_SECONDS = max(
    0.05, _env_float("NOETL_POSTGRES_CONNECT_RETRY_BASE_SECONDS", 0.2)
)
_RESULT_FETCH_BATCH_SIZE = max(1, _env_int("NOETL_POSTGRES_RESULT_FETCH_BATCH_SIZE", 200))
_MAX_RESULT_ROWS = max(0, _env_int("NOETL_POSTGRES_MAX_RESULT_ROWS", 1000))
_MAX_RESULT_BYTES = max(0, _env_int("NOETL_POSTGRES_MAX_RESULT_BYTES", 1024 * 1024))
_STATEMENT_TIMEOUT_MS = max(0, _env_int("NOETL_POSTGRES_STATEMENT_TIMEOUT_MS", 60000))
_IDLE_IN_TX_TIMEOUT_MS = max(
    0,
    _env_int("NOETL_POSTGRES_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS", 45000),
)
_direct_conn_semaphore = asyncio.Semaphore(_DIRECT_CONN_LIMIT)


class _TransientConnectionDrop(Exception):
    """Raised when a retryable connection drop happens mid-command stream."""

    def __init__(
        self,
        message: str,
        failed_command_index: int,
        partial_results: Dict[str, Dict],
    ):
        super().__init__(message)
        self.failed_command_index = int(failed_command_index)
        self.partial_results = dict(partial_results or {})


def _get_plugin_connection_ctx(connection_string: str, pool_name: str, **pool_params):
    from .pool import get_plugin_connection

    return get_plugin_connection(connection_string, pool_name=pool_name, **pool_params)


async def _apply_connection_session_guards(conn: AsyncConnection, conn_id: str) -> None:
    """Apply per-session timeout guards to prevent runaway transactions/queries."""
    if _STATEMENT_TIMEOUT_MS <= 0 and _IDLE_IN_TX_TIMEOUT_MS <= 0:
        return

    original_autocommit = conn.autocommit
    try:
        if not original_autocommit:
            await conn.set_autocommit(True)
        async with conn.cursor() as cursor:
            if _STATEMENT_TIMEOUT_MS > 0:
                await cursor.execute(
                    f"SET SESSION statement_timeout = {_STATEMENT_TIMEOUT_MS}"
                )
            if _IDLE_IN_TX_TIMEOUT_MS > 0:
                await cursor.execute(
                    "SET SESSION idle_in_transaction_session_timeout = "
                    f"{_IDLE_IN_TX_TIMEOUT_MS}"
                )
    except Exception as exc:
        logger.warning(
            "[CONN-%s] Failed to apply session timeout guards: %s",
            conn_id,
            exc,
        )
    finally:
        try:
            if conn.autocommit != original_autocommit:
                await conn.set_autocommit(original_autocommit)
        except Exception:
            pass


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
    next_command_index = 0
    aggregated_results: Dict[str, Dict] = {}
    for attempt in range(1, _CONNECT_ATTEMPTS + 1):
        try:
            async with _get_plugin_connection_ctx(
                connection_string, pool_name=pool_name, **pool_params
            ) as conn:
                conn_pid = conn.info.backend_pid if conn and conn.info else "unknown"
                logger.debug("[CONN-%s] Using pooled connection pid=%s", conn_id, conn_pid)
                await _apply_connection_session_guards(conn, conn_id)
                remaining_commands = commands[next_command_index:]
                exec_results = await execute_sql_statements_async(
                    conn,
                    remaining_commands,
                    start_index=next_command_index,
                )
                aggregated_results.update(exec_results)
                return aggregated_results
        except _TransientConnectionDrop as exc:
            aggregated_results.update(exc.partial_results)
            should_retry = attempt < _CONNECT_ATTEMPTS
            if should_retry:
                next_command_index = max(next_command_index, exc.failed_command_index)
                delay = _RETRY_BASE_DELAY_SECONDS * attempt + random.uniform(0, 0.15)
                logger.warning(
                    "[CONN-%s] Pooled transient drop attempt %s/%s at command_%s for %s:%s/%s; "
                    "retrying remaining commands in %.2fs (%s)",
                    conn_id,
                    attempt,
                    _CONNECT_ATTEMPTS,
                    exc.failed_command_index,
                    host,
                    port,
                    database,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                continue
            logger.exception(
                "[CONN-%s] Exhausted pooled retries after transient drop at command_%s on %s:%s/%s: %s",
                conn_id,
                exc.failed_command_index,
                host,
                port,
                database,
                exc,
            )
            raise
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
    next_command_index = 0
    aggregated_results: Dict[str, Dict] = {}
    for attempt in range(1, _CONNECT_ATTEMPTS + 1):
        conn = None
        try:
            conn = await AsyncConnection.connect(connection_string, row_factory=dict_row)
            conn_pid = conn.info.backend_pid if conn and conn.info else "unknown"
            logger.debug("[CONN-%s] Using direct connection pid=%s", conn_id, conn_pid)
            await _apply_connection_session_guards(conn, conn_id)
            remaining_commands = commands[next_command_index:]
            exec_results = await execute_sql_statements_async(
                conn,
                remaining_commands,
                start_index=next_command_index,
            )
            aggregated_results.update(exec_results)
            return aggregated_results
        except _TransientConnectionDrop as exc:
            aggregated_results.update(exc.partial_results)
            should_retry = attempt < _CONNECT_ATTEMPTS
            if should_retry:
                next_command_index = max(next_command_index, exc.failed_command_index)
                delay = _RETRY_BASE_DELAY_SECONDS * attempt + random.uniform(0, 0.15)
                logger.warning(
                    "[CONN-%s] Direct transient drop attempt %s/%s at command_%s for %s:%s/%s; "
                    "retrying remaining commands in %.2fs (%s)",
                    conn_id,
                    attempt,
                    _CONNECT_ATTEMPTS,
                    exc.failed_command_index,
                    host,
                    port,
                    database,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                continue
            logger.exception(
                "[CONN-%s] Exhausted direct retries after transient drop at command_%s on %s:%s/%s: %s",
                conn_id,
                exc.failed_command_index,
                host,
                port,
                database,
                exc,
            )
            raise
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
    start_index: int = 0,
) -> Dict[str, Dict]:
    """
    Execute multiple SQL statements asynchronously and collect results.
    """
    conn_pid = conn.info.backend_pid if conn and conn.info else "unknown"
    logger.debug("[PID-%s] Executing %s SQL statements", conn_pid, len(commands))
    results = {}

    for i, cmd in enumerate(commands):
        command_index = int(start_index) + int(i)
        cmd_summary = _sql_summary(cmd)
        logger.debug(
            "[PID-%s] SQL command %s/%s %s",
            conn_pid,
            command_index + 1,
            int(start_index) + len(commands),
            cmd_summary,
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
                        result_data, fetch_meta = await _fetch_result_rows_async(cursor)
                        column_names = [desc[0] for desc in cursor.description]
                        command_result = {
                            "status": "success",
                            "rows": result_data,
                            "row_count": len(result_data),
                            "columns": column_names,
                        }
                        if fetch_meta.get("truncated"):
                            command_result["truncated"] = True
                            command_result["truncation"] = {
                                "reason": fetch_meta.get("reason"),
                                "max_rows": fetch_meta.get("max_rows"),
                                "max_bytes": fetch_meta.get("max_bytes"),
                                "returned_bytes": fetch_meta.get("returned_bytes", 0),
                            }
                        results[f"command_{command_index}"] = command_result
                    else:
                        results[f"command_{command_index}"] = {
                            "status": "success",
                            "message": "Procedure executed successfully.",
                        }
            else:
                async with conn.transaction():
                    async with conn.cursor() as cursor:
                        await cursor.execute(cmd)
                        has_results = cursor.description is not None

                        if has_results:
                            result_data, fetch_meta = await _fetch_result_rows_async(cursor)
                            column_names = [desc[0] for desc in cursor.description]
                            command_result = {
                                "status": "success",
                                "rows": result_data,
                                "row_count": len(result_data),
                                "columns": column_names,
                            }
                            if fetch_meta.get("truncated"):
                                command_result["truncated"] = True
                                command_result["truncation"] = {
                                    "reason": fetch_meta.get("reason"),
                                    "max_rows": fetch_meta.get("max_rows"),
                                    "max_bytes": fetch_meta.get("max_bytes"),
                                    "returned_bytes": fetch_meta.get("returned_bytes", 0),
                                }
                            results[f"command_{command_index}"] = command_result
                        else:
                            results[f"command_{command_index}"] = {
                                "status": "success",
                                "row_count": cursor.rowcount,
                                "message": f"Command executed. {cursor.rowcount} rows affected.",
                            }
        except Exception as cmd_error:
            is_transient_drop = _is_midstream_connection_drop_error(cmd_error)
            retryable_command = _is_retry_safe_read_statement(cmd)
            if is_transient_drop and retryable_command:
                logger.warning(
                    "[PID-%s] SQL command_%s transient drop detected (%s); "
                    "will reconnect and retry remaining commands",
                    conn_pid,
                    command_index,
                    cmd_error,
                )
                raise _TransientConnectionDrop(
                    str(cmd_error),
                    failed_command_index=command_index,
                    partial_results=results,
                )
            logger.error(
                "[PID-%s] SQL command %s failed (%s): %s",
                conn_pid,
                command_index,
                cmd_summary,
                cmd_error,
            )
            results[f"command_{command_index}"] = {
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
                    command_index,
                    restore_error,
                )

    return results


async def _fetch_result_rows_async(cursor) -> tuple[List[Dict], Dict]:
    """
    Fetch and format result rows from async cursor with bounded memory usage.

    Returns:
        tuple(rows, meta)
        - rows: list of formatted row dictionaries.
        - meta: truncation metadata:
          {
            "truncated": bool,
            "reason": "max_rows" | "max_bytes" | None,
            "max_rows": int | None,
            "max_bytes": int | None,
            "returned_bytes": int,
          }
    """
    result_data = []
    returned_bytes = 0
    truncated_reason = None

    while True:
        rows = await cursor.fetchmany(_RESULT_FETCH_BATCH_SIZE)
        if not rows:
            break

        for row in rows:
            row_dict = {}
            for col_name, value in row.items():
                if isinstance(value, Decimal):
                    row_dict[col_name] = float(value)
                elif isinstance(value, (datetime, date, time)):
                    row_dict[col_name] = value.isoformat()
                else:
                    row_dict[col_name] = value

            row_bytes = 0
            try:
                row_bytes = len(json.dumps(row_dict, default=str).encode("utf-8"))
            except Exception:
                row_bytes = len(str(row_dict).encode("utf-8"))

            if _MAX_RESULT_BYTES > 0 and (returned_bytes + row_bytes) > _MAX_RESULT_BYTES:
                truncated_reason = "max_bytes"
                break

            result_data.append(row_dict)
            returned_bytes += row_bytes

            if _MAX_RESULT_ROWS > 0 and len(result_data) >= _MAX_RESULT_ROWS:
                truncated_reason = "max_rows"
                break

        if truncated_reason:
            break

    logger.debug(
        "Fetched %s rows from cursor (bytes=%s truncated=%s)",
        len(result_data),
        returned_bytes,
        bool(truncated_reason),
    )
    if truncated_reason:
        logger.warning(
            "Postgres result truncated due to %s (rows=%s max_rows=%s bytes=%s max_bytes=%s)",
            truncated_reason,
            len(result_data),
            _MAX_RESULT_ROWS,
            returned_bytes,
            _MAX_RESULT_BYTES,
        )

    return result_data, {
        "truncated": bool(truncated_reason),
        "reason": truncated_reason,
        "max_rows": _MAX_RESULT_ROWS if _MAX_RESULT_ROWS > 0 else None,
        "max_bytes": _MAX_RESULT_BYTES if _MAX_RESULT_BYTES > 0 else None,
        "returned_bytes": returned_bytes,
    }
