import time
import math
from typing import Optional
from fastapi import HTTPException
from .core import (
    logger,
    _DB_UNAVAILABLE_ERROR_MARKERS,
    _DB_UNAVAILABLE_BACKOFF_BASE_SECONDS,
    _DB_UNAVAILABLE_BACKOFF_MAX_SECONDS,
    _DB_UNAVAILABLE_SHORT_CIRCUIT,
)

_db_unavailable_failure_streak: int = 0
_db_unavailable_backoff_until_monotonic: float = 0.0

def _db_unavailable_retry_after() -> Optional[str]:
    remaining = _db_unavailable_backoff_until_monotonic - time.monotonic()
    if remaining <= 0:
        return None
    return str(max(1, int(math.ceil(remaining))))

def _record_db_operation_success() -> None:
    global _db_unavailable_failure_streak, _db_unavailable_backoff_until_monotonic
    if _db_unavailable_failure_streak > 0 or _db_unavailable_backoff_until_monotonic > time.monotonic():
        logger.info(
            "[DB-RECOVERY] Connectivity recovered; clearing outage backoff (previous_streak=%s)",
            _db_unavailable_failure_streak,
        )
    _db_unavailable_failure_streak = 0
    _db_unavailable_backoff_until_monotonic = 0.0

def _is_db_unavailable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if not message: return False
    return any(marker in message for marker in _DB_UNAVAILABLE_ERROR_MARKERS)

def _record_db_unavailable_failure(exc: Exception, *, operation: str) -> Optional[str]:
    global _db_unavailable_failure_streak, _db_unavailable_backoff_until_monotonic
    if not _is_db_unavailable_error(exc): return None
    _db_unavailable_failure_streak = max(1, _db_unavailable_failure_streak + 1)
    exponent = min(_db_unavailable_failure_streak - 1, 6)
    next_backoff_seconds = min(
        _DB_UNAVAILABLE_BACKOFF_BASE_SECONDS * (2 ** exponent),
        _DB_UNAVAILABLE_BACKOFF_MAX_SECONDS,
    )
    now = time.monotonic()
    _db_unavailable_backoff_until_monotonic = max(_db_unavailable_backoff_until_monotonic, now + next_backoff_seconds)
    retry_after = _db_unavailable_retry_after() or str(max(1, int(math.ceil(next_backoff_seconds))))
    logger.warning("[DB-UNAVAILABLE] operation=%s streak=%s retry_after=%ss error=%s",
                   operation, _db_unavailable_failure_streak, retry_after, exc)
    return retry_after

def _raise_if_db_short_circuit_enabled(*, operation: str) -> None:
    if not _DB_UNAVAILABLE_SHORT_CIRCUIT: return
    retry_after = _db_unavailable_retry_after()
    if retry_after is None: return
    raise HTTPException(
        status_code=503,
        detail={
            "code": "db_unavailable",
            "message": f"Database temporarily unavailable during {operation}; retry shortly",
        },
        headers={"Retry-After": retry_after},
    )

from noetl.core.db.pool import get_server_pool_stats
from fastapi import APIRouter

router = APIRouter()

@router.get("/pool/status")
async def get_pool_status():
    """
    Return real-time server DB pool telemetry.
    """
    stats = get_server_pool_stats()
    if not stats:
        return {
            "pool_min": 0, "pool_max": 0, "pool_size": 0,
            "pool_available": 0, "requests_waiting": 0,
            "utilization": 0.0, "slots_available": 0,
            "status": "unavailable",
        }
    return {**stats, "status": "ok"}

async def _next_snowflake_id(cur) -> int:
    await cur.execute("SELECT noetl.snowflake_id() AS snowflake_id")
    row = await cur.fetchone()
    if not row: raise RuntimeError("Failed to generate snowflake ID from database")
    value = row.get("snowflake_id") if isinstance(row, dict) else row[0]
    return int(value)

async def _next_snowflake_ids(cur, count: int) -> list[int]:
    if count <= 0: return []
    await cur.execute("SELECT noetl.snowflake_id() FROM generate_series(1, %s)", (count,))
    rows = await cur.fetchall()
    return [int(row.get("snowflake_id") if isinstance(row, dict) else row[0]) for row in rows]
